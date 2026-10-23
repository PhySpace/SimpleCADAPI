"""Private .scadbrep container codec shared by extraction and modeling."""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any

from ..errors import SimpleCADMessageError
import simplecadapi._cpp.occt as _occt
from simplecadapi._cpp.occt.TopAbs import TopAbs_SHELL, TopAbs_SOLID

from .canonical_json import canonical_json_bytes, parse_canonical_json
from ..kernel.ocp_brep_snapshot import (
    RootKind,
    decode_shape,
    encode_shape,
    face_fingerprints,
    has_triangulation,
    shape_descriptor,
)


MAGIC = b"SCADBREP"
HEADER = struct.Struct(">8sHHIQQ")
MAJOR_VERSION = 1
MINOR_VERSION = 0
PROFILE = f"scadbrep-1-ocp-{_occt.__version__}-bintools-v4-no-mesh"
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
BINTOOLS_V4_PREAMBLE = b"\nOpen CASCADE Topology V4, (c) Open Cascade\n"
_BINTOOLS_TEXT_HEADER = re.compile(
    rb"\A\nOpen CASCADE Topology V4, \(c\) Open Cascade\n"
    rb"Locations [0-9]+\nCurve2ds [0-9]+\n"
)
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_FACE_ID_PATTERN = re.compile(r"face:(0|[1-9][0-9]*)")


class BRepRegionError(SimpleCADMessageError):
    """Raised when a .scadbrep container is invalid or unsupported."""

    operation = "brep_region"


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def encode_artifact(manifest: dict[str, Any], payload: bytes) -> bytes:
    manifest_bytes = canonical_json_bytes(manifest)
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ValueError("BREP region snapshot manifest exceeds the size limit")
    artifact = (
        HEADER.pack(
            MAGIC,
            MAJOR_VERSION,
            MINOR_VERSION,
            0,
            len(manifest_bytes),
            len(payload),
        )
        + manifest_bytes
        + payload
    )
    if len(artifact) > MAX_ARTIFACT_BYTES:
        raise ValueError("BREP region snapshot exceeds the size limit")
    return artifact


def _require_exact_keys(
    name: str,
    value: Any,
    *,
    required: set[str],
    optional: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BRepRegionError(f"BREP region snapshot {name} must be an object")
    keys = set(value)
    missing = sorted(required - keys)
    extra = sorted(keys - required - optional)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unknown " + ", ".join(extra))
        raise BRepRegionError(
            f"BREP region snapshot {name} schema is invalid: {'; '.join(details)}"
        )
    return value


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _validate_manifest(manifest: Any, payload: bytes) -> tuple[dict[str, Any], RootKind]:
    manifest = _require_exact_keys(
        "manifest",
        manifest,
        required={
            "format",
            "schema_version",
            "profile",
            "coordinate_system",
            "generator",
            "source",
            "region",
            "shape",
            "provenance",
        },
    )
    if (
        manifest.get("format") != "simplecad-brep-region"
        or manifest.get("schema_version") != "1.0"
        or manifest.get("profile") != PROFILE
    ):
        raise BRepRegionError("BREP region snapshot manifest profile is unsupported")
    coordinate_system = _require_exact_keys(
        "coordinate_system",
        manifest["coordinate_system"],
        required={"length_unit"},
    )
    if coordinate_system["length_unit"] != "mm":
        raise BRepRegionError("BREP region snapshot length unit must be mm")
    generator = _require_exact_keys(
        "generator", manifest["generator"], required={"ocp_version"}
    )
    if generator["ocp_version"] != str(_occt.__version__):
        raise BRepRegionError(
            "BREP region snapshot OCP version does not match this runtime profile"
        )
    source = _require_exact_keys(
        "source",
        manifest["source"],
        required={
            "format",
            "name",
            "byte_length",
            "content_hash",
            "transferred_root_count",
        },
    )
    if source["format"] != "step" or not isinstance(source["name"], str):
        raise BRepRegionError("BREP region snapshot source record is invalid")
    if not _is_count(source["byte_length"]) or not _is_count(
        source["transferred_root_count"]
    ) or source["transferred_root_count"] < 1:
        raise BRepRegionError("BREP region snapshot source counts are invalid")
    if not _is_sha256(source["content_hash"]):
        raise BRepRegionError("BREP region snapshot source hash is invalid")
    region = _require_exact_keys(
        "region",
        manifest["region"],
        required={"kind", "source_face_ids"},
    )
    if region["kind"] not in {"complete_solid", "face_shell"}:
        raise BRepRegionError("BREP region snapshot region kind is unsupported")
    if not isinstance(region["source_face_ids"], list) or not all(
        isinstance(value, str) and _FACE_ID_PATTERN.fullmatch(value) is not None
        for value in region["source_face_ids"]
    ):
        raise BRepRegionError("BREP region snapshot source face ids are invalid")
    if len(set(region["source_face_ids"])) != len(region["source_face_ids"]):
        raise BRepRegionError("BREP region snapshot source face ids are not unique")
    shape_record = _require_exact_keys(
        "shape",
        manifest["shape"],
        required={
            "root_shape_type",
            "valid",
            "solid_count",
            "shell_count",
            "face_count",
            "edge_count",
            "vertex_count",
            "encoding",
            "format_version",
            "triangulation",
            "normals",
            "byte_length",
            "content_hash",
            "face_fingerprints",
        },
        optional={"closed", "volume"},
    )
    root_kind = shape_record["root_shape_type"]
    if root_kind not in {"shell", "solid"}:
        raise BRepRegionError("BREP region snapshot root shape type is unsupported")
    if region["kind"] != ("complete_solid" if root_kind == "solid" else "face_shell"):
        raise BRepRegionError("BREP region snapshot region kind and root shape disagree")
    if shape_record["valid"] is not True:
        raise BRepRegionError("BREP region snapshot must declare a valid shape")
    for name in (
        "solid_count",
        "shell_count",
        "face_count",
        "edge_count",
        "vertex_count",
        "byte_length",
    ):
        if not _is_count(shape_record[name]):
            raise BRepRegionError(f"BREP region snapshot {name} is invalid")
    if shape_record["face_count"] < 1:
        raise BRepRegionError("BREP region snapshot must contain at least one face")
    if root_kind == "solid":
        if shape_record["solid_count"] != 1 or shape_record["shell_count"] < 1:
            raise BRepRegionError("BREP region snapshot solid counts are invalid")
        if "closed" in shape_record or not _is_finite_number(
            shape_record.get("volume")
        ) or float(shape_record["volume"]) <= 0.0:
            raise BRepRegionError("BREP region snapshot solid descriptor is invalid")
    else:
        if shape_record["solid_count"] != 0 or shape_record["shell_count"] != 1:
            raise BRepRegionError("BREP region snapshot shell counts are invalid")
        if "volume" in shape_record or not isinstance(
            shape_record.get("closed"), bool
        ):
            raise BRepRegionError("BREP region snapshot shell descriptor is invalid")
    if shape_record["encoding"] != "occt-bintools":
        raise BRepRegionError("BREP region snapshot encoding is unsupported")
    if shape_record["format_version"] != 4:
        raise BRepRegionError("BREP region snapshot BinTools version is unsupported")
    if shape_record["triangulation"] is not False or shape_record["normals"] is not False:
        raise BRepRegionError("BREP region snapshot mesh profile is unsupported")
    if not _is_sha256(shape_record["content_hash"]):
        raise BRepRegionError("BREP region snapshot payload hash is invalid")
    if shape_record["content_hash"] != sha256_bytes(payload):
        raise BRepRegionError("BREP region snapshot payload SHA-256 does not match")
    if shape_record["byte_length"] != len(payload):
        raise BRepRegionError("BREP region snapshot payload length does not match")
    if not payload.startswith(BINTOOLS_V4_PREAMBLE):
        raise BRepRegionError("BREP region snapshot payload is not BinTools V4")
    if _BINTOOLS_TEXT_HEADER.match(payload) is None:
        raise BRepRegionError("BREP region snapshot BinTools text header is invalid")
    face_records = shape_record["face_fingerprints"]
    if not isinstance(face_records, list) or len(face_records) != shape_record[
        "face_count"
    ]:
        raise BRepRegionError("BREP region snapshot has no face fingerprint records")
    for record in face_records:
        record = _require_exact_keys(
            "face fingerprint",
            record,
            required={
                "surface_type",
                "orientation",
                "area",
                "centroid",
                "edge_count",
                "source_face_id",
            },
        )
        if not isinstance(record["surface_type"], str) or not record["surface_type"]:
            raise BRepRegionError("BREP region snapshot face surface type is invalid")
        if record["orientation"] not in {
            "TopAbs_FORWARD",
            "TopAbs_REVERSED",
            "TopAbs_INTERNAL",
            "TopAbs_EXTERNAL",
        }:
            raise BRepRegionError("BREP region snapshot face orientation is invalid")
        if not _is_finite_number(record["area"]) or float(record["area"]) < 0.0:
            raise BRepRegionError("BREP region snapshot face area is invalid")
        if (
            not isinstance(record["centroid"], list)
            or len(record["centroid"]) != 3
            or not all(_is_finite_number(value) for value in record["centroid"])
        ):
            raise BRepRegionError("BREP region snapshot face centroid is invalid")
        if not _is_count(record["edge_count"]):
            raise BRepRegionError("BREP region snapshot face edge count is invalid")
        if record["source_face_id"] not in region["source_face_ids"]:
            raise BRepRegionError("BREP region snapshot face source id is invalid")
    if [record["source_face_id"] for record in face_records] != region[
        "source_face_ids"
    ]:
        raise BRepRegionError("BREP region snapshot face provenance mapping drifted")
    provenance = _require_exact_keys(
        "provenance",
        manifest["provenance"],
        required={
            "evidence_origin",
            "construction",
            "topology_origin",
            "runtime_dependency",
            "target_step_required_at_replay",
        },
    )
    if provenance != {
        "evidence_origin": "copied",
        "construction": "exact_transcription",
        "topology_origin": "retained",
        "runtime_dependency": "embedded_target_derived",
        "target_step_required_at_replay": False,
    }:
        raise BRepRegionError("BREP region snapshot provenance profile is unsupported")
    return manifest, root_kind


def decode_artifact(data: bytes, *, expected_root_kind: RootKind | None = None):
    if len(data) > MAX_ARTIFACT_BYTES:
        raise BRepRegionError("BREP region snapshot exceeds the size limit")
    if len(data) < HEADER.size:
        raise BRepRegionError("BREP region snapshot is truncated")
    magic, major, minor, flags, manifest_size, payload_size = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise BRepRegionError("BREP region snapshot has invalid magic")
    if major != MAJOR_VERSION or minor != MINOR_VERSION:
        raise BRepRegionError(
            f"Unsupported BREP region snapshot version: {major}.{minor}"
        )
    if flags != 0:
        raise BRepRegionError("BREP region snapshot uses unsupported flags")
    if manifest_size > MAX_MANIFEST_BYTES:
        raise BRepRegionError("BREP region snapshot manifest exceeds the size limit")
    expected_size = HEADER.size + manifest_size + payload_size
    if len(data) != expected_size:
        raise BRepRegionError("BREP region snapshot length does not match its header")
    manifest_start = HEADER.size
    payload_start = manifest_start + manifest_size
    manifest = parse_canonical_json(data[manifest_start:payload_start])
    payload = data[payload_start:]
    manifest, root_kind = _validate_manifest(manifest, payload)
    shape_record = manifest["shape"]
    if expected_root_kind is not None and root_kind != expected_root_kind:
        raise BRepRegionError(
            f"BREP region snapshot contains {root_kind}, expected {expected_root_kind}"
        )
    shape = decode_shape(payload, root_kind)
    expected_shape_type = TopAbs_SOLID if root_kind == "solid" else TopAbs_SHELL
    if shape.ShapeType() != expected_shape_type:
        raise BRepRegionError(
            f"BREP region payload root is not declared {root_kind} topology"
        )
    if has_triangulation(shape):
        raise BRepRegionError("BREP region snapshot payload contains triangulation")
    if len(encode_shape(shape, root_kind)) != len(payload):
        raise BRepRegionError("BREP region snapshot payload has trailing or missing data")
    actual = shape_descriptor(shape, root_kind)
    descriptor_keys = [
        "root_shape_type",
        "valid",
        "solid_count",
        "shell_count",
        "face_count",
        "edge_count",
        "vertex_count",
        "volume" if root_kind == "solid" else "closed",
    ]
    for key in descriptor_keys:
        if shape_record.get(key) != actual[key]:
            raise BRepRegionError(
                f"BREP region snapshot shape descriptor drifted at {key}"
            )
    stored_face_records = shape_record["face_fingerprints"]
    actual_face_records = face_fingerprints(shape)
    stripped_records = [
        {key: value for key, value in record.items() if key != "source_face_id"}
        if isinstance(record, dict)
        else record
        for record in stored_face_records
    ]
    if stripped_records != actual_face_records:
        raise BRepRegionError("BREP region snapshot face order or geometry drifted")
    source_face_ids = manifest["region"]["source_face_ids"]
    if len(source_face_ids) != actual["face_count"]:
        raise BRepRegionError("BREP region snapshot source face mapping is incomplete")
    if [record.get("source_face_id") for record in stored_face_records] != source_face_ids:
        raise BRepRegionError("BREP region snapshot face provenance mapping drifted")
    return shape, manifest


def read_artifact(
    path: str | Path,
    sha256: str,
    *,
    expected_root_kind: RootKind,
    replay_root: Path | None = None,
):
    source = Path(path)
    if replay_root is not None:
        root = replay_root.resolve()
        source = root / source
        resolved = source.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise BRepRegionError(
                "BREP region snapshot escapes the replay working directory"
            ) from exc
        current = root
        for part in Path(path).parts:
            current = current / part
            if current.is_symlink():
                raise BRepRegionError(
                    "BREP region snapshot path must not contain symbolic links"
                )
            try:
                component_stat = current.stat(follow_symlinks=False)
            except OSError as exc:
                raise BRepRegionError(
                    f"Could not inspect BREP region snapshot path component: {current}"
                ) from exc
            if getattr(component_stat, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
            ):
                raise BRepRegionError(
                    "BREP region snapshot path must not contain reparse points"
                )
        source = resolved
    try:
        expected_stat = source.stat(follow_symlinks=False)
    except OSError as exc:
        raise BRepRegionError(f"Could not inspect BREP region snapshot: {source}") from exc
    if not stat.S_ISREG(expected_stat.st_mode):
        raise BRepRegionError("BREP region snapshot must be a regular file")
    if getattr(expected_stat, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    ):
        raise BRepRegionError("BREP region snapshot path must not be a reparse point")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise BRepRegionError(f"Could not open BREP region snapshot: {source}") from exc
    try:
        actual_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(actual_stat.st_mode)
            or actual_stat.st_dev != expected_stat.st_dev
            or actual_stat.st_ino != expected_stat.st_ino
            or actual_stat.st_size != expected_stat.st_size
        ):
            raise BRepRegionError(
                "BREP region snapshot changed while it was being opened"
            )
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_ARTIFACT_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise BRepRegionError("BREP region snapshot exceeds the size limit")
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    actual_hash = sha256_bytes(data)
    expected_hash = str(sha256).strip().lower()
    if not expected_hash.startswith("sha256:"):
        expected_hash = "sha256:" + expected_hash
    if expected_hash != actual_hash:
        raise BRepRegionError(
            f"BREP region snapshot SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
        )
    shape, manifest = decode_artifact(data, expected_root_kind=expected_root_kind)
    return shape, manifest, actual_hash


__all__ = [
    "BRepRegionError",
    "MAX_ARTIFACT_BYTES",
    "PROFILE",
    "decode_artifact",
    "encode_artifact",
    "read_artifact",
    "sha256_bytes",
]

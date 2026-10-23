"""Create and validate content-addressed BREP region snapshots."""

from __future__ import annotations

import io
import os
from pathlib import Path
import tempfile
from typing import Any, Sequence

import simplecadapi._cpp.occt as _occt
from simplecadapi._cpp.occt.BRep import BRep_Builder
from simplecadapi._cpp.occt.IFSelect import IFSelect_RetDone
from simplecadapi._cpp.occt.STEPControl import STEPControl_Reader
from simplecadapi._cpp.occt.TopoDS import TopoDS_Shell

from ..._internal.brep_region import (
    PROFILE,
    decode_artifact,
    encode_artifact,
    sha256_bytes,
)
from ...kernel.ocp_brep_snapshot import (
    RootKind,
    encode_shape,
    face_fingerprints,
    require_single_valid_solid,
    shape_descriptor,
)
from .model import BRepEntityError, index_shape_rbrepmodel


def _load_step_solid(path: Path, source_bytes: bytes):
    reader = STEPControl_Reader()
    status = reader.ReadStream(path.name, io.BytesIO(source_bytes))
    if status != IFSelect_RetDone:
        raise BRepEntityError(f"Could not read STEP file {path}: {status}")
    transferred = int(reader.TransferRoots())
    if transferred < 1 or reader.NbShapes() < 1:
        raise BRepEntityError(f"STEP file transferred no shapes: {path}")
    return require_single_valid_solid(reader.OneShape()), transferred


def _face_shell(solid, face_ids: Sequence[str]):
    if not face_ids:
        raise ValueError("face_ids must contain at least one face id")
    model = index_shape_rbrepmodel(solid)
    canonical_ids = []
    seen = set()
    for entity_id in face_ids:
        kind, index, face = model.resolve_entity(str(entity_id))
        if kind != "face":
            raise ValueError(f"face_ids must contain only face ids, got {entity_id}")
        canonical = f"face:{index}"
        if canonical in seen:
            raise ValueError(f"face_ids contains duplicate id {canonical}")
        seen.add(canonical)
        canonical_ids.append((canonical, face))
    canonical_ids.sort(key=lambda item: int(item[0].split(":", 1)[1]))
    selected_ids = {entity_id for entity_id, _ in canonical_ids}
    connected = {canonical_ids[0][0]}
    pending = [canonical_ids[0][0]]
    while pending:
        current = pending.pop()
        neighbors = set(model.adjacency_details(current)["neighboring_faces"])
        additions = (neighbors & selected_ids) - connected
        connected.update(additions)
        pending.extend(sorted(additions))
    if connected != selected_ids:
        raise ValueError("face_ids must form exactly one connected face region")
    shell = TopoDS_Shell()
    builder = BRep_Builder()
    builder.MakeShell(shell)
    for _, face in canonical_ids:
        builder.Add(shell, face)
    shape_descriptor(shell, "shell")
    return shell, [entity_id for entity_id, _ in canonical_ids]


def _manifest(
    *,
    source: Path,
    source_bytes: bytes,
    transferred_root_count: int,
    payload: bytes,
    descriptor: dict[str, Any],
    face_ids: Sequence[str] | None,
    face_records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "format": "simplecad-brep-region",
        "schema_version": "1.0",
        "profile": PROFILE,
        "coordinate_system": {"length_unit": "mm"},
        "generator": {"ocp_version": str(_occt.__version__)},
        "source": {
            "format": "step",
            "name": source.name,
            "byte_length": len(source_bytes),
            "content_hash": sha256_bytes(source_bytes),
            "transferred_root_count": transferred_root_count,
        },
        "region": (
            {
                "kind": "complete_solid",
                "source_face_ids": [
                    f"face:{index}" for index in range(len(face_records))
                ],
            }
            if face_ids is None
            else {"kind": "face_shell", "source_face_ids": list(face_ids)}
        ),
        "shape": {
            **descriptor,
            "encoding": "occt-bintools",
            "format_version": 4,
            "triangulation": False,
            "normals": False,
            "byte_length": len(payload),
            "content_hash": sha256_bytes(payload),
            "face_fingerprints": list(face_records),
        },
        "provenance": {
            "evidence_origin": "copied",
            "construction": "exact_transcription",
            "topology_origin": "retained",
            "runtime_dependency": "embedded_target_derived",
            "target_step_required_at_replay": False,
        },
    }


def copy_step_region_rpath(
    path: str | Path,
    output_path: str | Path,
    *,
    face_ids: Sequence[str] | None = None,
) -> Path:
    """Copy one STEP solid or one connected face Shell into a BREP snapshot.

    ``face_ids`` copies the selected target faces with their existing carriers,
    trims, pcurves, shared edges/vertices, orientations, and tolerances. The
    selection must form one connected valid Shell. Omitting ``face_ids`` copies
    the complete single Solid. The operation runs outside GraphSession and writes
    atomically to ``.scadbrep``.
    """

    source = Path(path).expanduser().resolve()
    destination = Path(output_path).expanduser().absolute()
    if source == destination:
        raise ValueError("output_path must differ from the source STEP path")
    if source.suffix.lower() not in {".step", ".stp"}:
        raise ValueError("path must end in .step or .stp")
    if destination.suffix.lower() != ".scadbrep":
        raise ValueError("output_path must end in .scadbrep")
    if ":" in source.name or ":" in destination.name:
        raise ValueError("snapshot filenames must not contain ':'")
    if not source.is_file():
        raise FileNotFoundError(source)
    if not destination.parent.is_dir():
        raise ValueError(f"output_path parent does not exist: {destination.parent}")
    if destination.is_symlink():
        raise ValueError("output_path must not be a symbolic link")

    source_bytes = source.read_bytes()
    solid, transferred = _load_step_solid(source, source_bytes)
    if face_ids is None:
        shape = solid
        root_kind: RootKind = "solid"
        canonical_face_ids = None
    else:
        shape, canonical_face_ids = _face_shell(solid, face_ids)
        root_kind = "shell"
    payload = encode_shape(shape, root_kind)
    face_records = face_fingerprints(shape)
    source_face_ids = (
        [f"face:{index}" for index in range(len(face_records))]
        if canonical_face_ids is None
        else list(canonical_face_ids)
    )
    face_records = [
        {**record, "source_face_id": source_face_id}
        for record, source_face_id in zip(face_records, source_face_ids)
    ]
    manifest = _manifest(
        source=source,
        source_bytes=source_bytes,
        transferred_root_count=transferred,
        payload=payload,
        descriptor=shape_descriptor(shape, root_kind),
        face_ids=canonical_face_ids,
        face_records=face_records,
    )
    artifact = encode_artifact(manifest, payload)
    decode_artifact(artifact)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.stem}-",
            suffix=destination.suffix,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(artifact)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return destination


__all__ = [
    "copy_step_region_rpath",
]

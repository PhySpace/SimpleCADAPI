"""Closed-schema, canonical JSON, identity, and blob validation."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

from .canonical import (
    ArtifactLimits,
    ArtifactValidationError,
    DEFAULT_ARTIFACT_LIMITS,
    canonical_bytes,
    content_hash,
    parse_canonical_json,
    parse_strict_json,
    sha256_bytes,
)

_ARTIFACT_KINDS = {"part_definition", "assembly_definition"}
_SCHEMA_FILES = {
    "part_definition": "part-definition-2.schema.json",
    "assembly_definition": "assembly-definition-2.schema.json",
}


@lru_cache(maxsize=2)
def _schema(kind: str) -> Mapping[str, Any]:
    if kind not in _ARTIFACT_KINDS:
        raise ArtifactValidationError("artifact_kind_invalid", "/artifact_kind", "unsupported artifact kind")
    resource = files("simplecadapi").joinpath("contracts", _SCHEMA_FILES[kind])
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def _pointer(parts: Iterable[Any]) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def _schema_validate(manifest: Mapping[str, Any], kind: str) -> None:
    errors = sorted(
        Draft202012Validator(_schema(kind)).iter_errors(manifest),
        key=lambda item: (list(item.absolute_path), item.message),
    )
    if errors:
        error = errors[0]
        raise ArtifactValidationError("schema_invalid", _pointer(error.absolute_path), error.message)


def _validate_order(manifest: Mapping[str, Any], kind: str) -> None:
    if kind == "part_definition":
        paths = [item["path"] for item in manifest["file_inputs"]]
        if paths != sorted(paths, key=lambda item: item.encode("utf-8")) or len(paths) != len(set(paths)):
            raise ArtifactValidationError("array_order_invalid", "/file_inputs", "must be unique UTF-8 sorted paths")
        return
    refs = manifest["definition_refs"]
    ref_ids = [item["definition_id"] for item in refs]
    if ref_ids != sorted(ref_ids, key=lambda item: item.encode("utf-8")) or len(ref_ids) != len(set(ref_ids)):
        raise ArtifactValidationError("array_order_invalid", "/definition_refs", "must be unique and sorted")
    grounded = manifest["grounded_instance_ids"]
    if grounded != sorted(grounded, key=lambda item: item.encode("utf-8")) or len(grounded) != len(set(grounded)):
        raise ArtifactValidationError("array_order_invalid", "/grounded_instance_ids", "must be unique and sorted")


def _validate_relation_values(manifest: Mapping[str, Any]) -> None:
    for index, relation in enumerate(manifest["relations"]):
        for limit_name in ("distance_limit", "angle_limit"):
            limit = relation[limit_name]
            if limit is not None and limit["lower_value"] > limit["upper_value"]:
                raise ArtifactValidationError(
                    "relation_invalid",
                    f"/relations/{index}/{limit_name}",
                    "lower_value must not exceed upper_value",
                )


def validate_manifest(manifest: Mapping[str, Any], kind: str | None = None) -> None:
    """Validate one already-parsed manifest in deterministic phase order."""

    if not isinstance(manifest, Mapping):
        raise ArtifactValidationError("type_invalid", "/", "artifact manifest must be an object")
    actual_kind = manifest.get("artifact_kind")
    selected = kind or actual_kind
    if selected not in _ARTIFACT_KINDS:
        raise ArtifactValidationError("artifact_kind_invalid", "/artifact_kind", "unsupported artifact kind")
    if actual_kind != selected:
        raise ArtifactValidationError("artifact_kind_invalid", "/artifact_kind", f"expected {selected}")
    _schema_validate(manifest, selected)
    _validate_order(manifest, selected)
    if selected == "assembly_definition":
        _validate_relation_values(manifest)
        expected_hash = content_hash({**manifest, "solved_snapshot": None})
    else:
        expected_hash = content_hash(manifest)
    if manifest["content_hash"] != expected_hash:
        raise ArtifactValidationError("hash_invalid", "/content_hash", "content hash does not match definition")


def parse_artifact_json(
    data: bytes | bytearray | memoryview | str,
    *,
    kind: str | None = None,
    canonical: bool = True,
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> Mapping[str, Any]:
    """Parse and validate bounded artifact JSON, optionally requiring exact JCS bytes."""

    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if len(raw) > limits.max_json_bytes:
        raise ArtifactValidationError("resource_limit", "/", "artifact JSON exceeds byte limit")
    try:
        parsed = parse_canonical_json(raw) if canonical else parse_strict_json(raw)
    except UnicodeDecodeError as exc:
        raise ArtifactValidationError("invalid_utf8", "/", str(exc)) from exc
    except ValueError as exc:
        reason = "noncanonical_json" if canonical else "json_invalid"
        raise ArtifactValidationError(reason, "/", str(exc)) from exc
    if not isinstance(parsed, Mapping):
        raise ArtifactValidationError("type_invalid", "/", "artifact manifest must be an object")
    validate_manifest(parsed, kind)
    return parsed


def _blob_refs(manifest: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    if manifest["artifact_kind"] == "part_definition":
        refs = [
            ("/definition/feature_graph_ref", manifest["definition"]["feature_graph_ref"]),
            ("/solid_cache/body_ref", manifest["solid_cache"]["body_ref"]),
            ("/topology_snapshot_ref", manifest["topology_snapshot_ref"]),
        ]
        material = manifest["material_ref"]
        if material is not None:
            refs.append(("/material_ref", material))
        for index, body in enumerate(manifest["solid_cache"].get("bodies") or ()):  # a multi-body part
            refs.append((f"/solid_cache/bodies/{index}/body_ref", body["body_ref"]))
            refs.append((f"/solid_cache/bodies/{index}/topology_snapshot_ref", body["topology_snapshot_ref"]))
        return refs
    return [("/feature_graph_ref", manifest["feature_graph_ref"])]


def validate_artifact_blobs(
    manifest: Mapping[str, Any],
    blobs: Mapping[str, bytes | bytearray | memoryview],
    *,
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> None:
    """Validate every immutable blob and reject missing or unreferenced payloads."""

    validate_manifest(manifest)
    normalized = {str(path): bytes(payload) for path, payload in blobs.items()}
    total = 0
    referenced: set[str] = set()
    for pointer, ref in _blob_refs(manifest):
        path = str(ref["path"])
        referenced.add(path)
        payload = normalized.get(path)
        if payload is None:
            raise ArtifactValidationError("blob_missing", pointer + "/path", f"missing blob {path}")
        if len(payload) > limits.max_blob_bytes:
            raise ArtifactValidationError("resource_limit", pointer, "blob exceeds byte limit")
        total += len(payload)
        if total > limits.max_total_bytes:
            raise ArtifactValidationError("resource_limit", pointer, "aggregate blob bytes exceed limit")
        if ref["byte_length"] != len(payload):
            raise ArtifactValidationError("blob_size_mismatch", pointer + "/byte_length", "declared size differs")
        expected = ref.get("sha256")
        if expected != sha256_bytes(payload):
            raise ArtifactValidationError("blob_hash_mismatch", pointer + "/sha256", "declared hash differs")
        media_type = ref.get("media_type")
        if media_type == "application/json":
            try:
                parse_canonical_json(payload)
            except ValueError as exc:
                raise ArtifactValidationError("noncanonical_json", pointer + "/path", str(exc)) from exc
    extras = sorted(set(normalized) - referenced, key=lambda item: item.encode("utf-8"))
    if extras:
        raise ArtifactValidationError("blob_unreferenced", "/blobs", f"unreferenced blob: {extras[0]}")


__all__ = ["parse_artifact_json", "validate_artifact_blobs", "validate_manifest"]

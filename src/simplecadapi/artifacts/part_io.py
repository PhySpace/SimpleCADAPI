"""Self-contained PartDefinition archive encoding and loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .brep import read_brep_shape, read_brep_solid
from .canonical import ArtifactValidationError
from .part_definition import (
    PartDefinition,
    mark_part_definition_validated,
    part_definition_is_validated,
)
from .topology_snapshot import (
    restore_topology_snapshot,
    validate_connector_entity_bindings,
)
from .validation import parse_artifact_json, validate_artifact_blobs
from .feature_graph import load_feature_graph_artifact
from ..scene.archive import canonical_zip_bytes, preflight_zip_bytes

_PART_DEFINITION_MANIFEST = "part-definition.json"
_BLOB_PREFIX = "blobs/"


def encode_part_definition(definition: PartDefinition) -> bytes:
    """Encode one validated definition and every referenced blob canonically."""

    if not isinstance(definition, PartDefinition):
        raise TypeError("definition must be a PartDefinition")
    if not part_definition_is_validated(definition):
        validate_artifact_blobs(definition.to_dict(), definition.blobs)
    members: dict[str, bytes] = {
        _PART_DEFINITION_MANIFEST: definition.canonical_bytes,
    }
    for path, payload in definition.blobs.items():
        members[_BLOB_PREFIX + path] = bytes(payload)
    return canonical_zip_bytes(
        members,
        manifest_name=_PART_DEFINITION_MANIFEST,
    )


def load_part_definition(
    data: bytes | bytearray | memoryview | str | Path,
) -> PartDefinition:
    """Load and fully validate a self-contained PartDefinition archive."""

    raw = Path(data).read_bytes() if isinstance(data, (str, Path)) else bytes(data)
    archive = preflight_zip_bytes(
        raw,
        manifest_name=_PART_DEFINITION_MANIFEST,
    )
    manifest = parse_artifact_json(
        archive.members[_PART_DEFINITION_MANIFEST],
        kind="part_definition",
    )
    expected_paths = {
        str(manifest["definition"]["feature_graph_ref"]["path"]),
        str(manifest["solid_cache"]["body_ref"]["path"]),
        str(manifest["topology_snapshot_ref"]["path"]),
    }
    material_ref = manifest["material_ref"]
    if material_ref is not None:
        expected_paths.add(str(material_ref["path"]))
    for body in manifest["solid_cache"].get("bodies") or ():  # a multi-body part: each body's BRep and snapshot
        expected_paths.add(str(body["body_ref"]["path"]))
        expected_paths.add(str(body["topology_snapshot_ref"]["path"]))
    expected_members = {
        _PART_DEFINITION_MANIFEST,
        *(_BLOB_PREFIX + path for path in expected_paths),
    }
    if set(archive.members) != expected_members:
        raise ArtifactValidationError(
            "blob_unreferenced",
            "/blobs",
            "archive member set differs from definition references",
        )
    blobs = {path: archive.members[_BLOB_PREFIX + path] for path in expected_paths}
    definition = PartDefinition.from_dict(manifest, blobs=blobs)
    validate_artifact_blobs(definition.to_dict(), definition.blobs)
    feature_graph = load_feature_graph_artifact(
        definition.blobs[definition.feature_graph_ref.path]
    )
    if (
        feature_graph.owner_definition_kind != definition.definition_kind
        or feature_graph.owner_definition_id != definition.definition_id
        or feature_graph.owner_revision != definition.revision
    ):
        raise ArtifactValidationError(
            "graph_owner_invalid",
            "/definition/feature_graph_ref",
            "feature graph owner differs from PartDefinition identity",
        )
    body = read_part_bodies(definition)
    mark_part_definition_validated(
        definition,
        body=body,
        feature_graph=feature_graph,
    )
    return definition


def read_part_bodies(definition: PartDefinition) -> Any:
    """The Solid of a one-body definition, or the ``Body`` values of a multi-body one, with their semantic state.

    A multi-body definition's ``body_ref`` must be a Compound of exactly as many solids as it lists bodies.
    """

    if not definition.bodies:
        body = read_brep_solid(definition.blobs[definition.solid_cache_ref.path])
        restore_topology_snapshot(body, definition.blobs[definition.topology_snapshot_ref.path])
        validate_connector_entity_bindings(body, definition.connectors)
        return body
    from simplecadapi._cpp import Body

    compound = read_brep_shape(definition.blobs[definition.solid_cache_ref.path])
    count = len(compound.solids()) if hasattr(compound, "solids") else 1
    if count != len(definition.bodies):
        raise ArtifactValidationError(
            "solid_cardinality_invalid",
            "/solid_cache/body_ref",
            f"BRep holds {count} solids, the definition lists {len(definition.bodies)} bodies",
        )
    bodies = []
    for item in definition.bodies:
        solid = read_brep_solid(definition.blobs[item.body_ref.path])
        restore_topology_snapshot(solid, definition.blobs[item.topology_snapshot_ref.path])
        bodies.append(Body(item.body_id, solid, item.name))
    return tuple(bodies)


def export_part_definition(
    value: PartDefinition | Any,
    path: str | Path,
) -> Path:
    """Write a PartDefinition or PartBuildResult to a canonical archive."""

    definition = (
        value
        if isinstance(value, PartDefinition)
        else getattr(value, "definition", None)
    )
    if not isinstance(definition, PartDefinition):
        raise TypeError("value must be a PartDefinition or PartBuildResult")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encode_part_definition(definition))
    return destination


__all__ = [
    "encode_part_definition",
    "export_part_definition",
    "load_part_definition",
]

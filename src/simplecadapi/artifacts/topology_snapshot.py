"""Stable topology fingerprinting and semantic-state snapshot restoration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from simplecadapi._cpp import Solid, TagBinding, TagLineageWitness
from ..topology.tagging import normalize_tag
from ..topology import TopoKind, TopoRef, topo_ref_to_dict
from .geometry_interface import (
    geometry_interface_fingerprint,
    stable_topology_entity_hash,
)
from .canonical import (
    TOPOLOGY_SNAPSHOT_PROFILE,
    ArtifactValidationError,
    canonical_bytes,
    content_hash,
    parse_canonical_json,
    validate_json_value,
)

_SNAPSHOT_VERSION = "4.0"
_METADATA_EXCLUDED = {
    "graph",
    "topo_ref",
    "track",
    "source_sketch",
    "sketch_solve",
    "sketch_promotion",
}


def _semantic_metadata(metadata: Mapping[str, Any], path: str) -> dict[str, Any]:
    """Project runtime metadata into canonical JSON-safe values."""
    from simplecadapi._cpp import Expr, Var

    def project(value: Any) -> Any:
        if isinstance(value, (Var, Expr)):
            return float(value.evaluate())
        if isinstance(value, dict):
            return {str(key): project(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [project(child) for child in value]
        return deepcopy(value)

    projected = {
        str(key): project(value)
        for key, value in metadata.items()
        if isinstance(key, str)
        and key not in _METADATA_EXCLUDED
        and not key.startswith("_")
    }
    validate_json_value(projected, path)
    return projected


def _binding_content_id(payload: Mapping[str, Any]) -> str:
    draft = deepcopy(dict(payload))

    def strip_identity(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("binding_id", None)
            value.pop("source_binding_id", None)
            for child in value.values():
                strip_identity(child)
        elif isinstance(value, list):
            for child in value:
                strip_identity(child)

    strip_identity(draft)
    return "tag_binding_" + content_hash(draft, omit=()).removeprefix("sha256:")[:32]


def _canonical_binding_payloads(solid: Solid) -> dict[str, str]:
    identities: dict[str, str] = {}
    for entity in solid._topology_cache.entities():
        bindings = [
            *entity.tag_bindings,
            *(item.binding for item in entity.tag_lineage),
        ]
        for binding in bindings:
            payload = binding.to_dict()
            identities[binding.binding_id] = _binding_content_id(payload)
    return identities


def _rewrite_binding_identities(value: Any, identities: Mapping[str, str]) -> Any:
    result = deepcopy(value)

    def rewrite(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"binding_id", "source_binding_id"} and isinstance(
                    child, str
                ):
                    item[key] = identities.get(child, child)
                else:
                    rewrite(child)
        elif isinstance(item, list):
            for child in item:
                rewrite(child)

    rewrite(result)
    return result


def _entity_key(entity: Any) -> tuple[str, str]:
    return (
        str(entity.kind),
        stable_topology_entity_hash(entity.representative, str(entity.kind)),
    )


def _entity_key_map(entities: list[Any]) -> dict[int, tuple[str, str]]:
    return {id(entity): _entity_key(entity) for entity in entities}


def _feature_output(entity: Any) -> dict[str, Any] | None:
    ref = entity.runtime.get("topo.ref")
    if not isinstance(ref, TopoRef):
        return None
    return topo_ref_to_dict(ref)

def topology_entity_ref(solid: Solid, topo_id: str) -> dict[str, str]:
    """Return the immutable package reference for one topology entity."""

    if not isinstance(solid, Solid):
        raise TypeError("solid must be a Solid")
    entity = solid._topology_cache._entities_by_id.get(str(topo_id))
    if entity is None:
        raise ArtifactValidationError(
            "reference_missing",
            "/topo_id",
            f"topology entity {topo_id!r} does not exist",
        )
    kind, geometry_hash = _entity_key(entity)
    return {
        "kind": kind,
        "topo_id": entity.topo_id,
        "geometry_hash": geometry_hash,
    }


def resolve_geometry_entity_ref(
    solid: Solid,
    geometry_ref: Any,
) -> dict[str, str]:
    """Resolve one GeometryRef against a final part body without ambiguity."""

    from ..recording.serializer import (
        _candidate_shapes_for_geo_selection,
        _geo_selector_score,
    )

    kind = str(geometry_ref.kind)
    candidates = _candidate_shapes_for_geo_selection(solid, kind)
    ranked = sorted(
        (
            (_geo_selector_score(candidate, geometry_ref.geo_selector), candidate)
            for candidate in candidates
        ),
        key=lambda item: (item[0], item[1].topo_id.encode("utf-8")),
    )
    if not ranked or ranked[0][0] > 1.0e-4:
        raise ArtifactValidationError(
            "connector_binding_invalid",
            "/connectors/binding",
            f"geometry connector did not resolve to a {kind} on the final body",
        )
    if len(ranked) > 1 and ranked[1][0] <= 1.0e-4:
        raise ArtifactValidationError(
            "connector_binding_ambiguous",
            "/connectors/binding",
            f"geometry connector resolves to multiple {kind} entities",
        )
    return topology_entity_ref(solid, ranked[0][1].topo_id)


def _name_index_from_records(
    entities: list[Mapping[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = {}
    for entity in entities:
        reference = {
            "kind": str(entity["kind"]),
            "topo_id": str(entity["topo_id"]),
            "geometry_hash": str(entity["geometry_hash"]),
        }
        for tag in entity["tags"]:
            name = str(tag)
            if name.startswith("interface."):
                index.setdefault(name, []).append(reference)
    result: dict[str, list[dict[str, str]]] = {}
    for name in sorted(index, key=lambda value: value.encode("utf-8")):
        references = sorted(
            index[name],
            key=lambda item: (
                item["kind"].encode("utf-8"),
                item["geometry_hash"].encode("utf-8"),
                item["topo_id"].encode("utf-8"),
            ),
        )
        kinds = {item["kind"] for item in references}
        if len(kinds) != 1:
            raise ArtifactValidationError(
                "geometry_name_invalid",
                f"/name_index/{name}",
                "one public geometry name cannot span multiple entity kinds",
            )
        result[name] = references
    return result


def validate_connector_entity_bindings(
    solid: Solid,
    connectors: Any,
) -> None:
    """Validate every frozen geometry connector against the restored body."""

    for index, connector in enumerate(connectors):
        if connector.anchor_kind != "geometry":
            continue
        path = f"/connectors/{index}/binding"
        binding = connector.binding
        if not isinstance(binding, Mapping) or set(binding) != {
            "kind",
            "source_node_id",
            "geo_selector",
            "flip",
            "resolved_entities",
        }:
            raise ArtifactValidationError(
                "connector_binding_invalid",
                path,
                "geometry binding fields are not closed",
            )
        references = binding["resolved_entities"]
        if not isinstance(references, list) or len(references) != 1:
            raise ArtifactValidationError(
                "connector_binding_invalid",
                path + "/resolved_entities",
                "geometry connector must resolve to exactly one entity",
            )
        reference = references[0]
        if not isinstance(reference, Mapping) or set(reference) != {
            "kind",
            "topo_id",
            "geometry_hash",
        }:
            raise ArtifactValidationError(
                "connector_binding_invalid",
                path + "/resolved_entities/0",
                "invalid entity reference",
            )
        actual = topology_entity_ref(solid, str(reference["topo_id"]))
        if dict(reference) != actual or binding["kind"] != actual["kind"]:
            raise ArtifactValidationError(
                "connector_binding_invalid",
                path + "/resolved_entities/0",
                "entity reference differs from the restored body",
            )

def _current_match_key(
    entity: Any,
    entities_by_id: Mapping[str, Any],
    entity_keys: Mapping[int, tuple[str, str]],
) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    kind, geometry_hash = entity_keys[id(entity)]
    neighbors = []
    for entity_id in entity.incident_face_ids | entity.incident_edge_ids:
        neighbor = entities_by_id.get(entity_id)
        if neighbor is None:
            raise ArtifactValidationError(
                "topology_mismatch",
                "/entities",
                f"incident entity {entity_id!r} does not resolve",
            )
        neighbors.append(entity_keys[id(neighbor)])
    return kind, geometry_hash, tuple(sorted(neighbors))


def _snapshot_match_key(
    item: Mapping[str, Any],
    entities_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    neighbors = []
    for entity_id in set(item["incident_face_ids"]) | set(item["incident_edge_ids"]):
        neighbor = entities_by_id.get(str(entity_id))
        if neighbor is None:
            raise ArtifactValidationError(
                "topology_snapshot_invalid",
                "/entities",
                f"incident entity {entity_id!r} does not resolve",
            )
        neighbors.append((str(neighbor["kind"]), str(neighbor["geometry_hash"])))
    return (
        str(item["kind"]),
        str(item["geometry_hash"]),
        tuple(sorted(neighbors)),
    )


def geometry_fingerprint(solid: Solid) -> str:
    if not isinstance(solid, Solid):
        raise TypeError("solid must be a Solid")
    return geometry_interface_fingerprint(solid)


def _topology_descriptor_from_keys(
    *,
    geometry_hash: str,
    entities: list[Any],
    entity_keys: Mapping[int, tuple[str, str]],
) -> dict[str, Any]:
    records = [
        {
            "kind": entity_keys[id(entity)][0],
            "geometry_hash": entity_keys[id(entity)][1],
            "incident_face_count": len(entity.incident_face_ids),
            "incident_edge_count": len(entity.incident_edge_ids),
        }
        for entity in entities
    ]
    records.sort(
        key=lambda item: (
            item["kind"].encode("utf-8"),
            item["geometry_hash"].encode("utf-8"),
            item["incident_face_count"],
            item["incident_edge_count"],
        )
    )
    return {
        "profile": TOPOLOGY_SNAPSHOT_PROFILE,
        "geometry_hash": geometry_hash,
        "entity_count": len(records),
        "entities": records,
    }


def topology_descriptor(solid: Solid) -> dict[str, Any]:
    """Return a traversal-independent descriptor for all wrapped topology entities."""

    if not isinstance(solid, Solid):
        raise TypeError("solid must be a Solid")
    entities = solid._topology_cache.entities()
    return _topology_descriptor_from_keys(
        geometry_hash=geometry_fingerprint(solid),
        entities=entities,
        entity_keys=_entity_key_map(entities),
    )


def topology_fingerprint(solid: Solid) -> str:
    return content_hash(topology_descriptor(solid), omit=())


def capture_topology_snapshot(solid: Solid) -> dict[str, Any]:
    """Capture exact semantic state keyed by stable normalized geometry."""

    if not isinstance(solid, Solid):
        raise TypeError("solid must be a Solid")
    current_entities = solid._topology_cache.entities()
    entity_keys = _entity_key_map(current_entities)
    geometry_hash = geometry_fingerprint(solid)
    topology_hash = content_hash(
        _topology_descriptor_from_keys(
            geometry_hash=geometry_hash,
            entities=current_entities,
            entity_keys=entity_keys,
        ),
        omit=(),
    )
    binding_identities = _canonical_binding_payloads(solid)
    entities = []
    for entity in current_entities:
        kind, entity_geometry_hash = entity_keys[id(entity)]
        entities.append(
            {
                "kind": kind,
                "topo_id": entity.topo_id,
                "geometry_hash": entity_geometry_hash,
                "feature_output": _feature_output(entity),
                "tags": sorted(entity.tags, key=lambda item: item.encode("utf-8")),
                "tag_bindings": _rewrite_binding_identities(
                    [item.to_dict() for item in entity.tag_bindings], binding_identities
                ),
                "tag_lineage": _rewrite_binding_identities(
                    [item.to_dict() for item in entity.tag_lineage], binding_identities
                ),
                "metadata": _semantic_metadata(
                    entity.metadata, f"/entities/{entity.topo_id}/metadata"
                ),
                "incident_face_ids": sorted(
                    entity.incident_face_ids, key=lambda item: item.encode("utf-8")
                ),
                "incident_edge_ids": sorted(
                    entity.incident_edge_ids, key=lambda item: item.encode("utf-8")
                ),
            }
        )
    entities.sort(
        key=lambda item: (
            item["kind"].encode("utf-8"),
            item["geometry_hash"].encode("utf-8"),
            item["topo_id"].encode("utf-8"),
        )
    )
    return {
        "schema_version": _SNAPSHOT_VERSION,
        "profile": TOPOLOGY_SNAPSHOT_PROFILE,
        "geometry_hash": geometry_hash,
        "topology_hash": topology_hash,
        "entity_count": len(entities),
        "entities": entities,
        "name_index": _name_index_from_records(entities),
    }


def encode_topology_snapshot(solid: Solid) -> bytes:
    return canonical_bytes(capture_topology_snapshot(solid))


def _validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "profile",
        "geometry_hash",
        "topology_hash",
        "entity_count",
        "entities",
        "name_index",
    }
    if set(snapshot) != required:
        raise ArtifactValidationError(
            "topology_snapshot_invalid", "/", "snapshot fields are not closed"
        )
    if (
        snapshot["schema_version"] != _SNAPSHOT_VERSION
        or snapshot["profile"] != TOPOLOGY_SNAPSHOT_PROFILE
    ):
        raise ArtifactValidationError(
            "topology_snapshot_invalid", "/profile", "unsupported snapshot profile"
        )
    entities = snapshot["entities"]
    if not isinstance(entities, list) or snapshot["entity_count"] != len(entities):
        raise ArtifactValidationError(
            "topology_snapshot_invalid", "/entity_count", "entity count differs"
        )
    entity_required = {
        "kind",
        "topo_id",
        "geometry_hash",
        "feature_output",
        "tags",
        "tag_bindings",
        "tag_lineage",
        "metadata",
        "incident_face_ids",
        "incident_edge_ids",
    }
    seen_ids: set[str] = set()
    for index, entity in enumerate(entities):
        if not isinstance(entity, Mapping) or set(entity) != entity_required:
            raise ArtifactValidationError(
                "topology_snapshot_invalid",
                f"/entities/{index}",
                "entity fields differ",
            )
        topo_id = entity["topo_id"]
        if not isinstance(topo_id, str) or not topo_id or topo_id in seen_ids:
            raise ArtifactValidationError(
                "topology_snapshot_invalid",
                f"/entities/{index}/topo_id",
                "invalid or duplicate ID",
            )
        seen_ids.add(topo_id)
        feature_output = entity["feature_output"]
        if feature_output is not None:
            if not isinstance(feature_output, Mapping) or set(feature_output) != {
                "graph_id",
                "node_id",
                "output_slot",
                "kind",
                "topo_id",
            }:
                raise ArtifactValidationError(
                    "topology_snapshot_invalid",
                    f"/entities/{index}/feature_output",
                    "invalid feature output reference",
                )
            if feature_output["kind"] != str(entity["kind"]).upper():
                raise ArtifactValidationError(
                    "topology_snapshot_invalid",
                    f"/entities/{index}/feature_output/kind",
                    "feature output kind differs from topology entity kind",
                )
            if (
                not isinstance(feature_output["graph_id"], str)
                or not feature_output["graph_id"]
                or not isinstance(feature_output["node_id"], str)
                or not feature_output["node_id"]
                or isinstance(feature_output["output_slot"], bool)
                or not isinstance(feature_output["output_slot"], int)
                or feature_output["output_slot"] < 0
                or not isinstance(feature_output["topo_id"], str)
                or not feature_output["topo_id"]
            ):
                raise ArtifactValidationError(
                    "topology_snapshot_invalid",
                    f"/entities/{index}/feature_output",
                    "feature output reference values are invalid",
                )
        validate_json_value(entity["metadata"], f"/entities/{index}/metadata")
    name_index = snapshot["name_index"]
    if not isinstance(name_index, Mapping):
        raise ArtifactValidationError(
            "topology_snapshot_invalid", "/name_index", "must be an object"
        )
    entities_by_id = {str(item["topo_id"]): item for item in entities}
    for raw_name, references in name_index.items():
        try:
            name = normalize_tag(str(raw_name), strict=True)
        except (TypeError, ValueError) as exc:
            raise ArtifactValidationError(
                "geometry_name_invalid", f"/name_index/{raw_name}", str(exc)
            ) from exc
        if name != raw_name or not name.startswith("interface."):
            raise ArtifactValidationError(
                "geometry_name_invalid",
                f"/name_index/{raw_name}",
                "public geometry names must use the interface.* namespace",
            )
        if not isinstance(references, list) or not references:
            raise ArtifactValidationError(
                "geometry_name_invalid",
                f"/name_index/{name}",
                "geometry name must reference at least one entity",
            )
        seen: set[tuple[str, str, str]] = set()
        kinds: set[str] = set()
        for ref_index, reference in enumerate(references):
            ref_path = f"/name_index/{name}/{ref_index}"
            if not isinstance(reference, Mapping) or set(reference) != {
                "kind",
                "topo_id",
                "geometry_hash",
            }:
                raise ArtifactValidationError(
                    "geometry_name_invalid", ref_path, "invalid entity reference"
                )
            key = (
                str(reference["kind"]),
                str(reference["topo_id"]),
                str(reference["geometry_hash"]),
            )
            if key in seen:
                raise ArtifactValidationError(
                    "geometry_name_invalid", ref_path, "duplicate entity reference"
                )
            seen.add(key)
            kinds.add(key[0])
            entity = entities_by_id.get(key[1])
            if entity is None or key[0] != entity["kind"] or key[2] != entity["geometry_hash"]:
                raise ArtifactValidationError(
                    "geometry_name_invalid",
                    ref_path,
                    "entity reference does not match the topology snapshot",
                )
        if len(kinds) != 1:
            raise ArtifactValidationError(
                "geometry_name_invalid",
                f"/name_index/{name}",
                "one public geometry name cannot span multiple entity kinds",
            )
    expected_names = _name_index_from_records(entities)
    if dict(name_index) != expected_names:
        raise ArtifactValidationError(
            "geometry_name_invalid",
            "/name_index",
            "name index differs from interface.* entity tags",
        )


def restore_topology_snapshot(
    solid: Solid,
    snapshot: Mapping[str, Any] | bytes | bytearray | memoryview,
) -> Solid:
    """Restore semantic state only when every topology entity maps uniquely."""

    if not isinstance(solid, Solid):
        raise TypeError("solid must be a Solid")
    if not isinstance(snapshot, Mapping):
        try:
            parsed = parse_canonical_json(bytes(snapshot))
        except ValueError as exc:
            raise ArtifactValidationError(
                "topology_snapshot_invalid", "/", str(exc)
            ) from exc
        if not isinstance(parsed, Mapping):
            raise ArtifactValidationError(
                "topology_snapshot_invalid", "/", "snapshot must be an object"
            )
        snapshot = parsed
    _validate_snapshot(snapshot)
    geometry_hash = geometry_fingerprint(solid)
    if snapshot["geometry_hash"] != geometry_hash:
        raise ArtifactValidationError(
            "geometry_mismatch", "/geometry_hash", "BRep geometry differs"
        )

    current_entities = solid._topology_cache.entities()
    entity_keys = _entity_key_map(current_entities)
    topology_hash = content_hash(
        _topology_descriptor_from_keys(
            geometry_hash=geometry_hash,
            entities=current_entities,
            entity_keys=entity_keys,
        ),
        omit=(),
    )
    if snapshot["topology_hash"] != topology_hash:
        raise ArtifactValidationError(
            "topology_mismatch", "/topology_hash", "topology descriptor differs"
        )

    current_by_id = {entity.topo_id: entity for entity in current_entities}
    snapshot_by_id = {str(item["topo_id"]): item for item in snapshot["entities"]}
    current_by_key: dict[tuple[str, str, tuple[tuple[str, str], ...]], list[Any]] = {}
    for entity in current_entities:
        key = _current_match_key(entity, current_by_id, entity_keys)
        current_by_key.setdefault(key, []).append(entity)
    snapshot_by_key: dict[
        tuple[str, str, tuple[tuple[str, str], ...]],
        list[Mapping[str, Any]],
    ] = {}
    for item in snapshot["entities"]:
        key = _snapshot_match_key(item, snapshot_by_id)
        snapshot_by_key.setdefault(key, []).append(item)
    if set(current_by_key) != set(snapshot_by_key):
        raise ArtifactValidationError(
            "topology_mismatch", "/entities", "entity identity sets differ"
        )

    matches: list[tuple[Any, Mapping[str, Any]]] = []
    for key in sorted(current_by_key, key=canonical_bytes):
        current = current_by_key[key]
        stored = snapshot_by_key[key]
        if len(current) != 1 or len(stored) != 1:
            raise ArtifactValidationError(
                "topology_ambiguous",
                "/entities",
                f"identity {key[0]} {key[1]} is not unique",
            )
        matches.append((current[0], stored[0]))

    new_ids = [str(item["topo_id"]) for _, item in matches]
    if len(new_ids) != len(set(new_ids)):
        raise ArtifactValidationError(
            "topology_snapshot_invalid", "/entities", "restored IDs are not unique"
        )
    valid_ids = set(new_ids)
    for _, item in matches:
        incident = set(item["incident_face_ids"]) | set(item["incident_edge_ids"])
        if not incident.issubset(valid_ids):
            raise ArtifactValidationError(
                "topology_snapshot_invalid", "/entities", "incident ID does not resolve"
            )

    for entity, item in matches:
        entity.topo_id = str(item["topo_id"])
    solid._topology_cache._entities_by_id = {
        entity.topo_id: entity for entity, _ in matches
    }
    for entity, item in matches:
        try:
            bindings = [TagBinding.from_dict(value) for value in item["tag_bindings"]]
            lineage = [
                TagLineageWitness.from_dict(value) for value in item["tag_lineage"]
            ]
        except Exception as exc:
            raise ArtifactValidationError(
                "topology_snapshot_invalid", "/entities", str(exc)
            ) from exc
        entity.tags.clear()
        entity.tags.update(str(value) for value in item["tags"])
        entity.tag_bindings[:] = bindings
        entity.tag_lineage[:] = lineage
        entity.metadata.clear()
        entity.metadata.update(deepcopy(dict(item["metadata"])))
        feature_output = item["feature_output"]
        if feature_output is None:
            entity.runtime.pop("topo.ref", None)
            entity.runtime.pop("topo.kind", None)
            entity.runtime.pop("topo.id", None)
        else:
            ref = TopoRef(
                graph_id=str(feature_output["graph_id"]),
                node_id=str(feature_output["node_id"]),
                output_slot=int(feature_output["output_slot"]),
                kind=TopoKind[str(feature_output["kind"])],
                topo_id=str(feature_output["topo_id"]),
            )
            entity.runtime["topo.ref"] = ref
            entity.runtime["topo.kind"] = ref.kind.name
            entity.runtime["topo.id"] = ref.topo_id
        entity.incident_face_ids.clear()
        entity.incident_face_ids.update(
            str(value) for value in item["incident_face_ids"]
        )
        entity.incident_edge_ids.clear()
        entity.incident_edge_ids.update(
            str(value) for value in item["incident_edge_ids"]
        )
    solid._refresh_tag_cache(recursive=True)
    return solid


__all__ = [
    "capture_topology_snapshot",
    "encode_topology_snapshot",
    "geometry_fingerprint",
    "resolve_geometry_entity_ref",
    "restore_topology_snapshot",
    "topology_descriptor",
    "topology_entity_ref",
    "topology_fingerprint",
    "validate_connector_entity_bindings",
]

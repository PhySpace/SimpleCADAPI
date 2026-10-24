"""Definition-driven, self-contained Scene 2.0 product snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from ..artifacts.assembly_definition import AssemblyDefinition
from ..artifacts.part_definition import PartDefinition, mark_part_definition_validated
from ..artifacts.assembly_io import (
    decode_assembly_definition,
    encode_assembly_definition,
    materialize_definition,
)
from ..artifacts.canonical import parse_canonical_json as parse_artifact_json
from ..artifacts.canonical import sha256_bytes
from ..artifacts.feature_graph import (
    FeatureGraphArtifact,
    load_feature_graph_artifact,
)
from ..artifacts.part_io import encode_part_definition, load_part_definition
from simplecadapi._cpp import Edge, Face, Solid, Vertex
from ..errors import SimpleCADMessageError
from ..product.placement import Placement, identity_placement, placement_from_canonical
from .archive import canonical_zip_bytes, preflight_zip_bytes
from .canonical import (
    canonical_json_bytes,
    compute_scene_revision,
    parse_canonical_json,
    with_scene_revision,
)
from .compiler import (
    DEFAULT_ANGULAR_TOLERANCE,
    DEFAULT_LINEAR_TOLERANCE,
    _bounds,
    _curve_geometry,
    _edge_endpoints,
    _frame,
    _normalize,
    _center_of_mass,
    _face_orientation,
    _shape_bounds,
    _surface_geometry,
    _vec,
)
from .glb_writer import write_line_glb, write_triangle_glb
from .render_mesh import build_edge_mesh, build_render_mesh, solid_asset_bounds

Definition = PartDefinition | AssemblyDefinition
_SCENE_MANIFEST = "scene.json"


class ProductSceneError(SimpleCADMessageError):
    """Raised when a Scene 2.0 product snapshot is not closed and canonical."""

    operation = "product_scene"


@dataclass(frozen=True, slots=True)
class ProductScenePackage:
    manifest: Mapping[str, Any]
    blobs: Mapping[str, bytes]
    _validated_manifest: bytes | None = field(
        default=None,
        init=False,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", MappingProxyType(dict(self.manifest)))
        object.__setattr__(
            self,
            "blobs",
            MappingProxyType(
                {str(path): bytes(payload) for path, payload in self.blobs.items()}
            ),
        )

    @property
    def scene(self) -> Mapping[str, Any]:
        return self.manifest


@lru_cache(maxsize=1)
def _schema() -> Mapping[str, Any]:
    resource = files("simplecadapi.scene").joinpath(
        "contracts", "schemas", "scene-2.0.schema.json"
    )
    value = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def _schema_validate(manifest: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(dict(manifest)),
        key=lambda item: (list(item.absolute_path), item.message),
    )
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(str(item) for item in error.absolute_path)
        raise ProductSceneError(f"scene schema invalid at {pointer}: {error.message}")


def _definition_bytes(definition: Definition) -> bytes:
    if isinstance(definition, PartDefinition):
        return encode_part_definition(definition)
    return encode_assembly_definition(definition)


def _definition_media_type(definition: Definition) -> str:
    if isinstance(definition, PartDefinition):
        return "application/vnd.simplecad.part-definition+zip"
    return "application/vnd.simplecad.assembly-definition+zip"


def _definition_closure(root: Definition) -> dict[str, Definition]:
    definitions: dict[str, Definition] = {}
    active: set[str] = set()

    def visit(definition: Definition) -> None:
        existing = definitions.get(definition.definition_id)
        if existing is not None:
            if (
                existing.definition_kind != definition.definition_kind
                or existing.content_hash != definition.content_hash
            ):
                raise ProductSceneError(
                    f"definition_id {definition.definition_id!r} has multiple identities"
                )
            return
        if definition.definition_id in active:
            raise ProductSceneError(
                f"definition cycle at {definition.definition_id!r}"
            )
        active.add(definition.definition_id)
        try:
            definitions[definition.definition_id] = definition
            if isinstance(definition, AssemblyDefinition):
                for ref in definition.definition_refs:
                    child = definition.resolved_definitions.get(ref.definition_id)
                    if not isinstance(child, (PartDefinition, AssemblyDefinition)):
                        raise ProductSceneError(
                            f"assembly {definition.definition_id!r} has unresolved "
                            f"definition {ref.definition_id!r}"
                        )
                    visit(child)
        finally:
            active.remove(definition.definition_id)

    visit(root)
    return definitions


def _feature_graph(definition: Definition) -> FeatureGraphArtifact:
    payload = definition.blobs[definition.feature_graph_ref.path]
    feature_graph = load_feature_graph_artifact(payload)
    if (
        feature_graph.owner_definition_id != definition.definition_id
        or feature_graph.owner_definition_kind != definition.definition_kind
        or feature_graph.owner_revision != definition.revision
    ):
        raise ProductSceneError(
            f"feature graph owner differs for {definition.definition_id!r}"
        )
    return feature_graph


def _asset_record(payload: bytes, *, uri: str, media_type: str) -> dict[str, Any]:
    digest = sha256_bytes(payload)
    return {
        "asset_id": digest,
        "uri": uri,
        "media_type": media_type,
        "sha256": digest,
        "byte_length": len(payload),
    }


def _source_feature_id(definition_id: str, node_id: str) -> str:
    return f"feature/{definition_id}/{node_id}"


def _node_source_spans(
    definition_id: str,
    node: Mapping[str, Any],
    source_ids: Mapping[str, str],
    source_uris: Mapping[str, str],
) -> list[dict[str, Any]]:
    source = node.get("source")
    if not isinstance(source, Mapping):
        return []
    source_file_id = source.get("source_file_id")
    if not isinstance(source_file_id, str) or source_file_id not in source_ids:
        return []
    start_line = source.get("line")
    end_line = source.get("end_line", start_line)
    if (
        isinstance(start_line, bool)
        or not isinstance(start_line, int)
        or start_line < 1
        or isinstance(end_line, bool)
        or not isinstance(end_line, int)
        or end_line < start_line
    ):
        return []
    targets = source.get("assignment_targets")
    symbol = (
        str(targets[0])
        if isinstance(targets, list) and targets and isinstance(targets[0], str)
        else None
    )
    return [
        {
            "source_asset_id": source_ids[source_file_id],
            "uri": source_uris[source_file_id],
            "start_line": start_line,
            "end_line": end_line,
            "symbol": symbol,
        }
    ]


def _feature_records(
    definition: Definition,
    feature_graph: FeatureGraphArtifact,
    source_ids: Mapping[str, str],
    source_uris: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    features: list[dict[str, Any]] = []
    source_index: list[dict[str, Any]] = []
    for node in feature_graph.graph.get("nodes", []):
        node_id = str(node["node_id"])
        feature_id = _source_feature_id(definition.definition_id, node_id)
        spans = _node_source_spans(
            definition.definition_id,
            node,
            source_ids,
            source_uris,
        )
        display = node.get("display")
        label = display.get("label") if isinstance(display, Mapping) else None
        features.append(
            {
                "feature_id": feature_id,
                "definition_id": definition.definition_id,
                "graph_id": feature_graph.owner_definition_id,
                "node_id": node_id,
                "op": str(node["op"]),
                "label": str(label) if label is not None else None,
                "parameters": dict(node.get("params", {})),
                "input_feature_ids": [
                    _source_feature_id(definition.definition_id, str(input_id))
                    for input_id in node.get("inputs", [])
                ],
                "output_count": int(node["output_count"]),
                "source_spans": spans,
            }
        )
        for span_index, span in enumerate(spans):
            source_index.append(
                {
                    "source_index_id": (
                        f"source/{definition.definition_id}/{node_id}/{span_index}"
                    ),
                    "source_asset_id": span["source_asset_id"],
                    "uri": span["uri"],
                    "definition_id": definition.definition_id,
                    "feature_id": feature_id,
                    "start_line": span["start_line"],
                    "end_line": span["end_line"],
                    "symbol": span["symbol"],
                }
            )
    return features, source_index


def _entity_source(
    definition_id: str,
    feature_output: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(feature_output, Mapping):
        raise ProductSceneError(
            f"definition {definition_id!r} has topology without feature_output"
        )
    return {
        "kind": "feature_output",
        "definition_id": definition_id,
        "graph_id": str(feature_output["graph_id"]),
        "node_id": str(feature_output["node_id"]),
        "output_slot": int(feature_output["output_slot"]),
        "topology_kind": str(feature_output["kind"]),
        "topo_id": str(feature_output["topo_id"]),
    }


def _entity_id(definition_id: str, kind: str, topo_id: str) -> str:
    return f"entity/{definition_id}/{kind}/{topo_id}"


def _part_geometry(
    definition: PartDefinition,
    *,
    linear_tolerance: float,
    angular_tolerance: float,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, bytes],
    str,
    str,
]:
    runtime = materialize_definition(definition)
    body = runtime.body
    if not isinstance(body, Solid):
        raise ProductSceneError(f"part {definition.definition_id!r} has no solid body")
    snapshot = parse_artifact_json(
        definition.blobs[definition.topology_snapshot_ref.path]
    )
    mark_part_definition_validated(
        definition,
        body=body,
        feature_graph=_feature_graph(definition),
    )
    source_by_key = {
        (str(item["kind"]), str(item["topo_id"])): _entity_source(
            definition.definition_id, item["feature_output"]
        )
        for item in snapshot["entities"]
    }

    faces = body._iter_faces()
    edges = body._iter_edges()
    vertices_by_id: dict[str, Vertex] = {}
    for edge in edges:
        for vertex in edge._iter_vertices():
            vertices_by_id.setdefault(vertex.topo_id, vertex)
    vertices = list(vertices_by_id.values())
    face_ids = {
        face.topo_id: _entity_id(definition.definition_id, "face", face.topo_id)
        for face in faces
    }
    edge_ids = {
        edge.topo_id: _entity_id(definition.definition_id, "edge", edge.topo_id)
        for edge in edges
    }
    vertex_ids = {
        vertex.topo_id: _entity_id(
            definition.definition_id, "vertex", vertex.topo_id
        )
        for vertex in vertices
    }
    render_mesh = build_render_mesh(
        body,
        face_entity_ids=[face_ids[item.topo_id] for item in faces],
        linear_tolerance=linear_tolerance,
        angular_tolerance=angular_tolerance,
    )
    edge_mesh = build_edge_mesh(
        body,
        edge_entity_ids=[edge_ids[item.topo_id] for item in edges],
        linear_tolerance=linear_tolerance,
        angular_tolerance=angular_tolerance,
    )
    triangle_glb = write_triangle_glb(render_mesh)
    line_glb = write_line_glb(edge_mesh)
    geometry_hash = sha256_bytes(triangle_glb)
    edge_hash = sha256_bytes(line_glb)
    geometry_uri = f"geometry/sha256-{geometry_hash.removeprefix('sha256:')}.glb"
    edge_uri = f"geometry/sha256-{edge_hash.removeprefix('sha256:')}.lines.glb"
    geometry_records = [
        _asset_record(triangle_glb, uri=geometry_uri, media_type="model/gltf-binary"),
        _asset_record(line_glb, uri=edge_uri, media_type="model/gltf-binary"),
    ]

    solid_id = _entity_id(definition.definition_id, "solid", body.topo_id)
    entities: list[dict[str, Any]] = [
        {
            "entity_id": solid_id,
            "kind": "solid",
            "topo_id": body.topo_id,
            "parent_entity_ids": [],
            "child_entity_ids": sorted(face_ids.values()),
            "source": source_by_key[("solid", body.topo_id)],
            "geometry": {"type": "brep_solid"},
            "properties": {
                "bounds": _bounds(solid_asset_bounds(body)),
                "volume": body.get_volume(),
                "surface_area": sum(face.get_area() for face in faces),
                "centroid": list(_vec(_center_of_mass(body))),
            },
            "tags": sorted(body._list_tags()),
        }
    ]
    for face in faces:
        center = _vec(face.get_center())
        entities.append(
            {
                "entity_id": face_ids[face.topo_id],
                "kind": "face",
                "topo_id": face.topo_id,
                "parent_entity_ids": [solid_id],
                "child_entity_ids": sorted(
                    edge_ids[item.topo_id] for item in face._iter_edges()
                ),
                "source": source_by_key[("face", face.topo_id)],
                "geometry": _surface_geometry(face),
                "properties": {
                    "bounds": _bounds(_shape_bounds(face)),
                    "area": face.get_area(),
                    "centroid": list(center),
                    "orientation": _face_orientation(face),
                    "connector_frame": _frame(center, _vec(face.get_normal_at())),
                },
                "tags": sorted(face._list_tags()),
            }
        )
    for edge in edges:
        start, end = _edge_endpoints(edge)
        frame = None
        if start is not None and end is not None and start != end:
            direction = _normalize(
                tuple(end[index] - start[index] for index in range(3))
            )
            frame = _frame(_vec(edge.get_center()), direction)
        entities.append(
            {
                "entity_id": edge_ids[edge.topo_id],
                "kind": "edge",
                "topo_id": edge.topo_id,
                "parent_entity_ids": sorted(
                    face_ids[item.topo_id]
                    for item in edge.get_incident_faces()
                    if item.topo_id in face_ids
                ),
                "child_entity_ids": sorted(
                    vertex_ids[item.topo_id] for item in edge._iter_vertices()
                ),
                "source": source_by_key[("edge", edge.topo_id)],
                "geometry": _curve_geometry(edge),
                "properties": {
                    "bounds": _bounds(_shape_bounds(edge)),
                    "length": edge.get_length(),
                    "centroid": list(_vec(edge.get_center())),
                    "connector_frame": frame,
                },
                "tags": sorted(edge._list_tags()),
            }
        )
    for vertex in vertices:
        point = list(_vec(vertex.get_coordinates()))
        entities.append(
            {
                "entity_id": vertex_ids[vertex.topo_id],
                "kind": "vertex",
                "topo_id": vertex.topo_id,
                "parent_entity_ids": sorted(
                    edge_ids[edge.topo_id]
                    for edge in edges
                    if any(
                        child.topo_id == vertex.topo_id
                        for child in edge._iter_vertices()
                    )
                ),
                "child_entity_ids": [],
                "source": source_by_key[("vertex", vertex.topo_id)],
                "geometry": {"type": "point", "position": point},
                "properties": {
                    "bounds": {"min": point, "max": point},
                    "position": point,
                },
                "tags": sorted(vertex._list_tags()),
            }
        )
    entity_document = {
        "schema_version": "2.0",
        "definition_id": definition.definition_id,
        "geometry_asset_id": geometry_hash,
        "edge_asset_id": edge_hash,
        "entities": sorted(entities, key=lambda item: item["entity_id"]),
        "face_groups": [
            {
                "group_id": index,
                "entity_id": group.entity_id,
                "mesh_index": 0,
                "primitive_index": 0,
                "first_index": group.first_index,
                "index_count": group.index_count,
            }
            for index, group in enumerate(render_mesh.groups)
        ],
        "edge_groups": [
            {
                "group_id": index,
                "entity_id": group.entity_id,
                "mesh_index": 0,
                "primitive_index": 0,
                "first_index": group.first_index,
                "index_count": group.index_count,
            }
            for index, group in enumerate(edge_mesh.groups)
        ],
    }
    entity_bytes = canonical_json_bytes(entity_document)
    entity_hash = sha256_bytes(entity_bytes)
    entity_uri = f"entities/sha256-{entity_hash.removeprefix('sha256:')}.json"
    return (
        geometry_records,
        {
            **_asset_record(
                entity_bytes,
                uri=entity_uri,
                media_type="application/vnd.simplecad.entities+json",
            )
        },
        {
            geometry_uri: triangle_glb,
            edge_uri: line_glb,
            entity_uri: entity_bytes,
        },
        geometry_hash,
        entity_hash,
    )


def _placement(value: Mapping[str, Any]) -> Placement:
    return placement_from_canonical(value)


def _node_id(path: tuple[str, ...]) -> str:
    return "node/" + "/".join(path)


def _build_nodes(
    root: Definition,
    definitions: Mapping[str, Definition],
    geometry_ids: Mapping[str, str],
    entity_ids: Mapping[str, str],
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[str]],
    dict[tuple[str, str], str],
]:
    nodes: list[dict[str, Any]] = []
    occurrences: dict[str, list[str]] = {}
    children: dict[tuple[str, str], str] = {}

    def visit(
        definition: Definition,
        path: tuple[str, ...],
        parent_node_id: str | None,
        transform: Placement,
        component_id: str | None,
        instance_id: str | None,
        display_name: str | None,
    ) -> str:
        node_id = _node_id(path)
        occurrences.setdefault(definition.definition_id, []).append(node_id)
        is_part = isinstance(definition, PartDefinition)
        nodes.append(
            {
                "node_id": node_id,
                "parent_node_id": parent_node_id,
                "display_name": display_name or definition.definition_id,
                "node_kind": "part" if is_part else "assembly",
                "definition_id": definition.definition_id,
                "definition_kind": definition.definition_kind,
                "component_id": component_id,
                "instance_id": instance_id,
                "transform": transform.to_dict(),
                "geometry_asset_id": geometry_ids.get(definition.definition_id),
                "entity_asset_id": entity_ids.get(definition.definition_id),
                "material_id": (
                    definition.material_ref.material_id
                    if is_part and definition.material_ref is not None
                    else None
                ),
                "properties": {
                    "content_hash": definition.content_hash,
                    "revision": definition.revision,
                },
            }
        )
        if isinstance(definition, AssemblyDefinition):
            for instance in definition.instances:
                child = definitions[instance.definition_id]
                child_path = (*path, instance.instance_id)
                child_node = visit(
                    child,
                    child_path,
                    node_id,
                    _placement(instance.placement),
                    instance.instance_id,
                    _node_id(child_path),
                    instance.name,
                )
                children[(node_id, instance.instance_id)] = child_node
        return node_id

    root_node = visit(
        root,
        (root.definition_id,),
        None,
        identity_placement(),
        None,
        None,
        root.metadata.get("name"),
    )
    for values in occurrences.values():
        values.sort()
    return sorted(nodes, key=lambda item: item["node_id"]), occurrences, children


def _producer_feature(
    definition_id: str,
    feature_graph: FeatureGraphArtifact,
    *,
    parameter: str,
    value: str,
    op_prefix: str,
) -> str | None:
    matches = [
        node
        for node in feature_graph.graph.get("nodes", [])
        if str(node.get("op", "")).startswith(op_prefix)
        and node.get("params", {}).get(parameter) == value
    ]
    if len(matches) != 1:
        return None
    return _source_feature_id(definition_id, str(matches[0]["node_id"]))


def _connector_snapshot_id(node_id: str, connector_id: str) -> str:
    return f"connector/{node_id.removeprefix('node/')}/{connector_id}"


def _connectors(
    definitions: Mapping[str, Definition],
    feature_graphs: Mapping[str, FeatureGraphArtifact],
    occurrences: Mapping[str, list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    connectors: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    for definition_id in sorted(definitions):
        definition = definitions[definition_id]
        interfaces = (
            definition.connectors
            if isinstance(definition, PartDefinition)
            else definition.public_connectors
        )
        graph = feature_graphs[definition_id]
        for node_id in occurrences.get(definition_id, []):
            for interface in interfaces:
                is_public = isinstance(definition, AssemblyDefinition)
                connector_id = interface.connector_id
                feature_id = _producer_feature(
                    definition_id,
                    graph,
                    parameter="public_connector_id" if is_public else "connector_id",
                    value=connector_id,
                    op_prefix=(
                        "make_set_public_connector_rassembly"
                        if is_public
                        else "make_add_connector_rpart"
                    ),
                )
                snapshot_id = _connector_snapshot_id(node_id, connector_id)
                source_snapshot_id: str | None = None
                if is_public:
                    source_node_id = f"{node_id}/{interface.source_component_id}"
                    source_snapshot_id = _connector_snapshot_id(
                        source_node_id, interface.source_connector_id
                    )
                connectors.append(
                    {
                        "connector_snapshot_id": snapshot_id,
                        "node_id": node_id,
                        "definition_id": definition_id,
                        "definition_kind": definition.definition_kind,
                        "connector_id": connector_id,
                        "name": interface.name or connector_id,
                        "anchor_kind": "public" if is_public else interface.anchor_kind,
                        "local_frame": dict(interface.local_frame),
                        "binding": (
                            dict(interface.binding)
                            if interface.binding is not None
                            else None
                        ),
                        "source_connector_snapshot_id": source_snapshot_id,
                        "source_feature_id": feature_id,
                    }
                )
                index.append(
                    {
                        "connector_index_id": (
                            f"connector-index/{node_id.removeprefix('node/')}"
                            f"/{connector_id}"
                        ),
                        "definition_id": definition_id,
                        "node_id": node_id,
                        "connector_id": connector_id,
                        "connector_snapshot_id": snapshot_id,
                        "source_feature_id": feature_id,
                    }
                )
    return (
        sorted(connectors, key=lambda item: item["connector_snapshot_id"]),
        sorted(index, key=lambda item: item["connector_index_id"]),
    )


def _joints(
    definitions: Mapping[str, Definition],
    feature_graphs: Mapping[str, FeatureGraphArtifact],
    occurrences: Mapping[str, list[str]],
    children: Mapping[tuple[str, str], str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    joints: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    for definition_id in sorted(definitions):
        definition = definitions[definition_id]
        if not isinstance(definition, AssemblyDefinition) or not definition.relations:
            continue
        instance_by_id = {item.instance_id: item for item in definition.instances}
        graph = feature_graphs[definition_id]
        for assembly_node in occurrences[definition_id]:
            for relation in definition.relations:
                constraint_id = str(relation["constraint_id"])
                feature_id = _producer_feature(
                    definition_id,
                    graph,
                    parameter="constraint_id",
                    value=constraint_id,
                    op_prefix=(
                        f"make_{relation['constraint_kind']}_constraint_rassembly"
                    ),
                )
                if feature_id is None:
                    raise ProductSceneError(
                        f"joint {definition_id!r}/{constraint_id!r} has no unique producer"
                    )

                def endpoint(side: str) -> dict[str, Any]:
                    ref = relation[side]
                    component_id = str(ref["component_id"])
                    connector_id = str(ref["connector_id"])
                    child_node = children[(assembly_node, component_id)]
                    instance = instance_by_id[component_id]
                    return {
                        "definition_id": instance.definition_id,
                        "component_id": component_id,
                        "instance_id": child_node,
                        "connector_id": connector_id,
                        "connector_snapshot_id": _connector_snapshot_id(
                            child_node, connector_id
                        ),
                    }

                parameters = {
                    key: relation.get(key)
                    for key in (
                        "drive_distance",
                        "drive_angle_degrees",
                        "pitch_radius_a",
                        "pitch_radius_b",
                        "pulley_radius_a",
                        "pulley_radius_b",
                        "pitch_radius",
                        "phase_offset",
                    )
                    if relation.get(key) is not None
                }
                limits = {
                    key: relation.get(key)
                    for key in ("distance_limit", "angle_limit")
                    if relation.get(key) is not None
                }
                occurrence_path = assembly_node.removeprefix("node/")
                joint_id = f"joint/{occurrence_path}/{constraint_id}"
                joints.append(
                    {
                        "joint_id": joint_id,
                        "assembly_definition_id": definition_id,
                        "joint_type": str(relation["constraint_kind"]),
                        "connector_a": endpoint("connector_a"),
                        "connector_b": endpoint("connector_b"),
                        "parameters": parameters,
                        "limits": limits or None,
                        "source_feature_id": feature_id,
                    }
                )
                index.append(
                    {
                        "joint_index_id": (
                            f"joint-index/{occurrence_path}/{constraint_id}"
                        ),
                        "assembly_definition_id": definition_id,
                        "joint_id": joint_id,
                        "source_feature_id": feature_id,
                    }
                )
    return (
        sorted(joints, key=lambda item: item["joint_id"]),
        sorted(index, key=lambda item: item["joint_index_id"]),
    )


def _camera(part_definitions: list[PartDefinition]) -> dict[str, Any]:
    if not part_definitions:
        raise ProductSceneError("product scene has no part geometry")
    bounds = []
    for definition in part_definitions:
        part = materialize_definition(definition)
        bounds.append(solid_asset_bounds(part.body))
    minimum = [min(item[0][axis] for item in bounds) for axis in range(3)]
    maximum = [max(item[1][axis] for item in bounds) for axis in range(3)]
    target = [(minimum[axis] + maximum[axis]) * 0.5 for axis in range(3)]
    span = max(maximum[axis] - minimum[axis] for axis in range(3))
    distance = max(span * 2.5, 10.0)
    return {
        "target": target,
        "position": [target[0] + distance, target[1] - distance, target[2] + distance],
        "up": [0.0, 0.0, 1.0],
        "near": max(distance / 1000.0, 0.001),
        "far": distance * 100.0,
        "fit_mode": "bounds",
        "margin": 0.08,
    }


def compile_product_scene(
    root: Definition,
    *,
    linear_tolerance: float = DEFAULT_LINEAR_TOLERANCE,
    angular_tolerance: float = DEFAULT_ANGULAR_TOLERANCE,
) -> ProductScenePackage:
    """Compile one durable definition closure into a complete Scene 2.0 package."""

    if not isinstance(root, (PartDefinition, AssemblyDefinition)):
        raise TypeError("root must be a PartDefinition or AssemblyDefinition")
    definitions = _definition_closure(root)
    blobs: dict[str, bytes] = {}
    definition_records: list[dict[str, Any]] = []
    product_assets: list[dict[str, Any]] = []
    feature_assets: list[dict[str, Any]] = []
    source_assets_by_uri: dict[str, dict[str, Any]] = {}
    source_ids: dict[str, str] = {}
    source_uris: dict[str, str] = {}
    feature_graphs: dict[str, FeatureGraphArtifact] = {}
    feature_index: list[dict[str, Any]] = []
    source_index: list[dict[str, Any]] = []

    for definition_id in sorted(definitions):
        definition = definitions[definition_id]
        product_payload = _definition_bytes(definition)
        product_hash = sha256_bytes(product_payload)
        product_uri = (
            f"products/sha256-{product_hash.removeprefix('sha256:')}"
            + (".part.zip" if isinstance(definition, PartDefinition) else ".assembly.zip")
        )
        blobs[product_uri] = product_payload
        product_assets.append(
            {
                **_asset_record(
                    product_payload,
                    uri=product_uri,
                    media_type=_definition_media_type(definition),
                ),
                "definition_id": definition_id,
                "definition_kind": definition.definition_kind,
                "revision": definition.revision,
                "content_hash": definition.content_hash,
            }
        )

        graph = _feature_graph(definition)
        feature_graphs[definition_id] = graph
        feature_payload = definition.blobs[definition.feature_graph_ref.path]
        feature_hash = sha256_bytes(feature_payload)
        feature_uri = (
            f"features/sha256-{feature_hash.removeprefix('sha256:')}.zip"
        )
        blobs[feature_uri] = feature_payload
        feature_assets.append(
            {
                **_asset_record(
                    feature_payload,
                    uri=feature_uri,
                    media_type="application/vnd.simplecad.feature-graph+zip",
                ),
                "definition_id": definition_id,
                "graph_id": graph.owner_definition_id,
                "graph_revision": graph.content_hash,
            }
        )
        definition_records.append(
            {
                "definition_id": definition_id,
                "definition_kind": definition.definition_kind,
                "revision": definition.revision,
                "content_hash": definition.content_hash,
                "product_asset_id": product_hash,
                "feature_graph_asset_id": feature_hash,
            }
        )
        for source_file in graph.source_files:
            payload = graph.blobs[source_file.uri]
            source_asset_id = source_file.source_file_id
            source_ids[source_file.source_file_id] = source_asset_id
            source_uris[source_file.source_file_id] = source_file.uri
            existing = source_assets_by_uri.get(source_file.uri)
            record = {
                "source_asset_id": source_asset_id,
                "uri": source_file.uri,
                "sha256": sha256_bytes(payload),
                "byte_length": len(payload),
                "media_type": "text/x-python; charset=utf-8",
                "display_name": source_file.display_path,
            }
            if existing is not None and (
                existing["sha256"] != record["sha256"]
                or blobs[source_file.uri] != payload
            ):
                raise ProductSceneError(
                    f"source URI collision at {source_file.uri!r}"
                )
            source_assets_by_uri.setdefault(source_file.uri, record)
            blobs[source_file.uri] = payload

    for definition_id in sorted(definitions):
        records, sources = _feature_records(
            definitions[definition_id],
            feature_graphs[definition_id],
            source_ids,
            source_uris,
        )
        feature_index.extend(records)
        source_index.extend(sources)

    geometry_assets_by_id: dict[str, dict[str, Any]] = {}
    entity_assets: list[dict[str, Any]] = []
    geometry_ids: dict[str, str] = {}
    entity_ids: dict[str, str] = {}
    part_definitions = [
        definition
        for definition in definitions.values()
        if isinstance(definition, PartDefinition)
    ]
    for definition in sorted(part_definitions, key=lambda item: item.definition_id):
        geometry_records, entity_record, part_blobs, geometry_id, entity_id = (
            _part_geometry(
                definition,
                linear_tolerance=linear_tolerance,
                angular_tolerance=angular_tolerance,
            )
        )
        for record in geometry_records:
            geometry_assets_by_id.setdefault(record["asset_id"], record)
        entity_assets.append(entity_record)
        blobs.update(part_blobs)
        geometry_ids[definition.definition_id] = geometry_id
        entity_ids[definition.definition_id] = entity_id

    nodes, occurrences, children = _build_nodes(
        root, definitions, geometry_ids, entity_ids
    )
    connectors, connector_index = _connectors(
        definitions, feature_graphs, occurrences
    )
    joints, joint_index = _joints(
        definitions, feature_graphs, occurrences, children
    )
    manifest = with_scene_revision(
        {
            "schema_version": "2.0",
            "scene_id": root.definition_id,
            "units": "mm",
            "roots": [_node_id((root.definition_id,))],
            "definitions": sorted(
                definition_records, key=lambda item: item["definition_id"]
            ),
            "geometry_assets": sorted(
                geometry_assets_by_id.values(), key=lambda item: item["asset_id"]
            ),
            "entity_assets": sorted(
                entity_assets, key=lambda item: item["asset_id"]
            ),
            "product_assets": sorted(
                product_assets, key=lambda item: item["definition_id"]
            ),
            "feature_graph_assets": sorted(
                feature_assets, key=lambda item: item["definition_id"]
            ),
            "source_assets": sorted(
                source_assets_by_uri.values(), key=lambda item: item["uri"]
            ),
            "nodes": nodes,
            "connectors": connectors,
            "joints": joints,
            "feature_index": sorted(
                feature_index, key=lambda item: item["feature_id"]
            ),
            "source_index": sorted(
                source_index, key=lambda item: item["source_index_id"]
            ),
            "connector_index": connector_index,
            "joint_index": joint_index,
            "camera": _camera(part_definitions),
            "extensions": {
                "compile_options": {
                    "linear_tolerance": float(linear_tolerance),
                    "angular_tolerance": float(angular_tolerance),
                }
            },
        }
    )
    package = ProductScenePackage(manifest=manifest, blobs=blobs)
    object.__setattr__(package, "_validated_manifest", canonical_json_bytes(manifest))
    validate_product_scene_package(package)
    return package


def validate_product_scene_package(package: ProductScenePackage) -> None:
    if not isinstance(package, ProductScenePackage):
        raise TypeError("package must be a ProductScenePackage")
    manifest = package.manifest
    _schema_validate(manifest)
    if manifest["revision"] != compute_scene_revision(manifest):
        raise ProductSceneError("scene revision is invalid")

    asset_records = [
        *manifest["geometry_assets"],
        *manifest["entity_assets"],
        *manifest["product_assets"],
        *manifest["feature_graph_assets"],
    ]
    source_records = list(manifest["source_assets"])
    expected_uris = {str(item["uri"]) for item in [*asset_records, *source_records]}
    if set(package.blobs) != expected_uris:
        raise ProductSceneError("scene blob set differs from asset records")
    for record in [*asset_records, *source_records]:
        uri = str(record["uri"])
        payload = package.blobs[uri]
        if record["byte_length"] != len(payload):
            raise ProductSceneError(f"scene asset {uri!r} byte_length differs")
        digest = sha256_bytes(payload)
        if record["sha256"] != digest:
            raise ProductSceneError(f"scene asset {uri!r} sha256 differs")
        if "asset_id" in record and record["asset_id"] != digest:
            raise ProductSceneError(f"scene asset {uri!r} identity differs")
        if "source_asset_id" in record and not isinstance(
            record["source_asset_id"], str
        ):
            raise ProductSceneError(f"source asset {uri!r} identity is invalid")

    definitions = {item["definition_id"]: item for item in manifest["definitions"]}
    if len(definitions) != len(manifest["definitions"]):
        raise ProductSceneError("scene definition IDs must be unique")
    feature_ids = {item["feature_id"] for item in manifest["feature_index"]}
    if len(feature_ids) != len(manifest["feature_index"]):
        raise ProductSceneError("scene feature IDs must be unique")
    for feature in manifest["feature_index"]:
        if feature["definition_id"] not in definitions:
            raise ProductSceneError("feature references an unknown definition")
        if not set(feature["input_feature_ids"]).issubset(feature_ids):
            raise ProductSceneError("feature input does not resolve")

    source_asset_ids = {item["source_asset_id"] for item in source_records}
    for source in manifest["source_index"]:
        if (
            source["source_asset_id"] not in source_asset_ids
            or source["feature_id"] not in feature_ids
        ):
            raise ProductSceneError("source index reference does not resolve")

    product_records = list(manifest["product_assets"])
    feature_records = list(manifest["feature_graph_assets"])
    product_by_id = {item["definition_id"]: item for item in product_records}
    feature_by_id = {item["definition_id"]: item for item in feature_records}
    if len(product_by_id) != len(product_records) or len(feature_by_id) != len(feature_records):
        raise ProductSceneError("scene product and feature asset definition IDs must be unique")
    for definition_record in manifest["definitions"]:
        definition_id = definition_record["definition_id"]
        product_record = product_by_id.get(definition_id)
        feature_record = feature_by_id.get(definition_id)
        if product_record is None or feature_record is None:
            raise ProductSceneError("definition assets do not resolve")
        if definition_record["product_asset_id"] != product_record["asset_id"]:
            raise ProductSceneError("scene definition product asset reference differs")
        if definition_record["feature_graph_asset_id"] != feature_record["asset_id"]:
            raise ProductSceneError("scene definition feature asset reference differs")
    trusted = package._validated_manifest == canonical_json_bytes(dict(manifest))
    for definition_id, record in definitions.items():
        if definition_id not in product_by_id or definition_id not in feature_by_id:
            raise ProductSceneError("definition assets do not resolve")
        product_record = product_by_id[definition_id]
        if not trusted:
            payload = package.blobs[product_record["uri"]]
            decoded: Definition
            if record["definition_kind"] == "single_solid":
                decoded = load_part_definition(payload)
            else:
                decoded = decode_assembly_definition(payload)
            if (
                decoded.definition_id != definition_id
                or decoded.definition_kind != record["definition_kind"]
                or decoded.revision != record["revision"]
                or decoded.content_hash != record["content_hash"]
            ):
                raise ProductSceneError("product asset identity differs")
        graph_record = feature_by_id[definition_id]
        graph = load_feature_graph_artifact(package.blobs[graph_record["uri"]])
        if (
            graph.owner_definition_id != definition_id
            or graph.content_hash != graph_record["graph_revision"]
        ):
            raise ProductSceneError("feature graph asset identity differs")

    geometry_ids = {item["asset_id"] for item in manifest["geometry_assets"]}
    entity_ids = {item["asset_id"] for item in manifest["entity_assets"]}
    node_ids = {item["node_id"] for item in manifest["nodes"]}
    if len(node_ids) != len(manifest["nodes"]):
        raise ProductSceneError("scene node IDs must be unique")
    if not set(manifest["roots"]).issubset(node_ids):
        raise ProductSceneError("scene root does not resolve")
    for node in manifest["nodes"]:
        if node["definition_id"] not in definitions:
            raise ProductSceneError("node definition does not resolve")
        if node["parent_node_id"] is not None and node["parent_node_id"] not in node_ids:
            raise ProductSceneError("node parent does not resolve")
        if node["geometry_asset_id"] is not None and node["geometry_asset_id"] not in geometry_ids:
            raise ProductSceneError("node geometry asset does not resolve")
        if node["entity_asset_id"] is not None and node["entity_asset_id"] not in entity_ids:
            raise ProductSceneError("node entity asset does not resolve")

    connector_by_id = {
        item["connector_snapshot_id"]: item for item in manifest["connectors"]
    }
    if len(connector_by_id) != len(manifest["connectors"]):
        raise ProductSceneError("connector snapshot IDs must be unique")
    for connector in manifest["connectors"]:
        if connector["node_id"] not in node_ids:
            raise ProductSceneError("connector node does not resolve")
        source_snapshot = connector["source_connector_snapshot_id"]
        if connector["anchor_kind"] == "public":
            if source_snapshot not in connector_by_id:
                raise ProductSceneError("public connector source does not resolve")
        elif source_snapshot is not None:
            raise ProductSceneError("part connector cannot reference a public source")
        source_feature = connector["source_feature_id"]
        if source_feature is not None and source_feature not in feature_ids:
            raise ProductSceneError("connector feature does not resolve")
    for start in connector_by_id:
        seen: set[str] = set()
        current = start
        while connector_by_id[current]["source_connector_snapshot_id"] is not None:
            if current in seen:
                raise ProductSceneError("public connector graph contains a cycle")
            seen.add(current)
            current = connector_by_id[current]["source_connector_snapshot_id"]
    for joint in manifest["joints"]:
        if (
            joint["connector_a"]["connector_snapshot_id"] not in connector_by_id
            or joint["connector_b"]["connector_snapshot_id"] not in connector_by_id
        ):
            raise ProductSceneError("joint connector does not resolve")
        source_feature = joint["source_feature_id"]
        if source_feature is not None and source_feature not in feature_ids:
            raise ProductSceneError("joint feature does not resolve")

    feature_by_pair = {
        (item["graph_id"], item["node_id"]): item["feature_id"]
        for item in manifest["feature_index"]
    }
    for entity_record in manifest["entity_assets"]:
        document = parse_canonical_json(package.blobs[entity_record["uri"]])
        if document["definition_id"] not in definitions:
            raise ProductSceneError("entity asset definition does not resolve")
        for entity in document["entities"]:
            source = entity["source"]
            if source["kind"] != "feature_output":
                raise ProductSceneError("entity source must be a feature_output")
            if (source["graph_id"], source["node_id"]) not in feature_by_pair:
                raise ProductSceneError("entity feature output does not resolve")
    object.__setattr__(
        package,
        "_validated_manifest",
        canonical_json_bytes(dict(package.manifest)),
    )


def encode_product_scene(package: ProductScenePackage) -> bytes:
    validate_product_scene_package(package)
    return canonical_zip_bytes(
        {_SCENE_MANIFEST: canonical_json_bytes(dict(package.manifest)), **package.blobs}
    )


def read_scene_package(data: bytes | bytearray | memoryview | str | Path) -> ProductScenePackage:
    raw = Path(data).read_bytes() if isinstance(data, (str, Path)) else bytes(data)
    archive = preflight_zip_bytes(raw)
    manifest = parse_canonical_json(archive.members[_SCENE_MANIFEST])
    if not isinstance(manifest, Mapping):
        raise ProductSceneError("scene.json must contain an object")
    package = ProductScenePackage(
        manifest=manifest,
        blobs={
            path: payload
            for path, payload in archive.members.items()
            if path != _SCENE_MANIFEST
        },
    )
    validate_product_scene_package(package)
    return package


__all__ = [
    "ProductSceneError",
    "ProductScenePackage",
    "compile_product_scene",
    "encode_product_scene",
    "read_scene_package",
    "validate_product_scene_package",
]

"""Small, strict Scene 1.0 compiler for manual and product values."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from simplecadapi._cpp import (
    Assembly,
    Compound,
    Connector,
    Edge,
    Face,
    Material,
    OperationGraph,
    OperationNode,
    Part,
    PublicConnectorRef,
    resolve_connector_placement,
    resolve_item_connector_placement,
    Solid,
    Vertex,
)
from ..product.placement import Placement, identity_placement
from ..recording.serializer import _candidate_shapes_for_geo_selection, _geo_selector_score
from ..scene.archive import canonical_zip_bytes
from ..scene.canonical import canonical_json_bytes, canonical_json_hash, with_scene_revision
from ..scene.documents import EntityDocument, NormalizedProductDocument, SceneDocument
from ..scene.glb_writer import write_line_glb, write_triangle_glb
from ..scene.render_mesh import ASSET_TO_SCENE, RenderEdgeMesh, RenderMesh, build_edge_mesh, build_render_mesh, solid_asset_bounds
from ..scene.validation import validate_scene_package


DEFAULT_LINEAR_TOLERANCE = 0.1
DEFAULT_ANGULAR_TOLERANCE = 0.08
_IDENTITY = {
    "origin": [0.0, 0.0, 0.0],
    "x_axis": [1.0, 0.0, 0.0],
    "y_axis": [0.0, 1.0, 0.0],
    "z_axis": [0.0, 0.0, 1.0],
}


@dataclass(frozen=True, slots=True)
class SceneRoot:
    root_id: str
    value: Solid | Compound | Part | Assembly
    transform: Placement = field(default_factory=identity_placement)
    source_element_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.root_id, str) or not self.root_id or not self.root_id[0].isalpha() or any(
            char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for char in self.root_id
        ):
            raise ValueError("root_id must be a Scene logical ID")
        if not isinstance(self.value, (Solid, Compound, Part, Assembly)):
            raise TypeError("SceneRoot.value must be Solid, Compound, Part, or Assembly")
        if not isinstance(self.transform, Placement):
            raise TypeError("SceneRoot.transform must be a Placement")
        if self.source_element_id is not None and not str(self.source_element_id):
            raise ValueError("source_element_id must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class _EmbeddedSourceFile:
    path: str
    uri: str
    content_hash: str
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class SceneSource:
    kind: str
    source_id: str | None = None
    graph_id: str | None = None
    artifact_hash: str | None = None
    format: str | None = None
    definition_id: str | None = None
    revision: str | None = None
    artifact_bytes: bytes | None = None
    _graph: OperationGraph | None = field(default=None, compare=False, repr=False)
    _source_files: tuple["_EmbeddedSourceFile", ...] = field(
        default=(), compare=False, repr=False
    )

    def __post_init__(self) -> None:
        supported = {"manual", "model", "imported", "part_package", "assembly_package"}
        if self.kind not in supported:
            raise ValueError(f"SceneSource.kind must be one of: {', '.join(sorted(supported))}")
        if self.kind == "manual" and not self.source_id:
            raise ValueError("manual SceneSource requires source_id")
        if self.kind == "model" and (not self.graph_id or not self.artifact_hash):
            raise ValueError("model SceneSource requires graph_id and artifact_hash")
        if self.kind == "imported" and not self.format:
            raise ValueError("imported SceneSource requires format")
        if self.kind in {"part_package", "assembly_package"} and (
            not self.definition_id or not self.revision or not self.artifact_hash
        ):
            raise ValueError(
                "product package SceneSource requires definition_id, revision, and artifact_hash"
            )
        if self.kind in {"part_package", "assembly_package"} and self.artifact_bytes is not None:
            raise ValueError("product package SceneSource cannot embed the upstream package")
        if self._graph is not None and self._graph.graph_id != self.graph_id:
            raise ValueError("SceneSource graph evidence must match graph_id")


@dataclass(frozen=True, slots=True)
class SceneCompileOptions:
    linear_tolerance: float = DEFAULT_LINEAR_TOLERANCE
    angular_tolerance: float = DEFAULT_ANGULAR_TOLERANCE
    embed_source: bool = False
    embed_presentation: bool = False

    def __post_init__(self) -> None:
        if not 0.0 < float(self.linear_tolerance) <= 1_000_000.0:
            raise ValueError("linear_tolerance must be in (0, 1000000]")
        if not 0.0 < float(self.angular_tolerance) <= 3.141592653589793:
            raise ValueError("angular_tolerance must be in (0, pi]")
        if self.embed_presentation:
            raise ValueError("presentation embedding is not implemented in the first compiler slice")


@dataclass(frozen=True, slots=True)
class CompiledScenePackage:
    manifest: Mapping[str, Any]
    blobs: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", MappingProxyType(_freeze_mapping(dict(self.manifest))))
        object.__setattr__(self, "blobs", MappingProxyType({str(key): bytes(value) for key, value in self.blobs.items()}))

    @property
    def scene(self) -> Mapping[str, Any]:
        return self.manifest


def compile_scene(
    *,
    scene_id: str,
    roots: Sequence[SceneRoot],
    source: SceneSource | None = None,
    presentation: Any = None,
    options: SceneCompileOptions | None = None,
) -> CompiledScenePackage:
    if presentation is not None:
        raise ValueError("presentation compilation is not implemented in the first compiler slice")
    options = options or SceneCompileOptions()
    root_values = tuple(roots)
    if not root_values:
        raise ValueError("compile_scene requires at least one root")
    if len({root.root_id for root in root_values}) != len(root_values):
        raise ValueError("SceneRoot.root_id values must be unique")
    source_descriptor = _coerce_source(
        source,
        root_values,
        embed_source=options.embed_source,
    )
    if source_descriptor.kind == "imported":
        raise ValueError("imported source compilation is not implemented in the first compiler slice")

    definitions: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    products: dict[str, dict[str, Any]] = {}
    renderables: dict[str, _Renderable] = {}
    appearances: dict[str, dict[str, Any]] = {}
    pending_connectors: list[_PendingConnector] = []
    for root in sorted(root_values, key=lambda item: item.root_id.encode("utf-8")):
        _compile_root(
            root,
            source=source_descriptor,
            options=options,
            definitions=definitions,
            nodes=nodes,
            products=products,
            renderables=renderables,
            appearances=appearances,
            pending_connectors=pending_connectors,
        )
    if not renderables:
        raise ValueError("scene contains no renderable Part or Shape definition")

    _reindex_node_orders(nodes)
    geometry_assets: dict[str, dict[str, Any]] = {}
    edge_assets: dict[str, dict[str, Any]] = {}
    entity_assets: dict[str, dict[str, Any]] = {}
    entity_asset_ids: dict[str, str] = {}
    blobs: dict[str, bytes] = {}
    for definition_id, renderable in sorted(renderables.items(), key=lambda item: item[0].encode("utf-8")):
        triangle_glb = write_triangle_glb(renderable.render_mesh)
        line_glb = write_line_glb(renderable.edge_mesh)
        geometry_hash = _hash_bytes(triangle_glb)
        edge_hash = _hash_bytes(line_glb)
        definition_kind = definitions[definition_id]["kind"]
        entity_payload = _entity_asset(
            definition_id=definition_id,
            definition_kind=definition_kind,
            geometry_asset_id=geometry_hash,
            edge_asset_id=edge_hash,
            solid=renderable.solid,
            render_mesh=renderable.render_mesh,
            edge_mesh=renderable.edge_mesh,
            source=source_descriptor,
            definition_source=definitions[definition_id]["source"],
            ocp_version=_ocp_version(),
        )
        EntityDocument.from_value(entity_payload)
        entity_bytes = canonical_json_bytes(entity_payload)
        entity_hash = _hash_bytes(entity_bytes)
        geometry_uri = f"geometry/sha256-{geometry_hash.removeprefix('sha256:')}.glb"
        edge_uri = f"edges/sha256-{edge_hash.removeprefix('sha256:')}.glb"
        entity_uri = f"entities/sha256-{entity_hash.removeprefix('sha256:')}.json"
        blobs.update({geometry_uri: triangle_glb, edge_uri: line_glb, entity_uri: entity_bytes})
        bounds = _scene_bounds_from_glb(renderable.render_mesh.bounds)
        edge_bounds = _scene_bounds_from_glb(renderable.edge_mesh.bounds)
        geometry_assets.setdefault(geometry_hash, _asset(geometry_hash, geometry_uri, len(triangle_glb), bounds, {"linear_tolerance": options.linear_tolerance, "angular_tolerance": options.angular_tolerance}))
        edge_assets.setdefault(edge_hash, _asset(edge_hash, edge_uri, len(line_glb), edge_bounds, {"linear_tolerance": options.linear_tolerance}))
        entity_assets.setdefault(entity_hash, {"entity_asset_id": entity_hash, "uri": entity_uri, "media_type": "application/vnd.simplecad.entities+json", "byte_length": len(entity_bytes), "content_hash": entity_hash})
        entity_asset_ids[definition_id] = entity_hash
        definition = definitions[definition_id]
        definition.update({"geometry_asset_id": geometry_hash, "edge_asset_id": edge_hash, "entity_asset_id": entity_hash, "appearance_id": renderable.appearance_id})

    if source_descriptor.artifact_bytes is not None:
        blobs["model/model.json"] = bytes(source_descriptor.artifact_bytes)
        for source_file in source_descriptor._source_files:
            blobs[source_file.uri] = source_file.content

    for product in products.values():
        NormalizedProductDocument.from_value(product)
    connectors = _finalize_connectors(
        pending_connectors,
        definitions=definitions,
        entity_asset_ids=entity_asset_ids,
        source=source_descriptor,
    )

    generator = _generator()
    manifest = {
        "schema_version": "1.0",
        "extensions_used": [],
        "extensions_required": [],
        "extensions": {},
        "scene_id": scene_id,
        "generator": generator,
        "source": _scene_source_record(source_descriptor),
        "coordinate_system": {"length_unit": "mm", "handedness": "right", "up_axis": "+Z"},
        "compile_options": {"linear_tolerance": options.linear_tolerance, "angular_tolerance": options.angular_tolerance, "embed_source": source_descriptor.artifact_bytes is not None, "embed_presentation": False},
        "definitions": sorted(definitions.values(), key=lambda item: item["definition_id"].encode("utf-8")),
        "nodes": sorted(nodes, key=lambda item: item["node_id"].encode("utf-8")),
        "geometry_assets": sorted(geometry_assets.values(), key=lambda item: item["asset_id"].encode("utf-8")),
        "edge_assets": sorted(edge_assets.values(), key=lambda item: item["asset_id"].encode("utf-8")),
        "appearances": sorted(appearances.values(), key=lambda item: item["appearance_id"].encode("utf-8")),
        "entity_assets": sorted(entity_assets.values(), key=lambda item: item["entity_asset_id"].encode("utf-8")),
        "connectors": sorted(connectors, key=lambda item: item["connector_snapshot_id"].encode("utf-8")),
        "cameras": [],
        "lights": [],
        "annotations": [],
        "diagnostics": [],
    }
    manifest = with_scene_revision(manifest)
    SceneDocument.from_value(manifest)
    report = validate_scene_package(manifest, blobs)
    if not report.valid:
        raise ValueError("compiled scene package failed validation: " + "; ".join(issue.message for issue in report.issues[:3]))
    return CompiledScenePackage(manifest=manifest, blobs=blobs)


def export_scene(*, package: CompiledScenePackage, path: str | os.PathLike[str]) -> None:
    if not isinstance(package, CompiledScenePackage):
        raise TypeError("package must be a CompiledScenePackage")
    manifest = _thaw_mapping(package.manifest)
    blobs = dict(package.blobs)
    report = validate_scene_package(manifest, blobs)
    if not report.valid:
        raise ValueError("cannot export invalid scene package")
    members = {"scene.json": canonical_json_bytes(manifest), **blobs}
    Path(path).write_bytes(canonical_zip_bytes(members))


@dataclass(frozen=True, slots=True)
class _Renderable:
    solid: Solid
    render_mesh: RenderMesh
    edge_mesh: RenderEdgeMesh
    appearance_id: str


@dataclass(frozen=True, slots=True)
class _PendingConnector:
    root_id: str
    owner_kind: str
    owner_definition_id: str
    owner: Part | Assembly
    connector: Connector | PublicConnectorRef


def _compile_root(root: SceneRoot, *, source: SceneSource, options: SceneCompileOptions, definitions: dict[str, dict[str, Any]], nodes: list[dict[str, Any]], products: dict[str, dict[str, Any]], renderables: dict[str, _Renderable], appearances: dict[str, dict[str, Any]], pending_connectors: list[_PendingConnector]) -> None:
    if isinstance(root.value, (Solid, Compound)):
        definition_source = _shape_definition_source(root.root_id, root.value, source)
        definition_id = _definition_id_for_shape(root.root_id, definition_source)
        solid = root.value if isinstance(root.value, Solid) else _compound_solid(root.value)
        renderable = _make_renderable(definition_id, solid, options, appearances)
        renderables[definition_id] = renderable
        definitions[definition_id] = {"definition_id": definition_id, "kind": "shape", "name": None, "source": definition_source, "sdk_metadata": {}}
        nodes.append(_node(f"instance/{root.root_id}", None, 0, definition_id, None, root.transform, {"kind": "shape_root", "root_id": root.root_id}))
        return
    if isinstance(root.value, Part):
        _compile_part(root.root_id, root.value, root.transform, source, options, definitions, nodes, products, renderables, appearances, pending_connectors, parent_node_id=None, component_path=[])
        return
    _compile_assembly(root.root_id, root.value, root.transform, source, options, definitions, nodes, products, renderables, appearances, pending_connectors, parent_node_id=None, component_path=[])


def _compile_part(root_id: str, part: Part, transform: Placement, source: SceneSource, options: SceneCompileOptions, definitions: dict[str, dict[str, Any]], nodes: list[dict[str, Any]], products: dict[str, dict[str, Any]], renderables: dict[str, _Renderable], appearances: dict[str, dict[str, Any]], pending_connectors: list[_PendingConnector], *, parent_node_id: str | None, component_path: list[str]) -> str:
    definition_id = f"definition/{root_id}/part/{_encode(part.part_id)}"
    normalized = _normalized_part(part)
    if definition_id not in definitions:
        appearance_id = _appearance(part.material, root_id, appearances)
        definitions[definition_id] = {"definition_id": definition_id, "kind": "part", "name": part.name, "source": _product_definition_source(root_id, part, source), "sdk_metadata": _metadata(part)}
        renderables[definition_id] = _make_renderable(definition_id, part.body, options, appearances, appearance_id=appearance_id)
        products[definition_id] = normalized
        pending_connectors.extend(_pending_connectors(root_id, "part", part, definition_id))
    elif canonical_json_bytes(products[definition_id]) != canonical_json_bytes(normalized):
        raise ValueError(f"conflicting Part definitions for {definition_id}")
    else:
        existing = renderables[definition_id]
        candidate = _make_renderable(
            definition_id,
            part.body,
            options,
            appearances,
            appearance_id=existing.appearance_id,
        )
        if candidate.render_mesh != existing.render_mesh or candidate.edge_mesh != existing.edge_mesh:
            raise ValueError(f"conflicting Part body geometry for {definition_id}")
    node_id = f"instance/{root_id}" + "".join(f"/{_encode(item)}" for item in component_path)
    nodes.append(_node(node_id, parent_node_id, len([n for n in nodes if n.get("parent_node_id") == parent_node_id]), definition_id, part.name, transform, {"kind": "product_occurrence", "root_id": root_id, "component_path": component_path}))
    return definition_id


def _compile_assembly(root_id: str, assembly: Assembly, transform: Placement, source: SceneSource, options: SceneCompileOptions, definitions: dict[str, dict[str, Any]], nodes: list[dict[str, Any]], products: dict[str, dict[str, Any]], renderables: dict[str, _Renderable], appearances: dict[str, dict[str, Any]], pending_connectors: list[_PendingConnector], *, parent_node_id: str | None, component_path: list[str]) -> str:
    definition_id = f"definition/{root_id}/assembly/{_encode(assembly.assembly_id)}"
    normalized = _normalized_assembly(assembly, root_id)
    if definition_id not in definitions:
        definitions[definition_id] = {"definition_id": definition_id, "kind": "assembly", "name": assembly.name, "source": _product_definition_source(root_id, assembly, source), "sdk_metadata": _metadata(assembly)}
        products[definition_id] = normalized
        pending_connectors.extend(_pending_connectors(root_id, "assembly", assembly, definition_id))
    elif canonical_json_bytes(products[definition_id]) != canonical_json_bytes(normalized):
        raise ValueError(f"conflicting Assembly definitions for {definition_id}")
    node_id = f"instance/{root_id}" + "".join(f"/{_encode(item)}" for item in component_path)
    nodes.append(_node(node_id, parent_node_id, len([n for n in nodes if n.get("parent_node_id") == parent_node_id]), definition_id, assembly.name, transform, {"kind": "product_occurrence", "root_id": root_id, "component_path": component_path}))
    for component in assembly.components:
        child_path = [*component_path, component.component_id]
        if isinstance(component.item, Part):
            _compile_part(root_id, component.item, component.placement, source, options, definitions, nodes, products, renderables, appearances, pending_connectors, parent_node_id=node_id, component_path=child_path)
        else:
            _compile_assembly(root_id, component.item, component.placement, source, options, definitions, nodes, products, renderables, appearances, pending_connectors, parent_node_id=node_id, component_path=child_path)
    return definition_id


def _make_renderable(definition_id: str, solid: Solid, options: SceneCompileOptions, appearances: dict[str, dict[str, Any]], *, appearance_id: str | None = None) -> _Renderable:
    face_ids = [f"entity/face/{index}" for index in range(len(solid._iter_faces()))]
    edge_ids = [f"entity/edge/{index}" for index in range(len(solid._iter_edges()))]
    render_mesh = build_render_mesh(solid, face_entity_ids=face_ids, linear_tolerance=options.linear_tolerance, angular_tolerance=options.angular_tolerance)
    edge_mesh = build_edge_mesh(
        solid,
        edge_entity_ids=edge_ids,
        linear_tolerance=options.linear_tolerance,
        angular_tolerance=options.angular_tolerance,
    )
    return _Renderable(solid, render_mesh, edge_mesh, appearance_id or _appearance(None, definition_id, appearances))


def _entity_asset(*, definition_id: str, definition_kind: str, geometry_asset_id: str, edge_asset_id: str, solid: Solid, render_mesh: RenderMesh, edge_mesh: RenderEdgeMesh, source: SceneSource, definition_source: Mapping[str, Any], ocp_version: str) -> dict[str, Any]:
    faces = solid._iter_faces()
    edges = solid._iter_edges()
    vertices = []
    seen_vertices: dict[str, Vertex] = {}
    for edge in edges:
        for vertex in edge._iter_vertices():
            seen_vertices.setdefault(vertex.topo_id, vertex)
    face_id = {face.topo_id: f"entity/face/{index}" for index, face in enumerate(faces)}
    edge_id = {edge.topo_id: f"entity/edge/{index}" for index, edge in enumerate(edges)}
    vertex_items = list(seen_vertices.values())
    vertex_id = {vertex.topo_id: f"entity/vertex/{index}" for index, vertex in enumerate(vertex_items)}
    entities: list[dict[str, Any]] = []
    entity_source = _entity_source(source, definition_source)
    solid_bounds = _bounds(solid_asset_bounds(solid))
    entities.append({"entity_id": "entity/solid/0", "kind": "solid", "parent_entity_ids": [], "child_entity_ids": sorted(face_id.values(), key=lambda item: item.encode("utf-8")), "source": entity_source, "geometry": {"type": "brep_solid"}, "properties": {"quality": "kernel_evaluated", "bounds": solid_bounds, "volume": solid.get_volume(), "surface_area": sum(face.get_area() for face in faces), "centroid": list(_vec(_center_of_mass(solid)))}, "sdk_connector_frame": None, "render_status": "rendered", "connector_binding_status": "not_applicable", "semantic_binding_ids": [], "evaluated_tags": [], "sdk_metadata": {}})
    for face in faces:
        entity_id = face_id[face.topo_id]
        normal = _vec(face.get_normal_at())
        center = _vec(face.get_center())
        geometry = _surface_geometry(face)
        connector_frame = _frame(center, normal)
        entities.append({"entity_id": entity_id, "kind": "face", "parent_entity_ids": ["entity/solid/0"], "child_entity_ids": sorted({edge_id[edge.topo_id] for edge in face._iter_edges()}, key=lambda item: item.encode("utf-8")), "source": entity_source, "geometry": geometry, "properties": {"quality": "kernel_evaluated", "bounds": _bounds(_shape_bounds(face)), "area": face.get_area(), "centroid": list(center), "orientation": _face_orientation(face)}, "sdk_connector_frame": _frame(center, normal), "render_status": "rendered", "connector_binding_status": "owner_not_part" if definition_kind != "part" else "source_not_model", "semantic_binding_ids": [], "evaluated_tags": sorted(face._list_tags(), key=lambda item: item.encode("utf-8")), "sdk_metadata": _metadata(face)})
        entities[-1]["sdk_connector_frame"] = connector_frame
        entities[-1]["connector_binding_status"] = _binding_status(source, definition_kind, connector_frame)
    for edge in edges:
        entity_id = edge_id[edge.topo_id]
        child_vertices = sorted(
            {vertex_id[vertex.topo_id] for vertex in edge._iter_vertices() if vertex.topo_id in vertex_id},
            key=lambda item: item.encode("utf-8"),
        )
        start, end = _edge_endpoints(edge)
        non_degenerate = start is not None and end is not None and start != end
        direction = _normalize(tuple(end[index] - start[index] for index in range(3))) if non_degenerate else (1.0, 0.0, 0.0)
        frame = _frame(_vec(edge.get_center()), direction) if non_degenerate else None
        entities.append({"entity_id": entity_id, "kind": "edge", "parent_entity_ids": sorted({face_id[face.topo_id] for face in edge.get_incident_faces() if face.topo_id in face_id}, key=lambda item: item.encode("utf-8")), "child_entity_ids": sorted(child_vertices, key=lambda item: item.encode("utf-8")), "source": entity_source, "geometry": _curve_geometry(edge), "properties": {"quality": "kernel_evaluated", "bounds": _bounds(_shape_bounds(edge)), "length": edge.get_length(), "centroid": list(_vec(edge.get_center()))}, "sdk_connector_frame": frame, "render_status": "degenerate" if entity_id in edge_mesh.degenerate_entity_ids else "rendered", "connector_binding_status": _binding_status(source, definition_kind, frame), "semantic_binding_ids": [], "evaluated_tags": sorted(edge._list_tags(), key=lambda item: item.encode("utf-8")), "sdk_metadata": _metadata(edge)})
    for vertex in vertex_items:
        point = _vec(vertex.get_coordinates())
        vertex_frame = {**_IDENTITY, "origin": list(point)}
        entities.append({"entity_id": vertex_id[vertex.topo_id], "kind": "vertex", "parent_entity_ids": sorted({edge_id[edge.topo_id] for edge in edges if any(child.topo_id == vertex.topo_id for child in edge._iter_vertices())}, key=lambda item: item.encode("utf-8")), "child_entity_ids": [], "source": entity_source, "geometry": {"type": "point", "position": list(point)}, "properties": {"quality": "kernel_evaluated", "bounds": {"min": list(point), "max": list(point)}, "position": list(point)}, "sdk_connector_frame": vertex_frame, "render_status": "rendered", "connector_binding_status": _binding_status(source, definition_kind, vertex_frame), "semantic_binding_ids": [], "evaluated_tags": sorted(vertex._list_tags(), key=lambda item: item.encode("utf-8")), "sdk_metadata": _metadata(vertex)})
    for entity in entities:
        entity["parent_entity_ids"] = sorted(entity["parent_entity_ids"], key=lambda item: item.encode("utf-8"))
        entity["child_entity_ids"] = sorted(entity["child_entity_ids"], key=lambda item: item.encode("utf-8"))
    return {"schema_version": "1.0", "definition_id": definition_id, "geometry_asset_id": geometry_asset_id, "edge_asset_id": edge_asset_id, "geometry_engine": {"name": "OpenCascade", "version": ocp_version, "profile": "ocp-evaluated-properties-1"}, "entities": sorted(entities, key=lambda item: item["entity_id"].encode("utf-8")), "face_groups": [{"group_id": index, "entity_id": group.entity_id, "mesh_index": 0, "primitive_index": 0, "first_index": group.first_index, "index_count": group.index_count} for index, group in enumerate(render_mesh.groups)], "edge_groups": [{"group_id": index, "entity_id": group.entity_id, "mesh_index": 0, "primitive_index": 0, "first_index": group.first_index, "index_count": group.index_count} for index, group in enumerate(edge_mesh.groups)]}


def _binding_status(source: SceneSource, definition_kind: str, frame: Mapping[str, Any] | None) -> str:
    if definition_kind != "part":
        return "owner_not_part"
    if source.kind != "model":
        return "source_not_model"
    return "frame_undefined" if frame is None else "supported"


def _coerce_source(
    source: SceneSource | None,
    roots: Sequence[SceneRoot],
    *,
    embed_source: bool,
) -> SceneSource:
    if isinstance(source, SceneSource):
        if embed_source or source.artifact_bytes is None:
            return source
        return SceneSource(
            kind=source.kind,
            source_id=source.source_id,
            graph_id=source.graph_id,
            artifact_hash=source.artifact_hash,
            format=source.format,
            definition_id=source.definition_id,
            revision=source.revision,
            _graph=source._graph,
        )
    return SceneSource(kind="manual", source_id=roots[0].root_id)


def _scene_source_record(source: SceneSource) -> dict[str, Any]:
    if source.kind == "manual":
        return {"kind": "manual", "source_id": source.source_id}
    if source.kind == "imported":
        return {
            "kind": "imported",
            "format": source.format,
            "artifact_hash": source.artifact_hash,
        }
    if source.kind in {"part_package", "assembly_package"}:
        return {
            "kind": source.kind,
            "definition_id": source.definition_id,
            "revision": source.revision,
            "artifact_hash": source.artifact_hash,
        }
    record = {
        "kind": "model",
        "graph_id": source.graph_id,
        "model_schema_version": "2.0",
        "artifact_hash": source.artifact_hash,
    }
    if source.artifact_bytes is not None:
        record.update(
            {
                "embedded_artifact_uri": "model/model.json",
                "embedded_artifact_byte_length": len(source.artifact_bytes),
                "source_files": [
                    {
                        "path": source_file.path,
                        "uri": source_file.uri,
                        "media_type": "text/x-python; charset=utf-8",
                        "byte_length": len(source_file.content),
                        "content_hash": source_file.content_hash,
                    }
                    for source_file in source._source_files
                ],
            }
        )
    return record


def _model_artifact_hash(model_json: str) -> str:
    return "sha256:" + hashlib.sha256(model_json.encode("utf-8")).hexdigest()


_SOURCE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*\.py$")


def _collect_source_files(graph: OperationGraph) -> tuple[_EmbeddedSourceFile, ...]:
    files: dict[str, _EmbeddedSourceFile] = {}
    casefold_paths: dict[str, str] = {}
    for node in graph.nodes:
        source = node.source
        if not isinstance(source, dict) or source.get("path_kind") != "project_relative":
            continue
        relative_path = source.get("path")
        local_path = source.get("local_path")
        if not isinstance(relative_path, str) or not isinstance(local_path, str):
            raise ValueError("project-relative operation source lacks a local path")
        if not _SOURCE_PATH_RE.fullmatch(relative_path):
            raise ValueError(f"operation source path is not archive-safe: {relative_path!r}")
        path = Path(local_path).resolve()
        if not path.is_file() or path.suffix != ".py":
            raise ValueError(f"operation source file is unavailable: {relative_path!r}")
        project_root = _source_project_root(path)
        if project_root is None or path.relative_to(project_root).as_posix() != relative_path:
            raise ValueError(f"operation source path no longer matches its project: {relative_path!r}")
        content = path.read_bytes()
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"operation source is not UTF-8: {relative_path!r}") from exc
        folded = relative_path.casefold()
        previous_path = casefold_paths.get(folded)
        if previous_path is not None and previous_path != relative_path:
            raise ValueError("operation source paths collide case-insensitively")
        casefold_paths[folded] = relative_path
        content_hash = _hash_bytes(content)
        record = _EmbeddedSourceFile(
            path=relative_path,
            uri=f"sources/{relative_path}",
            content_hash=content_hash,
            content=content,
        )
        previous = files.get(relative_path)
        if previous is not None and previous != record:
            raise ValueError(f"operation source path has conflicting contents: {relative_path!r}")
        files[relative_path] = record
    return tuple(files[path] for path in sorted(files, key=lambda item: item.encode("utf-8")))


def _source_project_root(path: Path) -> Path | None:
    for parent in (path.parent, *path.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def _graph_output_ref(value: Any, *, source: SceneSource) -> tuple[str, int]:
    getter = getattr(value, "_get_runtime", None)
    node = getter("graph.node") if callable(getter) else None
    if node is None or not getattr(node, "node_id", None):
        raise ValueError("model scene root must retain graph node ownership")
    graph = source._graph
    if graph is None:
        raise ValueError("model scene source requires GraphSession graph evidence")
    graph_id = getattr(node, "graph_id", None) or source.graph_id
    if graph_id != source.graph_id:
        raise ValueError("model scene root belongs to a different graph")
    if graph.get_node(node.node_id) is not node:
        raise ValueError("model scene root is not owned by the source model graph")
    output_slot = getter("graph.output_slot", 0) if callable(getter) else 0
    if (
        isinstance(output_slot, bool)
        or not isinstance(output_slot, int)
        or output_slot < 0
        or output_slot >= node.output_count
    ):
        raise ValueError("model scene root output slot is out of range")
    return str(node.node_id), int(output_slot)


def _product_definition_source(root_id: str, value: Part | Assembly, source: SceneSource) -> dict[str, Any]:
    semantic_type = "Part" if isinstance(value, Part) else "Assembly"
    semantic_id = value.part_id if isinstance(value, Part) else value.assembly_id
    if source.kind == "model":
        node_id, output_slot = _graph_output_ref(value, source=source)
        return {"kind": "product_model", "root_id": root_id, "semantic_type": semantic_type, "semantic_id": semantic_id, "graph_id": source.graph_id, "node_id": node_id, "output_slot": output_slot}
    if source.kind in {"part_package", "assembly_package"}:
        return {"kind": "product_package", "root_id": root_id, "semantic_type": semantic_type, "semantic_id": semantic_id, "package_kind": source.kind, "package_revision": source.revision}
    return {"kind": "product_manual", "root_id": root_id, "semantic_type": semantic_type, "semantic_id": semantic_id}

def _shape_definition_source(root_id: str, value: Solid | Compound, source: SceneSource) -> dict[str, Any]:
    if source.kind == "model":
        node_id, output_slot = _graph_output_ref(value, source=source)
        return {"kind": "model_output", "root_id": root_id, "graph_id": source.graph_id, "node_id": node_id, "output_slot": output_slot}
    return {"kind": "manual", "root_id": root_id, "source_id": source.source_id or root_id}


def _definition_id_for_shape(root_id: str, definition_source: Mapping[str, Any]) -> str:
    if definition_source["kind"] == "model_output":
        return f"definition/{root_id}/shape/model/{_encode(str(definition_source['graph_id']))}/{_encode(str(definition_source['node_id']))}/{definition_source['output_slot']}"
    return _shape_definition_id(root_id, str(definition_source["source_id"]))


def _entity_source(source: SceneSource, definition_source: Mapping[str, Any]) -> dict[str, Any]:
    if source.kind == "model":
        return {"kind": "model_output", "graph_id": definition_source["graph_id"], "node_id": definition_source["node_id"], "output_slot": definition_source["output_slot"]}
    if source.kind in {"part_package", "assembly_package"}:
        return {"kind": "package_geometry", "package_kind": source.kind, "package_revision": source.revision, "definition_id": definition_source["semantic_id"]}
    return {"kind": "unbound"}


def _generator() -> dict[str, Any]:
    version = importlib.metadata.version("simplecadapi")
    ocp = _ocp_version()
    identity = {"simplecadapi_version": version, "ocp_version": ocp, "platform": platform.platform()}
    return {"name": "simplecadapi", "simplecadapi_version": version, "ocp_version": ocp, "ocp_bindings_version": ocp, "python_abi": f"cp{sys.version_info.major}{sys.version_info.minor}", "platform_tag": platform.system().lower() + "-" + platform.machine().lower(), "toolchain_hash": canonical_json_hash(identity), "profile": "scene-1.0-ocp-glb-2"}


def _ocp_version() -> str:
    from simplecadapi._cpp import occt

    return str(occt.__version__)


def _appearance(material: Material | None, root_id: str, appearances: dict[str, dict[str, Any]]) -> str:
    draft = {"alpha_mode": "opaque", "base_color": [*(material.color if material and material.color else (0.72, 0.75, 0.78)), 1], "double_sided": False, "edge_color": [0.08, 0.09, 0.1, 1], "metallic": 0, "name": material.name if material else None, "roughness": 0.55, "sdk_metadata": {}, "source": {"kind": "product_material", "root_id": root_id, "material_id": material.material_id} if material else None}
    appearance_id = "appearance/evaluated/" + hashlib.sha256(canonical_json_bytes(draft)).hexdigest()
    appearances.setdefault(appearance_id, {"appearance_id": appearance_id, **draft})
    return appearance_id


def _pending_connectors(root_id: str, owner_kind: str, owner: Part | Assembly, definition_id: str) -> list[_PendingConnector]:
    connectors: Sequence[Connector | PublicConnectorRef]
    if isinstance(owner, Part):
        connectors = owner.connectors
    else:
        connectors = owner.public_connectors
    return [
        _PendingConnector(root_id, owner_kind, definition_id, owner, connector)
        for connector in connectors
    ]
def _finalize_connectors(
    pending: Sequence[_PendingConnector],
    *,
    definitions: Mapping[str, Mapping[str, Any]],
    entity_asset_ids: Mapping[str, str],
    source: SceneSource,
) -> list[dict[str, Any]]:
    pending_by_id: dict[str, _PendingConnector] = {}
    for item in pending:
        snapshot_id = _connector_snapshot_id(item)
        if snapshot_id in pending_by_id:
            raise ValueError(f"duplicate connector snapshot ID: {snapshot_id}")
        pending_by_id[snapshot_id] = item

    snapshots: dict[str, dict[str, Any]] = {}
    resolving: set[str] = set()

    def finalize(snapshot_id: str) -> dict[str, Any]:
        if snapshot_id in snapshots:
            return snapshots[snapshot_id]
        if snapshot_id in resolving:
            raise ValueError(f"cyclic public connector source: {snapshot_id}")
        item = pending_by_id.get(snapshot_id)
        if item is None:
            raise ValueError(f"public connector source is not compiled: {snapshot_id}")
        resolving.add(snapshot_id)
        connector = item.connector
        if isinstance(connector, PublicConnectorRef):
            if item.owner_kind != "assembly" or not isinstance(item.owner, Assembly):
                raise ValueError("public connectors require an Assembly owner")
            component = item.owner.get_component(connector.component_id)
            source_snapshot_id = _source_connector_snapshot_id(
                item.root_id, component.item, connector.connector_id
            )
            finalize(source_snapshot_id)
            payload = {
                "connector_snapshot_id": snapshot_id,
                "owner_definition_id": item.owner_definition_id,
                "connector_id": connector.public_connector_id,
                "name": connector.name,
                "anchor_kind": "public",
                "local_transform": component.placement.compose(
                    resolve_item_connector_placement(
                        component.item, connector.connector_id
                    )
                ).to_dict(),
                "source_connector_snapshot_id": source_snapshot_id,
                "source": _connector_source(source, item.owner, connector),
                "sdk_metadata": {},
            }
        elif connector.anchor_kind == "geometry":
            if not isinstance(item.owner, Part):
                raise ValueError("geometry connectors require a Part owner")
            target = _resolve_connector_target(item.owner.body, connector)
            target_kind = type(target).__name__.lower()
            if target_kind not in {"face", "edge", "vertex"}:
                raise ValueError("geometry connector target must be a face, edge, or vertex")
            entity_id = _entity_id_for_shape(item.owner.body, target)
            entity_asset_id = entity_asset_ids.get(item.owner_definition_id)
            if entity_asset_id is None:
                raise ValueError("geometry connector owner has no entity asset")
            payload = {
                "connector_snapshot_id": snapshot_id,
                "owner_definition_id": item.owner_definition_id,
                "connector_id": connector.connector_id,
                "name": connector.name,
                "anchor_kind": "geometry",
                "local_transform": resolve_connector_placement(connector).to_dict(),
                "target": {"entity_asset_id": entity_asset_id, "entity_id": entity_id},
                "source_connector_snapshot_id": None,
                "source": _connector_source(source, item.owner, connector),
                "sdk_metadata": {},
            }
        else:
            payload = {
                "connector_snapshot_id": snapshot_id,
                "owner_definition_id": item.owner_definition_id,
                "connector_id": connector.connector_id,
                "name": connector.name,
                "anchor_kind": "placement",
                "local_transform": resolve_connector_placement(connector).to_dict(),
                "source_connector_snapshot_id": None,
                "source": _connector_source(source, item.owner, connector),
                "sdk_metadata": {},
            }
        snapshots[snapshot_id] = payload
        resolving.remove(snapshot_id)
        return payload

    for snapshot_id in sorted(pending_by_id, key=lambda value: value.encode("utf-8")):
        finalize(snapshot_id)
    return sorted(
        snapshots.values(),
        key=lambda item: item["connector_snapshot_id"].encode("utf-8"),
    )


def _connector_snapshot_id(item: _PendingConnector) -> str:
    semantic_id = item.owner.assembly_id if isinstance(item.owner, Assembly) else item.owner.part_id
    connector_id = (
        item.connector.public_connector_id
        if isinstance(item.connector, PublicConnectorRef)
        else item.connector.connector_id
    )
    return (
        f"connector/{item.root_id}/{item.owner_kind}/"
        f"{_encode(semantic_id)}/{_encode(connector_id)}"
    )


def _source_connector_snapshot_id(
    root_id: str, item: Part | Assembly, connector_id: str
) -> str:
    owner_kind = "assembly" if isinstance(item, Assembly) else "part"
    semantic_id = item.assembly_id if isinstance(item, Assembly) else item.part_id
    return (
        f"connector/{root_id}/{owner_kind}/"
        f"{_encode(semantic_id)}/{_encode(connector_id)}"
    )


def _connector_source(
    source: SceneSource,
    owner: Part | Assembly,
    connector: Connector | PublicConnectorRef,
) -> dict[str, Any] | None:
    if source.kind == "manual":
        if not source.source_id:
            raise ValueError("manual connector source requires a source_id")
        return {"kind": "manual", "source_id": source.source_id}
    if source.kind == "imported":
        return None
    if source.kind in {"part_package", "assembly_package"}:
        semantic_id = owner.assembly_id if isinstance(owner, Assembly) else owner.part_id
        return {
            "kind": "product_package",
            "package_kind": source.kind,
            "package_revision": source.revision,
            "definition_id": semantic_id,
        }
    graph = source._graph
    if graph is None:
        raise ValueError("model connector source requires GraphSession graph evidence")
    owner_node_id, _output_slot = _graph_output_ref(owner, source=source)
    producer = _connector_producer(
        graph=graph,
        owner_node_id=owner_node_id,
        owner=owner,
        connector=connector,
    )
    return {
        "kind": "model_operation",
        "graph_id": source.graph_id,
        "node_id": producer.node_id,
        "output_slot": 0,
    }


def _connector_producer(
    *,
    graph: OperationGraph,
    owner_node_id: str,
    owner: Part | Assembly,
    connector: Connector | PublicConnectorRef,
) -> OperationNode:
    if isinstance(owner, Part):
        expected_op = "make_add_connector_rpart"
        semantic_type = "Part"
        semantic_id = owner.part_id
        semantic_id_param = "part_id"
        connector_param = "connector_id"
        connector_id = connector.connector_id
        expected_record = {"connector": connector.to_dict()}
    else:
        expected_op = "make_set_public_connector_rassembly"
        semantic_type = "Assembly"
        semantic_id = owner.assembly_id
        semantic_id_param = "assembly_id"
        connector_param = "public_connector_id"
        connector_id = connector.public_connector_id
        expected_record = {"public_connector": connector.to_dict()}

    matches: list[OperationNode] = []
    visited: set[str] = set()
    node = graph.get_node(owner_node_id)
    while node is not None and node.node_id not in visited:
        visited.add(node.node_id)
        delta = node.semantic_delta
        connector_record = delta.metadata if delta is not None else None
        modifies_owner = delta is not None and any(
            ref.entity_type == semantic_type and ref.entity_id == semantic_id
            for ref in delta.modified
        )
        if (
            node.op == expected_op
            and node.params.get(semantic_id_param) == semantic_id
            and node.params.get(connector_param) == connector_id
            and modifies_owner
            and connector_record == expected_record
        ):
            matches.append(node)
        if not node.inputs:
            break
        node = graph.get_node(node.inputs[0].node_id)

    if len(matches) != 1:
        raise ValueError(
            "connector source is not uniquely proven by the owner product lineage: "
            f"{semantic_type} {semantic_id!r} connector {connector_id!r}"
        )
    return matches[0]




def _resolve_connector_target(solid: Solid, connector: Connector) -> Face | Edge | Vertex:
    geometry_ref = connector.geometry_ref
    if geometry_ref is None:
        raise ValueError("geometry connector is missing its GeometryRef")
    candidates = _candidate_shapes_for_geo_selection(solid, geometry_ref.kind)
    if not candidates:
        raise ValueError(f"geometry connector found no {geometry_ref.kind} candidates")
    ranked = sorted(
        [
            (
                _geo_selector_score(candidate, geometry_ref.geo_selector),
                candidate,
            )
            for candidate in candidates
        ],
        key=lambda item: (item[0], item[1].topo_id.encode("utf-8")),
    )
    if ranked[0][0] > 1e-4:
        raise ValueError("geometry connector selector did not match a stable topology entity")
    if len(ranked) > 1 and ranked[1][0] <= 1e-4:
        raise ValueError("geometry connector selector is ambiguous")
    return ranked[0][1]  # type: ignore[return-value]


def _entity_id_for_shape(solid: Solid, shape: Face | Edge | Vertex) -> str:
    kind = type(shape).__name__.lower()
    if kind == "face":
        values = solid._iter_faces()
    elif kind == "edge":
        values = solid._iter_edges()
    else:
        seen: dict[str, Vertex] = {}
        for edge in solid._iter_edges():
            for vertex in edge._iter_vertices():
                seen.setdefault(vertex.topo_id, vertex)
        values = list(seen.values())
    try:
        ordinal = next(index for index, value in enumerate(values) if value.topo_id == shape.topo_id)
    except StopIteration as exc:
        raise ValueError(f"{kind} connector target is not part of the owner solid") from exc
    return f"entity/{kind}/{ordinal}"


def _reindex_node_orders(nodes: list[dict[str, Any]]) -> None:
    grouped: dict[str | None, list[dict[str, Any]]] = {}
    for node in nodes:
        grouped.setdefault(node.get("parent_node_id"), []).append(node)
    for parent, siblings in grouped.items():
        if parent is None:
            siblings.sort(key=lambda node: str(node["source"]["root_id"]).encode("utf-8"))
        else:
            siblings.sort(key=lambda node: tuple(str(part).encode("utf-8") for part in node["source"].get("component_path", [])))
        for order, node in enumerate(siblings):
            node["order"] = order


def _normalized_part(part: Part) -> dict[str, Any]:
    material = part.material
    material_value = None if material is None else {"material_id": material.material_id, "name": material.name, "density": material.density, "density_unit": material.density_unit, "color": list(material.color) if material.color is not None else None, "metadata": _metadata(material)}
    return {"kind": "part", "part_id": part.part_id, "body_source": {"kind": "manual", "source_id": part.part_id}, "name": part.name, "material": material_value, "connectors": [connector.to_dict() for connector in part.connectors], "metadata": _metadata(part)}


def _normalized_assembly(assembly: Assembly, root_id: str) -> dict[str, Any]:
    return {"kind": "assembly", "assembly_id": assembly.assembly_id, "name": assembly.name, "components": [{"component_id": component.component_id, "name": component.name, "definition_ref": f"definition/{root_id}/" + ("assembly/" if isinstance(component.item, Assembly) else "part/") + _encode(component.item.assembly_id if isinstance(component.item, Assembly) else component.item.part_id), "local_placement": component.placement.to_dict()} for component in assembly.components], "public_connectors": [connector.to_dict() for connector in assembly.public_connectors], "constraints": [constraint.to_dict() for constraint in assembly.constraints], "grounded_component_ids": sorted(assembly.grounded_component_ids, key=lambda item: item.encode("utf-8")), "metadata": _metadata(assembly)}


def _compound_solid(compound: Compound) -> Solid:
    solids = compound._iter_solids()
    if len(solids) != 1:
        raise ValueError("a standalone Compound must contain exactly one solid in the first compiler slice")
    return solids[0]


def _shape_definition_id(root_id: str, source_id: str) -> str:
    return f"definition/{root_id}/shape/manual/{_encode(source_id)}"


def _encode(value: str) -> str:
    return quote(str(value), safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _node(node_id: str, parent_node_id: str | None, order: int, definition_id: str, name: str | None, transform: Placement, source: dict[str, Any]) -> dict[str, Any]:
    return {"node_id": node_id, "parent_node_id": parent_node_id, "order": order, "definition_id": definition_id, "name": name, "transform": transform.to_dict(), "visible": True, "selectable": True, "appearance_override_id": None, "source": source, "sdk_metadata": {}}


def _hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _asset(asset_id: str, uri: str, byte_length: int, bounds: dict[str, Any], tessellation: dict[str, Any]) -> dict[str, Any]:
    return {"asset_id": asset_id, "uri": uri, "media_type": "model/gltf-binary", "byte_length": byte_length, "content_hash": asset_id, "scene_local_bounds": bounds, "asset_to_scene": ASSET_TO_SCENE, "tessellation": tessellation}


def _scene_bounds_from_glb(bounds: tuple[tuple[float, float, float], tuple[float, float, float]]) -> dict[str, list[float]]:
    minimum, maximum = bounds
    return {"min": [1000 * minimum[0], -1000 * maximum[2], 1000 * minimum[1]], "max": [1000 * maximum[0], -1000 * minimum[2], 1000 * maximum[1]]}


def _shape_bounds(shape: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xmin, ymin, zmin, xmax, ymax, zmax = shape._bounds()
    return ((xmin, ymin, zmin), (xmax, ymax, zmax))


def _bounds(value: tuple[tuple[float, float, float], tuple[float, float, float]]) -> dict[str, list[float]]:
    return {"min": [float(item) for item in value[0]], "max": [float(item) for item in value[1]]}


def _vec(value: Any) -> tuple[float, float, float]:
    if hasattr(value, "to_tuple"):
        return tuple(float(item) for item in value.to_tuple())
    return tuple(float(item) for item in value)


def _normalize(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = sum(item * item for item in value) ** 0.5
    if length == 0:
        raise ValueError("cannot normalize zero vector")
    return tuple(item / length for item in value)


def _frame(origin: tuple[float, float, float], z_axis: tuple[float, float, float]) -> dict[str, list[float]]:
    z = _normalize(z_axis)
    seeds = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    seed = min(seeds, key=lambda candidate: abs(sum(a * b for a, b in zip(z, candidate))))
    dot = sum(a * b for a, b in zip(z, seed))
    x = _normalize(tuple(seed[index] - z[index] * dot for index in range(3)))
    y = _normalize((z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]))
    return {"origin": list(origin), "x_axis": list(x), "y_axis": list(y), "z_axis": list(z)}


def _edge_endpoints(edge: Edge) -> tuple[tuple[float, float, float] | None, tuple[float, float, float] | None]:
    try:
        return _vec(edge.get_start_vertex().get_coordinates()), _vec(edge.get_end_vertex().get_coordinates())
    except Exception:
        return None, None


def _center_of_mass(shape: Any) -> Any:
    center = shape.get_center()
    return (center.x, center.y, center.z)


def _face_orientation(face: Any) -> str:
    return face._orientation()


def _surface_geometry(face: Face) -> dict[str, Any]:
    kind = face._geom_type()
    center = _vec(face.get_center())
    normal = _vec(face.get_normal_at())
    if kind == "PLANE":
        return {"type": "plane", "origin": list(center), "normal": list(normal), "x_direction": _frame(center, normal)["x_axis"]}
    parameters = face._geometry()
    names = {"CYLINDER": "cylinder", "SPHERE": "sphere", "TORUS": "torus"}
    if kind in names and parameters is not None:
        return {"type": names[kind], **{key: list(value) if isinstance(value, tuple) else value for key, value in parameters.items()}}
    return {"type": "other_surface", "engine_type": kind}


def _curve_geometry(edge: Edge) -> dict[str, Any]:
    kind = edge._geom_type()
    parameters = edge._geometry()
    names = {"LINE": "line", "CIRCLE": "circle", "ELLIPSE": "ellipse", "BSPLINE": "bspline_curve"}
    if kind in names and parameters is not None:
        return {"type": names[kind], **{key: list(value) if isinstance(value, tuple) else value for key, value in parameters.items()}}
    return {"type": "other_curve", "engine_type": kind}


def _metadata(value: Any) -> dict[str, Any]:
    metadata = getattr(value, "_metadata", {})
    if not isinstance(metadata, dict):
        return {}
    excluded = {"graph", "topo_ref", "track", "source_sketch", "sketch_solve", "sketch_promotion"}
    return {key: _json_value(item) for key, item in metadata.items() if key not in excluded and not key.startswith("_")}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise ValueError(f"unsupported metadata value: {type(value).__name__}")


def _freeze_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_mapping(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_mapping(item) for item in value)
    return value


def _thaw_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_mapping(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_mapping(item) for item in value]
    return value


__all__ = ["CompiledScenePackage", "SceneCompileOptions", "SceneRoot", "SceneSource", "compile_scene", "export_scene"]

"""Scene 2.0 synthesis for raw STEP targets (reverse-engineering original side).

The synthesized projection mirrors what ``simplecadapi.scene.product_scene``
emits into ``.scadpkg`` packages, so the browser re-mode reuses one GLB +
entity-sidecar assembly path for both the original STEP side and the rebuilt
package side.

Entity ids follow the scene shape ``entity/<kind>/<index>``; each record's
``topo_id`` carries the canonical ``BRepModel`` id (``face:3``) accepted by
the inspection endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from OCP.BRep import BRep_Tool

from simplecadapi._internal.mesh import (
    DEFAULT_ANGULAR_TOLERANCE,
    DEFAULT_LINEAR_TOLERANCE,
)
from simplecadapi.artifacts.canonical import sha256_bytes
from simplecadapi.core import Solid
from simplecadapi.inspect.brep import BRepModel, load_step_rbrepmodel
from simplecadapi.kernel.ocp_properties import center_of_mass
from simplecadapi.scene.canonical import canonical_json_bytes
from simplecadapi.scene.compiler import _curve_geometry, _surface_geometry
from simplecadapi.scene.glb_writer import write_line_glb, write_triangle_glb
from simplecadapi.scene.render_mesh import build_edge_mesh, build_render_mesh

# Edges are cheap lines but carry the perceived curvature of the model, so they
# tessellate tighter than faces (defaults: 0.35 mm / 0.22 rad).
EDGE_LINEAR_TOLERANCE = 0.1
EDGE_ANGULAR_TOLERANCE = 0.1

_IDENTITY_TRANSFORM: dict[str, Any] = {
    "origin": [0.0, 0.0, 0.0],
    "x_axis": [1.0, 0.0, 0.0],
    "y_axis": [0.0, 1.0, 0.0],
    "z_axis": [0.0, 0.0, 1.0],
}

_PLACEHOLDER_CAMERA: dict[str, Any] = {
    "target": [0.0, 0.0, 0.0],
    "position": [0.0, 0.0, 1.0],
    "up": [0.0, 0.0, 1.0],
    "near": 0.01,
    "far": 1000.0,
    "fit_mode": "bounds",
    "margin": 0.08,
}


@dataclass
class StepScene:
    """Synthesized scene plus the BRepModel backing the inspection endpoints."""

    manifest: dict[str, Any]
    files: dict[str, bytes]
    summary: dict[str, Any]
    model: BRepModel
    # canonical entity id -> {"kind", "centroid"/"position", "normal"?} in CAD mm
    anchors: dict[str, dict[str, Any]] = field(default_factory=dict)


_scene_cache: dict[str, tuple[float, StepScene]] = {}


def _scene_entity_id(kind: str, canonical_id: str) -> str:
    return f"entity/{kind}/{canonical_id.split(':', 1)[1]}"


def _vec3(value: Any) -> list[float]:
    return [float(item) for item in value]


def _face_anchor(face: Any) -> dict[str, Any]:
    return {
        "kind": "face",
        "centroid": _vec3(face.get_center()),
        "normal": _vec3(face.get_normal_at()),
    }


def _asset_record(payload: bytes, *, uri: str, media_type: str) -> dict[str, Any]:
    digest = sha256_bytes(payload)
    return {
        "asset_id": digest,
        "uri": uri,
        "media_type": media_type,
        "sha256": digest,
        "byte_length": len(payload),
    }


def build_step_scene(step_path: str | Path) -> StepScene:
    """Build (and cache) the synthesized scene for one STEP file."""

    resolved = Path(step_path).resolve()
    stamp = resolved.stat().st_mtime
    cached = _scene_cache.get(str(resolved))
    if cached and cached[0] == stamp:
        return cached[1]

    model = load_step_rbrepmodel(resolved)
    if not model.bodies:
        raise ValueError(
            "re-mode scene synthesis requires solid bodies; "
            "open-shell STEP targets are not supported yet"
        )

    geometry_assets: list[dict[str, Any]] = []
    entity_assets: list[dict[str, Any]] = []
    definitions: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    anchors: dict[str, dict[str, Any]] = {}

    for body_index, body in enumerate(model.bodies):
        solid = Solid(body)
        faces = solid._iter_faces()
        face_ids = [model.id_for_shape("face", face.wrapped) for face in faces]
        edges = solid._iter_edges()
        edge_ids = [model.id_for_shape("edge", edge.wrapped) for edge in edges]
        vertices_by_id: dict[str, Any] = {}
        for edge in edges:
            for vertex in edge._iter_vertices():
                vertices_by_id.setdefault(vertex.topo_id, vertex)
        vertices = list(vertices_by_id.values())
        vertex_ids = [
            model.id_for_shape("vertex", vertex.wrapped) for vertex in vertices
        ]

        scene_face_ids = [_scene_entity_id("face", item) for item in face_ids]
        scene_edge_ids = [_scene_entity_id("edge", item) for item in edge_ids]
        scene_vertex_ids = [
            _scene_entity_id("vertex", item) for item in vertex_ids
        ]
        render_mesh = build_render_mesh(
            solid,
            face_entity_ids=scene_face_ids,
            linear_tolerance=DEFAULT_LINEAR_TOLERANCE,
            angular_tolerance=DEFAULT_ANGULAR_TOLERANCE,
        )
        edge_mesh = build_edge_mesh(
            solid,
            edge_entity_ids=scene_edge_ids,
            linear_tolerance=EDGE_LINEAR_TOLERANCE,
            angular_tolerance=EDGE_ANGULAR_TOLERANCE,
        )
        triangle_glb = write_triangle_glb(render_mesh)
        line_glb = write_line_glb(edge_mesh)
        geometry_hash = sha256_bytes(triangle_glb)
        edge_hash = sha256_bytes(line_glb)
        geometry_uri = f"geometry/sha256-{geometry_hash.removeprefix('sha256:')}.glb"
        edge_uri = f"geometry/sha256-{edge_hash.removeprefix('sha256:')}.lines.glb"
        geometry_assets.extend(
            [
                _asset_record(triangle_glb, uri=geometry_uri, media_type="model/gltf-binary"),
                _asset_record(line_glb, uri=edge_uri, media_type="model/gltf-binary"),
            ]
        )

        solid_canonical = model.id_for_shape("body", body)
        solid_scene_id = f"entity/solid/{body_index}"
        entities: list[dict[str, Any]] = [
            {
                "entity_id": solid_scene_id,
                "kind": "solid",
                "topo_id": solid_canonical,
                "parent_entity_ids": [],
                "child_entity_ids": sorted(scene_face_ids),
                "source": {"kind": "imported_step", "topo_id": solid_canonical},
                "geometry": {"type": "brep_solid"},
                "properties": {
                    "volume": solid.get_volume(),
                    "surface_area": sum(face.get_area() for face in faces),
                    "centroid": _vec3(center_of_mass(solid.wrapped)),
                },
                "tags": [],
            }
        ]
        for face, canonical_id, scene_id in zip(faces, face_ids, scene_face_ids):
            anchors[canonical_id] = _face_anchor(face)
            entities.append(
                {
                    "entity_id": scene_id,
                    "kind": "face",
                    "topo_id": canonical_id,
                    "parent_entity_ids": [solid_scene_id],
                    "child_entity_ids": [],
                    "source": {"kind": "imported_step", "topo_id": canonical_id},
                    "geometry": _surface_geometry(face),
                    "properties": {
                        "area": face.get_area(),
                        "centroid": _vec3(face.get_center()),
                        "normal": _vec3(face.get_normal_at()),
                    },
                    "tags": [],
                }
            )
        for edge, canonical_id, scene_id in zip(edges, edge_ids, scene_edge_ids):
            # On a solid every edge touches >= 2 distinct faces; fewer means a
            # seam (the doubled edge of a closed surface, e.g. a cylinder wall).
            # Pro CAD viewers hide both seams and degenerate edges by default.
            incident_faces = {face.topo_id for face in edge.get_incident_faces()}
            entities.append(
                {
                    "entity_id": scene_id,
                    "kind": "edge",
                    "topo_id": canonical_id,
                    "parent_entity_ids": [],
                    "child_entity_ids": [],
                    "source": {"kind": "imported_step", "topo_id": canonical_id},
                    "geometry": _curve_geometry(edge),
                    "properties": {
                        "length": edge.get_length(),
                        "centroid": _vec3(edge.get_center()),
                        "seam": len(incident_faces) < 2,
                        "degenerate": BRep_Tool.Degenerated_s(edge.wrapped),
                    },
                    "tags": [],
                }
            )
        for vertex, canonical_id, scene_id in zip(vertices, vertex_ids, scene_vertex_ids):
            position = _vec3(vertex.get_coordinates())
            anchors[canonical_id] = {"kind": "vertex", "position": position}
            entities.append(
                {
                    "entity_id": scene_id,
                    "kind": "vertex",
                    "topo_id": canonical_id,
                    "parent_entity_ids": [],
                    "child_entity_ids": [],
                    "source": {"kind": "imported_step", "topo_id": canonical_id},
                    "geometry": {"type": "point", "position": position},
                    "properties": {"position": position},
                    "tags": [],
                }
            )

        entity_document = {
            "schema_version": "2.0",
            "definition_id": f"step-body-{body_index}",
            "geometry_asset_id": geometry_hash,
            "edge_asset_id": edge_hash,
            "entities": entities,
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
        entity_assets.append(
            _asset_record(
                entity_bytes,
                uri=entity_uri,
                media_type="application/vnd.simplecad.entities+json",
            )
        )
        files[geometry_uri] = triangle_glb
        files[edge_uri] = line_glb
        files[entity_uri] = entity_bytes

        definition_id = f"step-body-{body_index}"
        definitions.append(
            {
                "definition_id": definition_id,
                "definition_kind": "single_solid",
                "revision": "1",
                "content_hash": "",
                "product_asset_id": "",
                "feature_graph_asset_id": "",
            }
        )
        nodes.append(
            {
                "node_id": f"node/body-{body_index}",
                "parent_node_id": None,
                "display_name": f"body {body_index}",
                "node_kind": "solid",
                "definition_id": definition_id,
                "definition_kind": "single_solid",
                "component_id": None,
                "instance_id": None,
                "transform": _IDENTITY_TRANSFORM,
                "geometry_asset_id": geometry_hash,
                "entity_asset_id": entity_hash,
                "material_id": None,
                "properties": {},
            }
        )

    manifest = {
        "schema_version": "2.0",
        "scene_id": resolved.stem,
        "revision": "1",
        "units": "mm",
        "roots": [node["node_id"] for node in nodes],
        "definitions": definitions,
        "geometry_assets": sorted(geometry_assets, key=lambda item: item["asset_id"]),
        "entity_assets": sorted(entity_assets, key=lambda item: item["asset_id"]),
        "product_assets": [],
        "feature_graph_assets": [],
        "source_assets": [],
        "nodes": nodes,
        "connectors": [],
        "joints": [],
        "feature_index": [],
        "source_index": [],
        "connector_index": [],
        "joint_index": [],
        "camera": _PLACEHOLDER_CAMERA,
        "extensions": {"re_mode": {"target_step": str(resolved)}},
    }
    files["scene.json"] = canonical_json_bytes(manifest)

    scene = StepScene(
        manifest=manifest,
        files=files,
        summary=model.summary(),
        model=model,
        anchors=anchors,
    )
    _scene_cache[str(resolved)] = (stamp, scene)
    return scene


__all__ = ["StepScene", "build_step_scene"]

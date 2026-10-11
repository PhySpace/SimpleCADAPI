"""A preview of a product for a viewer that is being edited with.

A product package (:mod:`.product_scene`) is the durable, exchangeable form of
a product: definitions, BREP, feature graph, topology snapshot, hashed and
validated GLB assets and entity sidecars.  Making one takes seconds, nearly all
of it for what a viewer of a model under edit never reads.  This module makes the
other thing a viewer needs, straight from the solids in memory:

* the triangles of each part (positions, normals, indices), the line segments of
  its edges and the positions of its vertices, with the index range each face and
  edge occupies, so a viewer can highlight and pick them;
* the parts of an assembly, each once, and where each of its instances stands;
* :func:`entity_info`, the geometric properties of one picked face, edge, vertex
  or solid, worked out on demand (about 0.05 ms for a face).

The geometry of a part is derived data: it is kept per (BREP content, tolerance),
so a part that did not change costs nothing to preview again, even if its object
was rebuilt (a notebook cell ran again, a cache restored it).  Nothing here is
hashed canonically, validated or written as a document.

Coordinates are glTF's (metres, +Y up: CAD x, z, -y / 1000), as in the package's
GLB assets, so a viewer built for those uses the arrays as they are.
"""

from __future__ import annotations

import hashlib
import json
import struct
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np

from .._internal.mesh import DEFAULT_ANGULAR_TOLERANCE, DEFAULT_LINEAR_TOLERANCE, cached_mesh
from ..artifacts.brep import _bintools_bytes
from ..core import Solid
from ..kernel.ocp_properties import center_of_mass
from ..product.assembly import Assembly
from ..product.part import Part
from ..product.placement import Placement, identity_placement
from .compiler import (
    _curve_geometry,
    _edge_endpoints,
    _frame,
    _normalize,
    _orientation,
    _shape_bounds,
    _surface_geometry,
    _vec,
)
from .compiler import _bounds as _bounds_document
from .render_mesh import build_edge_mesh, solid_asset_bounds

PREVIEW_SCHEMA = "sca-preview-1"
MAGIC = b"SCAPREV1"
_CACHE_PARTS = 96


class PreviewError(ValueError):
    """The product cannot be previewed (it has no solid to draw)."""


@dataclass(frozen=True)
class PartPreview:
    """Everything a viewer draws of one solid; immutable and independent of its object."""

    key: str
    positions: np.ndarray  # (n, 3) float32, glTF metres
    normals: np.ndarray  # (n, 3) float32
    indices: np.ndarray  # (3 * triangles,) uint32
    face_groups: tuple[tuple[str, int, int], ...]  # (face topo id, first index, index count)
    edge_positions: np.ndarray  # (k, 3) float32
    edge_indices: np.ndarray  # (2 * segments,) uint32
    edge_groups: tuple[tuple[str, int, int], ...]
    vertex_positions: np.ndarray  # (v, 3) float32
    vertex_ids: tuple[str, ...]
    solid_topo_id: str
    triangle_count: int


@dataclass(frozen=True)
class PreviewNode:
    node_id: str
    part_key: str
    definition_id: str
    display_name: str
    placement: Placement  # CAD space, millimetres, relative to the product


@dataclass
class PreviewScene:
    parts: dict[str, PartPreview]
    nodes: list[PreviewNode]
    solids: dict[str, Solid]
    """The solid behind each part key, for :func:`entity_info` (not serialized)."""
    definitions: dict[str, str]
    """The definition id each part key belongs to."""


# -- the per-part cache --------------------------------------------------------------

_parts: OrderedDict[str, PartPreview] = OrderedDict()
_parts_lock = threading.Lock()


def _remember(preview: PartPreview) -> PartPreview:
    with _parts_lock:
        _parts[preview.key] = preview
        _parts.move_to_end(preview.key)
        while len(_parts) > _CACHE_PARTS:
            _parts.popitem(last=False)
    return preview


def _recall(key: str) -> PartPreview | None:
    with _parts_lock:
        preview = _parts.get(key)
        if preview is not None:
            _parts.move_to_end(key)
        return preview


def clear_preview_cache() -> None:
    with _parts_lock:
        _parts.clear()


def part_key(solid: Solid, linear_tolerance: float, angular_tolerance: float) -> str:
    """A key for the geometry of *solid* at a tolerance: its BREP content, not its identity.

    Remembered on the solid, so asking again about the same object is free.
    """
    tolerance = f"{float(linear_tolerance).hex()}:{float(angular_tolerance).hex()}"
    remembered = solid._get_runtime("preview.key", None)
    if isinstance(remembered, tuple) and remembered[0] == tolerance:
        return remembered[1]
    digest = hashlib.sha256(_bintools_bytes(solid.wrapped)).hexdigest()[:24]
    key = f"{digest}-{hashlib.sha256(tolerance.encode()).hexdigest()[:6]}"
    solid._set_runtime("preview.key", (tolerance, key))
    return key


# -- one solid -----------------------------------------------------------------------


def preview_solid(
    solid: Solid,
    *,
    linear_tolerance: float = DEFAULT_LINEAR_TOLERANCE,
    angular_tolerance: float = DEFAULT_ANGULAR_TOLERANCE,
) -> PartPreview:
    """The preview geometry of *solid*, from the cache if its content was seen at this tolerance."""

    key = part_key(solid, linear_tolerance, angular_tolerance)
    known = _recall(key)
    if known is not None:
        return known
    mesh = cached_mesh(solid, linear_tolerance=linear_tolerance, angular_tolerance=angular_tolerance)
    if mesh is None:
        raise PreviewError("the solid has no mesh")
    triangles = np.asarray(mesh.triangles, dtype=np.int64)
    corner_normals = np.asarray(mesh.corner_normals, dtype=np.float64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    positions, normals, indices = _vertex_buffers(vertices, triangles, corner_normals)
    face_groups = tuple(
        (str(item.source_topo_id), item.start * 3, item.count * 3)
        for item in mesh.face_triangle_ranges
        if item.count > 0
    )

    edges = solid._iter_edges()
    edge_mesh = build_edge_mesh(
        solid,
        edge_entity_ids=[edge.topo_id for edge in edges],
        linear_tolerance=linear_tolerance,
        angular_tolerance=angular_tolerance,
    )
    edge_positions = np.asarray(edge_mesh.positions, dtype=np.float32).reshape((-1, 3))
    edge_indices = np.asarray(edge_mesh.indices, dtype=np.uint32)
    edge_groups = tuple((group.entity_id, group.first_index, group.index_count) for group in edge_mesh.groups)

    unique: dict[str, Any] = {}
    for edge in edges:
        for vertex in edge._iter_vertices():
            unique.setdefault(vertex.topo_id, vertex)
    vertex_ids = tuple(unique)
    vertex_positions = _gltf(np.asarray([list(_vec(unique[i].get_coordinates())) for i in vertex_ids], dtype=np.float64).reshape((-1, 3)))

    return _remember(
        PartPreview(
            key=key,
            positions=positions,
            normals=normals,
            indices=indices,
            face_groups=face_groups,
            edge_positions=edge_positions,
            edge_indices=edge_indices,
            edge_groups=edge_groups,
            vertex_positions=vertex_positions.astype(np.float32),
            vertex_ids=vertex_ids,
            solid_topo_id=str(solid.topo_id),
            triangle_count=int(len(triangles)),
        )
    )


def _gltf(points: np.ndarray) -> np.ndarray:
    """CAD millimetres (x, y, z) to glTF metres (x, z, -y)."""
    return np.stack([points[:, 0], points[:, 2], -points[:, 1]], axis=1) / 1000.0


def _gltf_direction(vectors: np.ndarray) -> np.ndarray:
    return np.stack([vectors[:, 0], vectors[:, 2], -vectors[:, 1]], axis=1)


def _vertex_buffers(
    vertices: np.ndarray, triangles: np.ndarray, corner_normals: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-vertex position and normal buffers and the index buffer.

    The mesh keeps a normal for each triangle corner.  Where every corner that
    uses a vertex agrees on it (the usual case: a face's vertices are its own)
    the vertex keeps that normal; otherwise vertices are split by (position,
    normal).
    """
    if len(triangles) == 0:
        empty = np.zeros((0, 3), dtype=np.float32)
        return empty, empty, np.zeros(0, dtype=np.uint32)
    flat = triangles.reshape(-1)
    corners = corner_normals.reshape(-1, 3)
    per_vertex = np.zeros((len(vertices), 3), dtype=np.float64)
    per_vertex[flat] = corners
    if np.abs(per_vertex[flat] - corners).max() <= 1e-9:
        return (
            _gltf(vertices).astype(np.float32),
            _gltf_direction(per_vertex).astype(np.float32),
            flat.astype(np.uint32),
        )
    combined = np.concatenate([vertices[flat], corners], axis=1)
    unique, inverse = np.unique(combined, axis=0, return_inverse=True)
    return (
        _gltf(unique[:, :3]).astype(np.float32),
        _gltf_direction(unique[:, 3:]).astype(np.float32),
        inverse.reshape(-1).astype(np.uint32),
    )


# -- a product -----------------------------------------------------------------------


def compile_preview(
    product: Part | Assembly,
    *,
    linear_tolerance: float = DEFAULT_LINEAR_TOLERANCE,
    angular_tolerance: float = DEFAULT_ANGULAR_TOLERANCE,
) -> PreviewScene:
    """Preview *product*: every part once, every instance with its placement."""

    parts: dict[str, PartPreview] = {}
    solids: dict[str, Solid] = {}
    definitions: dict[str, str] = {}
    nodes: list[PreviewNode] = []

    def add(part: Part, path: tuple[str, ...], placement: Placement, name: str) -> None:
        body = part.body
        if not isinstance(body, Solid):
            raise PreviewError(f"part {part.part_id!r} has no solid body")
        preview = preview_solid(body, linear_tolerance=linear_tolerance, angular_tolerance=angular_tolerance)
        parts[preview.key] = preview
        solids.setdefault(preview.key, body)
        definitions.setdefault(preview.key, part.part_id)
        nodes.append(
            PreviewNode(
                node_id="node/" + "/".join(path),
                part_key=preview.key,
                definition_id=part.part_id,
                display_name=name,
                placement=placement,
            )
        )

    def visit(item: Part | Assembly, path: tuple[str, ...], placement: Placement, name: str) -> None:
        if isinstance(item, Part):
            add(item, path, placement, name)
            return
        for component in item.components:
            visit(
                component.item,
                path + (component.component_id,),
                placement.compose(component.placement),
                component.name or component.component_id,
            )

    root_id = product.part_id if isinstance(product, Part) else product.assembly_id
    visit(product, (root_id,), identity_placement(), root_id)
    if not nodes:
        raise PreviewError("the product has nothing to draw")
    return PreviewScene(parts=parts, nodes=nodes, solids=solids, definitions=definitions)


# -- the wire format -----------------------------------------------------------------


def encode_preview(scene: PreviewScene) -> bytes:
    """Serialize *scene*: ``SCAPREV1``, a header length, a JSON header, then the arrays.

    The header lists the parts (each array as an ``offset`` and ``count`` into the
    data that follows), the face and edge groups, and the nodes.  Arrays are
    little-endian ``float32`` (positions, normals) and ``uint32`` (indices).
    """
    chunks: list[bytes] = []
    cursor = 0

    def array(values: np.ndarray, dtype: str) -> dict[str, int]:
        nonlocal cursor
        data = np.ascontiguousarray(values, dtype=dtype).tobytes()
        entry = {"offset": cursor, "count": int(values.size)}
        chunks.append(data)
        cursor += len(data)
        return entry

    parts: list[dict[str, Any]] = []
    for key, part in scene.parts.items():
        definition = scene.definitions[key]
        prefix = f"entity/{definition}/"
        parts.append(
            {
                "key": key,
                "definition_id": definition,
                "positions": array(part.positions, "<f4"),
                "normals": array(part.normals, "<f4"),
                "indices": array(part.indices, "<u4"),
                "edge_positions": array(part.edge_positions, "<f4"),
                "edge_indices": array(part.edge_indices, "<u4"),
                "vertex_positions": array(part.vertex_positions, "<f4"),
                "vertex_ids": [f"{prefix}vertex/{topo}" for topo in part.vertex_ids],
                "face_groups": [
                    {"entity_id": f"{prefix}face/{topo}", "first_index": first, "index_count": count}
                    for topo, first, count in part.face_groups
                ],
                "edge_groups": [
                    {"entity_id": f"{prefix}edge/{topo}", "first_index": first, "index_count": count}
                    for topo, first, count in part.edge_groups
                ],
                "solid_entity_id": f"{prefix}solid/{part.solid_topo_id}",
                "triangles": part.triangle_count,
            }
        )
    header = {
        "schema": PREVIEW_SCHEMA,
        "parts": parts,
        "nodes": [
            {
                "node_id": node.node_id,
                "part": node.part_key,
                "definition_id": node.definition_id,
                "display_name": node.display_name,
                "transform": {
                    "origin": list(node.placement.origin),
                    "x_axis": list(node.placement.x_axis),
                    "y_axis": list(node.placement.y_axis),
                    "z_axis": list(node.placement.z_axis),
                },
            }
            for node in scene.nodes
        ],
    }
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 8)
    return MAGIC + struct.pack("<I", len(encoded)) + b"\0\0\0\0" + encoded + b"".join(chunks)


def decode_preview_header(data: bytes) -> dict[str, Any]:
    """The header of an encoded preview (the arrays follow it)."""
    if not data.startswith(MAGIC):
        raise PreviewError("not a preview")
    (length,) = struct.unpack_from("<I", data, len(MAGIC))
    start = len(MAGIC) + 8
    return json.loads(data[start : start + length])


# -- one picked entity ---------------------------------------------------------------


def entity_info(scene: PreviewScene, entity_id: str) -> dict[str, Any] | None:
    """The geometric properties of the entity *entity_id* of a part of *scene*.

    ``entity/<definition>/<kind>/<topo id>``; returns what the package's entity
    sidecar holds for it (``properties``, ``geometry``, ``tags``) except the
    ``source`` links into the feature graph, or ``None`` if there is no such entity.
    """
    _, _, rest = entity_id.partition("entity/")
    definition, _, tail = rest.partition("/")
    kind, _, topo_id = tail.partition("/")
    key = next((k for k, d in scene.definitions.items() if d == definition), None)
    if key is None:
        return None
    solid = scene.solids[key]
    if kind == "solid":
        return {
            "entity_id": entity_id,
            "kind": "solid",
            "topo_id": solid.topo_id,
            "geometry": {"type": "brep_solid"},
            "properties": {
                "bounds": _bounds_document(solid_asset_bounds(solid)),
                "volume": solid.get_volume(),
                "surface_area": sum(face.get_area() for face in solid._iter_faces()),
                "centroid": list(_vec(center_of_mass(solid.wrapped))),
            },
            "tags": sorted(solid._list_tags()),
        }
    if kind == "face":
        face = next((f for f in solid._iter_faces() if f.topo_id == topo_id), None)
        if face is None:
            return None
        center = _vec(face.get_center())
        return {
            "entity_id": entity_id,
            "kind": "face",
            "topo_id": topo_id,
            "geometry": _surface_geometry(face),
            "properties": {
                "bounds": _bounds_document(_shape_bounds(face)),
                "area": face.get_area(),
                "centroid": list(center),
                "orientation": _orientation(face.wrapped.Orientation()),
                "connector_frame": _frame(center, _vec(face.get_normal_at())),
            },
            "tags": sorted(face._list_tags()),
        }
    if kind == "edge":
        edge = next((e for e in solid._iter_edges() if e.topo_id == topo_id), None)
        if edge is None:
            return None
        start, end = _edge_endpoints(edge)
        frame = None
        if start is not None and end is not None and start != end:
            direction = _normalize(tuple(end[i] - start[i] for i in range(3)))
            frame = _frame(_vec(edge.get_center()), direction)
        return {
            "entity_id": entity_id,
            "kind": "edge",
            "topo_id": topo_id,
            "geometry": _curve_geometry(edge),
            "properties": {
                "bounds": _bounds_document(_shape_bounds(edge)),
                "length": edge.get_length(),
                "centroid": list(_vec(edge.get_center())),
                "connector_frame": frame,
            },
            "tags": sorted(edge._list_tags()),
        }
    if kind == "vertex":
        for edge in solid._iter_edges():
            for vertex in edge._iter_vertices():
                if vertex.topo_id == topo_id:
                    point = list(_vec(vertex.get_coordinates()))
                    return {
                        "entity_id": entity_id,
                        "kind": "vertex",
                        "topo_id": topo_id,
                        "geometry": {"type": "point", "position": point},
                        "properties": {"bounds": {"min": point, "max": point}, "position": point},
                        "tags": sorted(vertex._list_tags()),
                    }
        return None
    return None


__all__ = [
    "MAGIC",
    "PREVIEW_SCHEMA",
    "PartPreview",
    "PreviewError",
    "PreviewNode",
    "PreviewScene",
    "clear_preview_cache",
    "compile_preview",
    "decode_preview_header",
    "encode_preview",
    "entity_info",
    "part_key",
    "preview_solid",
]

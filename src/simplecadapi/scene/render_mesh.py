"""Deterministic Scene 1.0 render and CAD-edge mesh construction."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from .._internal.mesh import DEFAULT_ANGULAR_TOLERANCE, TriMesh, cached_mesh, mesh_error
from simplecadapi._cpp import Solid
from ..scene.glb import profile_cross, profile_f32, profile_f32_bits, profile_normalize


ASSET_TO_SCENE = [1000, 0, 0, 0, 0, 0, -1000, 0, 0, 1000, 0, 0, 0, 0, 0, 1]


@dataclass(frozen=True, slots=True)
class CanonicalTriangleBlock:
    entity_id: str
    render_key: bytes
    block_bytes: bytes
    vertex_keys: tuple[bytes, ...]
    positions: tuple[tuple[float, float, float], ...]
    normals: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True, slots=True)
class CanonicalEdgeBlock:
    entity_id: str
    render_key: bytes
    block_bytes: bytes
    position_keys: tuple[bytes, ...]
    positions: tuple[tuple[float, float, float], ...]
    segments: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class RenderGroup:
    entity_id: str
    first_index: int
    index_count: int


@dataclass(frozen=True, slots=True)
class RenderMesh:
    positions: tuple[tuple[float, float, float], ...]
    normals: tuple[tuple[float, float, float], ...]
    indices: tuple[int, ...]
    groups: tuple[RenderGroup, ...]
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    blocks: tuple[CanonicalTriangleBlock, ...]


@dataclass(frozen=True, slots=True)
class RenderEdgeMesh:
    positions: tuple[tuple[float, float, float], ...]
    indices: tuple[int, ...]
    groups: tuple[RenderGroup, ...]
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    blocks: tuple[CanonicalEdgeBlock, ...]
    degenerate_entity_ids: tuple[str, ...]


def cad_to_gltf(point: Sequence[float] | object) -> tuple[float, float, float]:
    """Convert CAD mm/+Z coordinates to glTF m/+Y coordinates."""

    if hasattr(point, "X") and hasattr(point, "Y") and hasattr(point, "Z"):
        point = (float(point.X()), float(point.Y()), float(point.Z()))
    return (
        profile_f32(float(point[0]) / 1000.0),  # type: ignore[index]
        profile_f32(float(point[2]) / 1000.0),  # type: ignore[index]
        profile_f32(-float(point[1]) / 1000.0),  # type: ignore[index]
    )


def cad_direction_to_gltf(direction: Sequence[float]) -> tuple[float, float, float]:
    return cad_to_gltf(direction)


def build_render_mesh(
    solid: Solid,
    *,
    face_entity_ids: Sequence[str],
    linear_tolerance: float,
    angular_tolerance: float,
) -> RenderMesh:
    faces = solid._iter_faces()
    if len(faces) != len(face_entity_ids):
        raise ValueError("face entity count does not match the solid topology")
    mesh = cached_mesh(
        solid,
        linear_tolerance=linear_tolerance,
        angular_tolerance=angular_tolerance,
    )
    if mesh is None:
        detail = mesh_error(solid) or "unknown evaluated mesh error"
        raise ValueError(f"solid evaluated mesh is unavailable: {detail}")
    blocks = tuple(
        _triangle_block(
            mesh,
            face_range=mesh.face_triangle_ranges[face_index],
            entity_id=entity_id,
        )
        for face_index, entity_id in enumerate(face_entity_ids)
    )
    ordered = tuple(sorted(blocks, key=lambda item: (item.render_key, item.block_bytes, item.entity_id.encode("utf-8"))))
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    indices: list[int] = []
    groups: list[RenderGroup] = []
    for block in ordered:
        offset = len(positions)
        positions.extend(block.positions)
        normals.extend(block.normals)
        indices.extend(offset + index for triangle in block.triangles for index in triangle)
        groups.append(
            RenderGroup(
                entity_id=block.entity_id,
                first_index=len(indices) - len(block.triangles) * 3,
                index_count=len(block.triangles) * 3,
            )
        )
    return RenderMesh(
        positions=tuple(positions),
        normals=tuple(normals),
        indices=tuple(indices),
        groups=tuple(sorted(groups, key=lambda item: item.first_index)),
        bounds=_bounds(positions),
        blocks=ordered,
    )


def build_edge_mesh(
    solid: Solid,
    *,
    edge_entity_ids: Sequence[str],
    linear_tolerance: float,
    angular_tolerance: float = DEFAULT_ANGULAR_TOLERANCE,
) -> RenderEdgeMesh:
    edges = solid._iter_edges()
    if len(edges) != len(edge_entity_ids):
        raise ValueError("edge entity count does not match the solid topology")
    blocks = tuple(
        _edge_block(
            edge if hasattr(edge, "_polyline") else edge._native_wrapped,
            entity_id=entity_id,
            linear_tolerance=linear_tolerance,
            angular_tolerance=angular_tolerance,
        )
        for edge, entity_id in zip(edges, edge_entity_ids)
    )
    rendered = tuple(
        sorted(
            (block for block in blocks if block.segments),
            key=lambda item: (item.render_key, item.block_bytes, item.entity_id.encode("utf-8")),
        )
    )
    positions: list[tuple[float, float, float]] = []
    indices: list[int] = []
    groups: list[RenderGroup] = []
    for block in rendered:
        offset = len(positions)
        positions.extend(block.positions)
        indices.extend(offset + index for segment in block.segments for index in segment)
        groups.append(
            RenderGroup(
                entity_id=block.entity_id,
                first_index=len(indices) - len(block.segments) * 2,
                index_count=len(block.segments) * 2,
            )
        )
    return RenderEdgeMesh(
        positions=tuple(positions),
        indices=tuple(indices),
        groups=tuple(sorted(groups, key=lambda item: item.first_index)),
        bounds=_bounds(positions),
        blocks=rendered,
        degenerate_entity_ids=tuple(
            sorted((block.entity_id for block in blocks if not block.segments), key=lambda value: value.encode("utf-8"))
        ),
    )


def solid_asset_bounds(solid: Solid) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if hasattr(solid, "_bounds"):  # the native kernel
        xmin, ymin, zmin, xmax, ymax, zmax = solid._bounds()
        return ((float(xmin), float(ymin), float(zmin)), (float(xmax), float(ymax), float(zmax)))
    from ..kernel.ocp_properties import bounding_box

    box = bounding_box(solid._native_wrapped)
    return (
        (float(box.xmin), float(box.ymin), float(box.zmin)),
        (float(box.xmax), float(box.ymax), float(box.zmax)),
    )


def _prepare_shape(shape, *, force_forward: bool):
    from simplecadapi._cpp.occt.TopAbs import TopAbs_FORWARD
    from simplecadapi._cpp.occt.TopLoc import TopLoc_Location

    oriented = shape.Oriented(TopAbs_FORWARD) if force_forward else shape
    location = oriented.Location()
    unlocated = oriented.Located(TopLoc_Location(), False)
    if location.IsIdentity():
        return unlocated
    from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_Transform

    builder = BRepBuilderAPI_Transform(unlocated, location.Transformation(), True, False)
    builder.Build()
    if not builder.IsDone():
        raise ValueError("OCP location bake failed")
    return builder.Shape()


def _triangle_block(
    mesh: TriMesh,
    *,
    face_range,
    entity_id: str,
) -> CanonicalTriangleBlock:
    """One face's canonical triangle block.

    Every value follows the profile's fixed steps: binary64 arithmetic in a
    fixed order, then rounding to binary32 with ``-0`` written as ``+0``
    (:func:`~simplecadapi.scene.glb.profile_f32`).  They are evaluated here for
    all of the face's triangles at once, with numpy, which performs the same
    IEEE operations in the same order as the scalar helpers (and never fuses a
    multiply and an add), so the bytes are identical, at a fraction of the cost.
    """

    start = face_range.start
    stop = start + face_range.count
    corners = np.asarray(mesh.triangles[start:stop], dtype=np.int64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    positions = _cad_to_gltf_rows(vertices[corners])  # (n, 3 corners, 3 axes)

    # A triangle whose corners collapse to fewer than three distinct positions
    # (after binary32 rounding) is dropped.
    distinct = (
        (positions[:, 0] != positions[:, 1]).any(axis=1)
        & (positions[:, 0] != positions[:, 2]).any(axis=1)
        & (positions[:, 1] != positions[:, 2]).any(axis=1)
    )
    keep = np.flatnonzero(distinct)
    positions = positions[keep]
    a, b, c = positions[:, 0], positions[:, 1], positions[:, 2]
    cross = _cross_rows(b - a, c - a)
    nonzero = ~(cross == 0.0).all(axis=1)
    keep = keep[nonzero]
    positions = positions[nonzero]
    cross = cross[nonzero]
    if len(keep) == 0:
        raise ValueError(f"face {entity_id} has no non-degenerate triangle")

    fallback = _normalize_rows(cross)
    raw = np.asarray(mesh.corner_normals[start:stop], dtype=np.float64)[keep]  # (n, 3 corners, 3)
    given = ~(raw == 0.0).all(axis=2)  # corners that carry a normal of their own
    normals = np.broadcast_to(fallback[:, None, :], raw.shape).copy()
    if given.any():
        normals[given] = _normalize_rows(_cad_to_gltf_rows(raw[given]))

    # One 24-byte key per corner: position bits, then normal bits.
    packed = np.concatenate([positions, normals], axis=2).astype(np.float32).astype("<f4")
    keys = packed.view(np.uint8).reshape(len(keep), 3, 24)
    triangle_keys = [
        _least_cyclic_rotation(tuple(bytes(corner) for corner in triangle)) for triangle in keys
    ]
    unique_keys = sorted(set(key for triangle in triangle_keys for key in triangle))
    key_to_index = {key: index for index, key in enumerate(unique_keys)}
    triangles = tuple(sorted(tuple(key_to_index[key] for key in triangle) for triangle in triangle_keys))
    decoded = np.frombuffer(b"".join(unique_keys), dtype="<f4").reshape(-1, 6).astype(np.float64)
    vertex_bytes = b"".join(unique_keys)
    index_format = "<H" if len(unique_keys) <= 65536 else "<I"
    index_bytes = b"".join(struct.pack(index_format, index) for triangle in triangles for index in triangle)
    block_bytes = vertex_bytes + index_bytes
    return CanonicalTriangleBlock(
        entity_id=entity_id,
        render_key=hashlib.sha256(b"\x01" + block_bytes).digest(),
        block_bytes=block_bytes,
        vertex_keys=tuple(unique_keys),
        positions=tuple(tuple(row[:3]) for row in decoded.tolist()),
        normals=tuple(tuple(row[3:]) for row in decoded.tolist()),
        triangles=triangles,
    )


def _f32_rows(values: "np.ndarray") -> "np.ndarray":
    """:func:`profile_f32` of every value: binary32 rounding, ``-0`` as ``+0`` (as binary64)."""

    if not np.isfinite(values).all():
        raise ValueError("f32 input must be a finite number")
    with np.errstate(over="ignore"):
        narrow = values.astype(np.float32)
    if not np.isfinite(narrow).all():
        raise ValueError("f32 conversion overflowed")
    return np.where(narrow == 0, np.float32(0.0), narrow).astype(np.float64)


def _cad_to_gltf_rows(points: "np.ndarray") -> "np.ndarray":
    """:func:`cad_to_gltf` of every point (the last axis is x, y, z)."""

    return _f32_rows(
        np.stack(
            [points[..., 0] / 1000.0, points[..., 2] / 1000.0, (-points[..., 1]) / 1000.0],
            axis=-1,
        )
    )


def _cross_rows(left: "np.ndarray", right: "np.ndarray") -> "np.ndarray":
    """:func:`profile_cross` of every pair, in its fixed operation order."""

    p1x, p2x = left[:, 1] * right[:, 2], left[:, 2] * right[:, 1]
    p1y, p2y = left[:, 2] * right[:, 0], left[:, 0] * right[:, 2]
    p1z, p2z = left[:, 0] * right[:, 1], left[:, 1] * right[:, 0]
    result = np.stack([p1x - p2x, p1y - p2y, p1z - p2z], axis=1)
    if not np.isfinite(result).all():
        raise ValueError("cross product produced a non-finite value")
    return result


def _normalize_rows(vectors: "np.ndarray") -> "np.ndarray":
    """:func:`profile_normalize` of every vector."""

    if not np.isfinite(vectors).all():
        raise ValueError("normalize input must contain finite values")
    squared = vectors[:, 0] * vectors[:, 0] + vectors[:, 1] * vectors[:, 1]
    squared = squared + vectors[:, 2] * vectors[:, 2]
    if not (np.isfinite(squared).all() and (squared > 0).all()):
        raise ValueError("normalize input has zero or non-finite length")
    result = _f32_rows(vectors / np.sqrt(squared)[:, None])
    norm_squared = result[:, 0] * result[:, 0] + result[:, 1] * result[:, 1]
    norm_squared = norm_squared + result[:, 2] * result[:, 2]
    norm = np.sqrt(norm_squared)
    if not ((norm >= 1.0 - 1e-6) & (norm <= 1.0 + 1e-6)).all():
        raise ValueError("normalized binary32 vector is outside the profile tolerance")
    return result


def _edge_block(
    edge,
    *,
    entity_id: str,
    linear_tolerance: float,
    angular_tolerance: float,
) -> CanonicalEdgeBlock:
    if hasattr(edge, "_polyline"):  # the native kernel samples the edge itself
        try:
            points = edge._polyline(float(linear_tolerance), float(angular_tolerance))
        except Exception as exc:
            raise ValueError(f"edge {entity_id} discretization failed") from exc
    else:
        from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve
        from simplecadapi._cpp.occt.GCPnts import GCPnts_TangentialDeflection
        from simplecadapi._cpp.occt.TopoDS import TopoDS

        prepared = TopoDS.Edge_s(_prepare_shape(edge, force_forward=True))
        adaptor = BRepAdaptor_Curve(prepared)
        try:
            sampler = GCPnts_TangentialDeflection(
                adaptor,
                adaptor.FirstParameter(),
                adaptor.LastParameter(),
                float(angular_tolerance),
                float(linear_tolerance),
                2,
                1e-9,
                1e-7,
            )
        except Exception as exc:
            raise ValueError(f"edge {entity_id} discretization failed") from exc
        points = [
            (float(sampler.Value(index).X()), float(sampler.Value(index).Y()), float(sampler.Value(index).Z()))
            for index in range(1, sampler.NbPoints() + 1)
        ]
    keys = _position_keys(points)
    segments = [(keys[index], keys[index + 1]) for index in range(len(keys) - 1) if keys[index] != keys[index + 1]]
    position_keys = sorted(set(key for segment in segments for key in segment))
    key_to_index = {key: index for index, key in enumerate(position_keys)}
    canonical_segments = tuple(sorted(set((min(key_to_index[a], key_to_index[b]), max(key_to_index[a], key_to_index[b])) for a, b in segments)))
    decoded_positions = tuple(_decode_position(key) for key in position_keys)
    index_format = "<H" if len(position_keys) <= 65536 else "<I"
    index_bytes = b"".join(struct.pack(index_format, index) for segment in canonical_segments for index in segment)
    block_bytes = b"".join(position_keys) + index_bytes
    return CanonicalEdgeBlock(
        entity_id=entity_id,
        render_key=hashlib.sha256(b"\x02" + block_bytes).digest(),
        block_bytes=block_bytes,
        position_keys=tuple(position_keys),
        positions=decoded_positions,
        segments=canonical_segments,
    )


def _position_keys(points: Sequence[Sequence[float]]) -> list[bytes]:
    """The position keys of CAD points (mm, +Z up), as ``_position_key(cad_to_gltf(point))`` for each, in one pass.

    The same arithmetic as the scalar path -- divide in binary64, round to binary32, the profile's zero-sign and
    finiteness rules -- so the bytes are identical; numpy does it for the whole polyline at once.
    """

    if len(points) == 0:
        return []
    cad = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    glt = np.stack([cad[:, 0] / 1000.0, cad[:, 2] / 1000.0, -cad[:, 1] / 1000.0], axis=1)
    if not np.isfinite(glt).all():
        raise ValueError("f32 input must be a finite number")
    with np.errstate(over="ignore"):
        single = glt.astype("<f4")
    if not np.isfinite(single).all():
        raise ValueError("f32 conversion overflowed")
    bits = np.ascontiguousarray(single).view("<u4")
    bits = np.where(bits == 0x80000000, np.uint32(0), bits).astype("<u4")
    raw = bits.tobytes()
    return [raw[offset : offset + 12] for offset in range(0, len(raw), 12)]


def _position_key(position: Sequence[float]) -> bytes:
    return struct.pack("<III", *(profile_f32_bits(float(value)) for value in position))


def _vertex_key(position: Sequence[float], normal: Sequence[float]) -> bytes:
    return _position_key(position) + struct.pack("<III", *(profile_f32_bits(float(value)) for value in normal))


def _decode_position(key: bytes) -> tuple[float, float, float]:
    return struct.unpack("<fff", key)  # type: ignore[return-value]


def _decode_vertex(key: bytes) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    return _decode_position(key[:12]), _decode_position(key[12:])


def _least_cyclic_rotation(values: tuple[bytes, bytes, bytes]) -> tuple[bytes, bytes, bytes]:
    return min((values, values[1:] + values[:1], values[2:] + values[:2]))


def _bounds(points: Iterable[Sequence[float]]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    points = tuple(points)
    if not points:
        raise ValueError("render mesh cannot be empty")
    return (
        tuple(min(float(point[axis]) for point in points) for axis in range(3)),
        tuple(max(float(point[axis]) for point in points) for axis in range(3)),
    )  # type: ignore[return-value]


__all__ = [
    "ASSET_TO_SCENE",
    "CanonicalEdgeBlock",
    "CanonicalTriangleBlock",
    "RenderEdgeMesh",
    "RenderGroup",
    "RenderMesh",
    "build_edge_mesh",
    "build_render_mesh",
    "cad_direction_to_gltf",
    "cad_to_gltf",
    "solid_asset_bounds",
]

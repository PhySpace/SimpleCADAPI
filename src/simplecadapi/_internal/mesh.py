"""Internal mesh companion data for SimpleCAD geometry.

This module intentionally stays out of the public API. A solid's mesh is built
on first use by :func:`cached_mesh` and kept on the solid per tolerance; it is
derived data (never pickled, never copied) and nothing builds one while a model
is being made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple

import numpy as np

from ..kernel.ocp_mesh import tessellate_face_with_normals


DEFAULT_LINEAR_TOLERANCE = 0.35
DEFAULT_ANGULAR_TOLERANCE = 0.22
MESH_RUNTIME_KEY = "mesh.default"
MESH_ERROR_RUNTIME_KEY = "mesh.error"


@dataclass(frozen=True)
class FaceTriangleRange:
    """Internal mapping from a source face to a contiguous triangle range."""

    face_index: int
    start: int
    count: int
    source_topo_id: str | None = None


@dataclass(frozen=True)
class TriMesh:
    """Internal triangle mesh data attached to OCP-backed solids."""

    vertices: np.ndarray
    triangles: np.ndarray
    face_triangle_ranges: Tuple[FaceTriangleRange, ...]
    linear_tolerance: float = DEFAULT_LINEAR_TOLERANCE
    angular_tolerance: float = DEFAULT_ANGULAR_TOLERANCE
    corner_normals: np.ndarray | None = None

    def __post_init__(self) -> None:
        vertices = np.asarray(self.vertices, dtype=float)
        triangles = np.asarray(self.triangles, dtype=np.int64)

        if vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError("TriMesh vertices must have shape (n, 3)")
        if triangles.ndim != 2 or triangles.shape[1] != 3:
            raise ValueError("TriMesh triangles must have shape (m, 3)")
        if not np.all(np.isfinite(vertices)):
            raise ValueError("TriMesh vertices must be finite")
        if len(triangles) and (
            int(triangles.min()) < 0 or int(triangles.max()) >= len(vertices)
        ):
            raise ValueError("TriMesh triangle indices are out of bounds")

        corner_normals = self.corner_normals
        if corner_normals is None:
            corner_normals = _triangle_corner_normals(vertices, triangles)
        else:
            corner_normals = np.asarray(corner_normals, dtype=float)
            if corner_normals.shape != (len(triangles), 3, 3):
                raise ValueError("TriMesh corner_normals must have shape (m, 3, 3)")
            if not np.all(np.isfinite(corner_normals)):
                raise ValueError("TriMesh corner_normals must be finite")

        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "triangles", triangles)
        object.__setattr__(self, "corner_normals", corner_normals)

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.triangles.shape[0])

    @property
    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        if self.vertex_count == 0:
            zero = (0.0, 0.0, 0.0)
            return zero, zero
        lower = self.vertices.min(axis=0)
        upper = self.vertices.max(axis=0)
        return tuple(float(v) for v in lower), tuple(float(v) for v in upper)


def build_solid_trimesh(
    solid: Any,
    *,
    linear_tolerance: float = DEFAULT_LINEAR_TOLERANCE,
    angular_tolerance: float = DEFAULT_ANGULAR_TOLERANCE,
) -> TriMesh:
    """Build an internal triangle mesh from an OCP-backed Solid wrapper."""

    all_vertices: list[tuple[float, float, float]] = []
    all_triangles: list[tuple[int, int, int]] = []
    all_corner_normals: list[tuple[tuple[float, float, float], ...]] = []
    face_ranges: list[FaceTriangleRange] = []

    for face_index, face in enumerate(solid._iter_faces()):
        start = len(all_triangles)
        vertices, triangles, corner_normals = tessellate_face_with_normals(
            face.wrapped,
            tolerance=linear_tolerance,
            angular_tolerance=angular_tolerance,
        )
        vertex_offset = len(all_vertices)
        all_vertices.extend((float(x), float(y), float(z)) for x, y, z in vertices)
        all_triangles.extend(
            (
                int(a) + vertex_offset,
                int(b) + vertex_offset,
                int(c) + vertex_offset,
            )
            for a, b, c in triangles
        )
        face_triangles = np.asarray(triangles, dtype=np.int64).reshape((-1, 3))
        face_vertices = np.asarray(vertices, dtype=float).reshape((-1, 3))
        all_corner_normals.extend(
            tuple(tuple(float(value) for value in normal) for normal in triangle)
            for triangle in corner_normals
        )
        face_ranges.append(
            FaceTriangleRange(
                face_index=face_index,
                start=start,
                count=len(all_triangles) - start,
                source_topo_id=getattr(face, "topo_id", None),
            )
        )

    return TriMesh(
        vertices=np.asarray(all_vertices, dtype=float).reshape((-1, 3)),
        triangles=np.asarray(all_triangles, dtype=np.int64).reshape((-1, 3)),
        face_triangle_ranges=tuple(face_ranges),
        linear_tolerance=float(linear_tolerance),
        angular_tolerance=float(angular_tolerance),
        corner_normals=np.asarray(all_corner_normals, dtype=float).reshape((-1, 3, 3)),
    )


def cached_mesh(
    solid: Any,
    *,
    linear_tolerance: float = DEFAULT_LINEAR_TOLERANCE,
    angular_tolerance: float = DEFAULT_ANGULAR_TOLERANCE,
) -> TriMesh | None:
    """Return the internal mesh cache for tests and future checkers."""

    key = _mesh_runtime_key(linear_tolerance, angular_tolerance)
    mesh = _get_runtime(solid, key, None)
    if mesh is None:
        try:
            mesh = build_solid_trimesh(
                solid,
                linear_tolerance=linear_tolerance,
                angular_tolerance=angular_tolerance,
            )
            _set_runtime(solid, key, mesh)
        except Exception as exc:
            _set_runtime(solid, MESH_ERROR_RUNTIME_KEY, str(exc))
            return None
    return mesh if isinstance(mesh, TriMesh) else None


def mesh_error(solid: Any) -> str | None:
    """Return the internal mesh diagnostic for tests and future checkers."""

    value = _get_runtime(solid, MESH_ERROR_RUNTIME_KEY, None)
    return str(value) if value else None


def _set_runtime(shape: Any, key: str, value: Any) -> None:
    setter = getattr(shape, "_set_runtime", None)
    if callable(setter):
        setter(key, value)


def _get_runtime(shape: Any, key: str, default: Any) -> Any:
    getter = getattr(shape, "_get_runtime", None)
    if callable(getter):
        return getter(key, default)
    return default


def _mesh_runtime_key(linear_tolerance: float, angular_tolerance: float) -> str:
    if (
        float(linear_tolerance) == DEFAULT_LINEAR_TOLERANCE
        and float(angular_tolerance) == DEFAULT_ANGULAR_TOLERANCE
    ):
        return MESH_RUNTIME_KEY
    return f"mesh:{float(linear_tolerance).hex()}:{float(angular_tolerance).hex()}"


def _triangle_corner_normals(
    vertices: np.ndarray, triangles: np.ndarray
) -> np.ndarray:
    normals = np.zeros((len(triangles), 3, 3), dtype=float)
    for index, (a, b, c) in enumerate(triangles):
        left = vertices[int(b)] - vertices[int(a)]
        right = vertices[int(c)] - vertices[int(a)]
        cross = np.cross(left, right)
        length = float(np.linalg.norm(cross))
        if length > 0.0 and np.isfinite(length):
            normal = cross / length
            normals[index, :, :] = normal
    return normals

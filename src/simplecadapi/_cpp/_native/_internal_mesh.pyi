"""
simplecadapi._internal.mesh
"""
from __future__ import annotations
import numpy
import simplecadapi._cpp._native
import typing
__all__: list[str] = ['DEFAULT_ANGULAR_TOLERANCE', 'DEFAULT_LINEAR_TOLERANCE', 'FaceTriangleRange', 'MESH_ERROR_RUNTIME_KEY', 'MESH_RUNTIME_KEY', 'TriMesh', 'build_solid_trimesh', 'cached_mesh', 'mesh_error']
class FaceTriangleRange:
    @property
    def count(self) -> int:
        ...
    @property
    def face_index(self) -> int:
        ...
    @property
    def source_topo_id(self) -> str:
        ...
    @property
    def start(self) -> int:
        ...
class TriMesh:
    @property
    def angular_tolerance(self) -> float:
        ...
    @property
    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        ...
    @property
    def corner_normals(self) -> typing.Any:
        ...
    @property
    def face_triangle_ranges(self) -> list[FaceTriangleRange]:
        ...
    @property
    def linear_tolerance(self) -> float:
        ...
    @property
    def triangle_count(self) -> int:
        ...
    @property
    def triangles(self) -> numpy.ndarray:
        ...
    @property
    def vertex_count(self) -> int:
        ...
    @property
    def vertices(self) -> numpy.ndarray:
        ...
def build_solid_trimesh(solid: simplecadapi._cpp._native.AnyShape, *, linear_tolerance: typing.SupportsFloat | typing.SupportsIndex = 0.35, angular_tolerance: typing.SupportsFloat | typing.SupportsIndex = 0.22) -> TriMesh:
    ...
def cached_mesh(solid: simplecadapi._cpp._native.AnyShape, *, linear_tolerance: typing.SupportsFloat | typing.SupportsIndex = 0.35, angular_tolerance: typing.SupportsFloat | typing.SupportsIndex = 0.22) -> TriMesh:
    ...
def mesh_error(solid: simplecadapi._cpp._native.AnyShape) -> typing.Any:
    ...
DEFAULT_ANGULAR_TOLERANCE: float = 0.22
DEFAULT_LINEAR_TOLERANCE: float = 0.35
MESH_ERROR_RUNTIME_KEY: str = 'mesh.error'
MESH_RUNTIME_KEY: str = 'mesh.default'

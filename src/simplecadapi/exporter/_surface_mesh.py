"""Shared OpenCASCADE BREP tessellation for STL and OBJ exporters."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

import numpy as np
from ..artifacts.assembly_io import materialize_definition
from simplecadapi._cpp import Assembly, make_compound_from_assembly_rcompound, Part
from ..translator.package_units import (
    ProductPackageInput,
    read_product_package_translation_units,
)

_TESSELLATION_BACKEND = "opencascade-brep-tessellation"


@dataclass(frozen=True, slots=True)
class TessellatedSurfaceMesh:
    """One triangle mesh produced directly from evaluated product BREP solids."""

    vertices: np.ndarray
    triangles: np.ndarray
    root_definition_id: str
    solid_count: int
    definition_count: int
    linear_deflection: float
    angular_deflection_degrees: float
    relative: bool
    tessellation_backend: str = _TESSELLATION_BACKEND

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.triangles.shape[0])


def _product_solids(value: Part | Assembly) -> tuple[Any, ...]:
    if isinstance(value, Part):
        return (value.body,)
    projection = make_compound_from_assembly_rcompound(assembly=value)
    solids = tuple(projection.solids())
    if not solids:
        raise ValueError("Product assembly produced no solids for mesh export")
    return solids


def _vertex_key(point: Sequence[float], tolerance: float) -> tuple[int, int, int]:
    return tuple(int(round(float(value) / tolerance)) for value in point)


def _is_collapsed_triangle(
    vertices: Sequence[tuple[float, float, float]],
    indices: tuple[int, int, int],
) -> bool:
    points = np.asarray([vertices[index] for index in indices], dtype=np.float64)
    first = points[1] - points[0]
    second = points[2] - points[0]
    third = points[2] - points[1]
    max_edge_squared = max(
        float(np.dot(first, first)),
        float(np.dot(second, second)),
        float(np.dot(third, third)),
    )
    if max_edge_squared == 0.0:
        return True
    normal = np.cross(first, second)
    area_squared = float(np.dot(normal, normal))
    relative_floor = np.finfo(np.float64).eps ** 2 * max_edge_squared**2
    return area_squared <= relative_floor


def _tessellate_native(
    solid: Any,
    *,
    linear_deflection: float,
    angular_deflection_degrees: float,
    relative: bool,
) -> tuple[np.ndarray, np.ndarray]:
    import simplecadapi._cpp as native

    vertices, triangles = native.tessellate_solid(
        solid,
        linear_deflection=linear_deflection,
        angular_deflection_degrees=angular_deflection_degrees,
        relative=relative,
    )
    return np.asarray(vertices, dtype=np.float64), np.asarray(triangles, dtype=np.int32)


def tessellate_solid(
    solid: Any,
    *,
    linear_deflection: float,
    angular_deflection_degrees: float,
    relative: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Tessellate one evaluated OpenCASCADE solid with validated parameters."""
    linear = float(linear_deflection)
    if not math.isfinite(linear) or linear <= 0.0:
        raise ValueError("linear_deflection must be a positive finite value")
    angular_degrees = float(angular_deflection_degrees)
    if (
        not math.isfinite(angular_degrees)
        or angular_degrees <= 0.0
        or angular_degrees > 180.0
    ):
        raise ValueError("angular_deflection_degrees must be in (0, 180]")
    if not isinstance(relative, bool):
        raise TypeError("relative must be a bool")
    return _tessellate_native(
        solid,
        linear_deflection=linear,
        angular_deflection_degrees=angular_degrees,
        relative=relative,
    )


def tessellate_product_surface(
    data: ProductPackageInput,
    *,
    linear_deflection: float,
    angular_deflection_degrees: float,
    relative: bool,
) -> TessellatedSurfaceMesh:
    """Tessellate every evaluated product solid directly with OpenCASCADE."""

    linear = float(linear_deflection)
    angular_degrees = float(angular_deflection_degrees)

    package, units = read_product_package_translation_units(data)
    root = materialize_definition(package.root_definition)
    solids = _product_solids(root)
    vertex_blocks: list[np.ndarray] = []
    triangle_blocks: list[np.ndarray] = []
    vertex_offset = 0
    for solid in solids:
        vertices, triangles = tessellate_solid(
            solid,
            linear_deflection=linear,
            angular_deflection_degrees=angular_degrees,
            relative=relative,
        )
        vertex_blocks.append(vertices)
        triangle_blocks.append(triangles + vertex_offset)
        vertex_offset += len(vertices)

    return TessellatedSurfaceMesh(
        vertices=np.concatenate(vertex_blocks, axis=0),
        triangles=np.concatenate(triangle_blocks, axis=0),
        root_definition_id=package.root_definition.definition_id,
        solid_count=len(solids),
        definition_count=len(units),
        linear_deflection=linear,
        angular_deflection_degrees=angular_degrees,
        relative=relative,
    )


__all__ = [
    "TessellatedSurfaceMesh",
    "tessellate_product_surface",
    "tessellate_solid",
]

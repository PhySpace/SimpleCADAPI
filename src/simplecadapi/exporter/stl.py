"""Direct OpenCASCADE BREP tessellation to binary STL."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

import numpy as np

from ..translator.package_units import ProductInput
from ._surface_mesh import TessellatedSurfaceMesh, tessellate_product_surface


@dataclass(frozen=True, slots=True)
class ProductSTLExportReport:
    """Evidence from direct BREP tessellation and binary STL export."""

    output_path: Path
    root_definition_id: str
    solid_count: int
    definition_count: int
    vertex_count: int
    triangle_count: int
    linear_deflection: float
    angular_deflection_degrees: float
    relative: bool
    tessellation_backend: str = "opencascade-brep-tessellation"


def _write_binary_stl(path: Path, mesh: TessellatedSurfaceMesh) -> None:
    header = b"SimpleCAD OpenCASCADE BREP tessellation".ljust(80, b"\0")
    with path.open("wb") as stream:
        stream.write(header)
        stream.write(struct.pack("<I", mesh.triangle_count))
        for a, b, c in mesh.triangles:
            points = mesh.vertices[[a, b, c]]
            normal = np.cross(points[1] - points[0], points[2] - points[0])
            length = float(np.linalg.norm(normal))
            if length == 0.0 or not np.isfinite(length):
                raise RuntimeError("STL tessellation contains a collapsed triangle")
            normal /= length
            stream.write(
                struct.pack(
                    "<12fH",
                    *normal.astype(np.float32),
                    *points.astype(np.float32).reshape(-1),
                    0,
                )
            )


def export_product_package_to_stl(
    data: ProductInput,
    output_path: str | Path,
    *,
    linear_deflection: float = 0.1,
    angular_deflection_degrees: float = 20.0,
    relative: bool = False,
) -> ProductSTLExportReport:
    """Export one `.scadpkg` directly from evaluated BREP as binary STL.

    `linear_deflection` is the maximum chordal deviation in product units.
    `angular_deflection_degrees` limits angular deviation on curved surfaces.
    No remeshing or topology reconstruction is performed.
    """

    destination = Path(output_path).expanduser().resolve()
    if destination.suffix.lower() != ".stl":
        raise ValueError("output_path must end in .stl")
    destination.parent.mkdir(parents=True, exist_ok=True)
    mesh = tessellate_product_surface(
        data=data,
        linear_deflection=linear_deflection,
        angular_deflection_degrees=angular_deflection_degrees,
        relative=relative,
    )
    _write_binary_stl(destination, mesh)
    if destination.stat().st_size != 84 + 50 * mesh.triangle_count:
        raise RuntimeError("STL writer produced an invalid binary length")
    return ProductSTLExportReport(
        output_path=destination,
        root_definition_id=mesh.root_definition_id,
        solid_count=mesh.solid_count,
        definition_count=mesh.definition_count,
        vertex_count=mesh.vertex_count,
        triangle_count=mesh.triangle_count,
        linear_deflection=mesh.linear_deflection,
        angular_deflection_degrees=mesh.angular_deflection_degrees,
        relative=mesh.relative,
    )


__all__ = ["ProductSTLExportReport", "export_product_package_to_stl"]

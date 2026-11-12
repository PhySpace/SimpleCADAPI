"""Direct OpenCASCADE BREP tessellation to triangle OBJ."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..translator.package_units import ProductInput
from ._surface_mesh import tessellate_product_surface


@dataclass(frozen=True, slots=True)
class ProductOBJExportReport:
    """Evidence from direct BREP tessellation and triangle OBJ export."""

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


def export_product_package_to_obj(
    data: ProductInput,
    output_path: str | Path,
    *,
    linear_deflection: float = 0.1,
    angular_deflection_degrees: float = 20.0,
    relative: bool = False,
) -> ProductOBJExportReport:
    """Export one `.scadpkg` directly from evaluated BREP as triangle OBJ.

    `linear_deflection` is the maximum chordal deviation in product units.
    `angular_deflection_degrees` limits angular deviation on curved surfaces.
    No remeshing or topology reconstruction is performed.
    """

    destination = Path(output_path).expanduser().resolve()
    if destination.suffix.lower() != ".obj":
        raise ValueError("output_path must end in .obj")
    destination.parent.mkdir(parents=True, exist_ok=True)
    mesh = tessellate_product_surface(
        data=data,
        linear_deflection=linear_deflection,
        angular_deflection_degrees=angular_deflection_degrees,
        relative=relative,
    )
    with destination.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("# SimpleCAD OpenCASCADE BREP tessellation\n")
        for x, y, z in mesh.vertices:
            stream.write(f"v {float(x):.17g} {float(y):.17g} {float(z):.17g}\n")
        for a, b, c in mesh.triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")
    if destination.stat().st_size <= 0:
        raise RuntimeError("OBJ writer produced an empty file")
    return ProductOBJExportReport(
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


__all__ = ["ProductOBJExportReport", "export_product_package_to_obj"]

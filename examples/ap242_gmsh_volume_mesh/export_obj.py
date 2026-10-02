"""Export the captured bracket directly from evaluated BREP as triangle OBJ."""

from __future__ import annotations

import simplecadapi as scad

from bracket_package import OUT_DIR, capture_bracket


OBJ_PATH = OUT_DIR / "ap242_gmsh_bracket.obj"


def main() -> None:
    package_path = capture_bracket()
    report = scad.exporter.export_product_package_to_obj(
        data=package_path,
        output_path=OBJ_PATH,
        linear_deflection=0.05,
        angular_deflection_degrees=10.0,
    )
    print("obj", report.output_path)
    print("obj_vertices", report.vertex_count)
    print("obj_triangles", report.triangle_count)
    print("tessellation_backend", report.tessellation_backend)
    print("linear_deflection", report.linear_deflection)
    print("angular_deflection_degrees", report.angular_deflection_degrees)


if __name__ == "__main__":
    main()

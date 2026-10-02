"""Export the compact two-stage planetary reducer as MuJoCo MJCF.

    uv run python examples/compact_two_stage_planetary_reducer/export_mjcf.py

Writes the product package first (``export.capture_package``), then the
MJCF, its mapping and the meshes to ``out/``.
"""

import simplecadapi as scad

from export import OUT_DIR, PACKAGE_PATH, capture_package

MJCF_PATH = OUT_DIR / "compact_two_stage_planetary_reducer.xml"
MAPPING_PATH = OUT_DIR / "compact_two_stage_planetary_reducer.mapping.json"
MESH_DIR = OUT_DIR / "compact_two_stage_planetary_reducer_meshes"
BEARING_STEEL_DENSITY_KG_M3 = 7850.0


def main() -> None:
    capture_package()
    report = scad.exporter.export_product_package_to_mjcf(
        data=PACKAGE_PATH,
        output_path=MJCF_PATH,
        mapping_path=MAPPING_PATH,
        mesh_directory=MESH_DIR,
        linear_deflection=0.15,
        default_density_kg_m3=BEARING_STEEL_DENSITY_KG_M3,
    )
    print("mjcf", report.output_path)
    print("mjcf_mapping", report.mapping_path)
    print("mjcf_meshes", report.mesh_directory)
    print("mjcf_bodies", report.body_count)
    print("mjcf_joints", report.joint_count)
    print("mjcf_equalities", report.equality_count)
    print("mjcf_sites", report.site_count)
    print("mjcf_default_density_parts", report.default_density_count)


if __name__ == "__main__":
    main()

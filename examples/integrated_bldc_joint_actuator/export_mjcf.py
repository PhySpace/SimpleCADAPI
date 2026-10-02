"""Export the integrated BLDC actuator as MuJoCo MJCF with its mapping.

    uv run python examples/integrated_bldc_joint_actuator/export_mjcf.py [--reuse-package]

Captures the product package first (``export.capture_package``) unless
``--reuse-package`` says it is already current (``export_all.py`` does that).
"""

import sys

import simplecadapi as scad

from export import OUT_DIR, PACKAGE_PATH, capture_package

MJCF_PATH = OUT_DIR / "integrated_bldc_joint_actuator.xml"
MAPPING_PATH = OUT_DIR / "integrated_bldc_joint_actuator.mapping.json"
MESH_DIR = OUT_DIR / "integrated_bldc_joint_actuator_meshes"
DEFAULT_DENSITY_KG_M3 = 7850.0


def main(*, capture: bool = True) -> None:
    if capture:
        capture_package()
    report = scad.exporter.export_product_package_to_mjcf(
        data=PACKAGE_PATH,
        output_path=MJCF_PATH,
        mapping_path=MAPPING_PATH,
        mesh_directory=MESH_DIR,
        linear_deflection=0.15,
        default_density_kg_m3=DEFAULT_DENSITY_KG_M3,
    )
    print("mjcf", report.output_path)
    print("mjcf_mapping", report.mapping_path)
    print("mjcf_meshes", report.mesh_directory)
    print("mjcf_bodies", report.body_count)
    print("mjcf_joints", report.joint_count)
    print("mjcf_equalities", report.equality_count)
    print("mjcf_sites", report.site_count)
    print("mjcf_mesh_count", report.mesh_count)
    print("mjcf_default_density_parts", report.default_density_count)


if __name__ == "__main__":
    main(capture="--reuse-package" not in sys.argv[1:])

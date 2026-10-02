"""Export the four-bar linkage as MuJoCo MJCF.

    uv run python examples/four_bar_linkage/export_mjcf.py

Writes the product package from the notebook, then compiles it into an MJCF
model with one mesh per part.
"""

from export import OUT_DIR, PACKAGE_PATH, capture_package

import simplecadapi as scad

MJCF_PATH = OUT_DIR / "four_bar_linkage.xml"
MAPPING_PATH = OUT_DIR / "four_bar_linkage.mapping.json"
MESH_DIR = OUT_DIR / "four_bar_linkage_meshes"


def main() -> None:
    capture_package()
    report = scad.exporter.export_product_package_to_mjcf(
        data=PACKAGE_PATH,
        output_path=MJCF_PATH,
        mapping_path=MAPPING_PATH,
        mesh_directory=MESH_DIR,
        linear_deflection=0.1,
    )
    print("mjcf", report.output_path)
    print("mjcf_bodies", report.body_count)
    print("mjcf_joints", report.joint_count)
    print("mjcf_equalities", report.equality_count)
    print("mjcf_closures", report.closure_count)


if __name__ == "__main__":
    main()

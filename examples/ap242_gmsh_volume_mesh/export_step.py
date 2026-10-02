"""Export the captured bracket product package as an AP242 STEP file."""

from __future__ import annotations

import simplecadapi as scad

from bracket_package import OUT_DIR, capture_bracket


STEP_PATH = OUT_DIR / "ap242_gmsh_bracket.step"


def main() -> None:
    package_path = capture_bracket()
    report = scad.exporter.export_product_package_to_step(
        data=package_path,
        output_path=STEP_PATH,
    )
    print("ap242_step", report.output_path)
    print("ap242_metadata_items", report.metadata_item_count)


if __name__ == "__main__":
    main()

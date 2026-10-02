"""Export the integrated BLDC actuator as one AP242 STEP assembly.

    uv run python examples/integrated_bldc_joint_actuator/export_step.py [--reuse-package]

Captures the product package first (``export.capture_package``) unless
``--reuse-package`` says it is already current (``export_all.py`` does that).
"""

import sys

import simplecadapi as scad

from export import OUT_DIR, PACKAGE_PATH, capture_package

STEP_PATH = OUT_DIR / "integrated_bldc_joint_actuator.step"


def main(*, capture: bool = True) -> None:
    if capture:
        capture_package()
    report = scad.exporter.export_product_package_to_step(PACKAGE_PATH, STEP_PATH)
    print("step", report.output_path)
    print("step_definitions", len(report.definition_ids))
    print("step_occurrences", report.occurrence_count)
    print("step_bytes", STEP_PATH.stat().st_size)


if __name__ == "__main__":
    main(capture="--reuse-package" not in sys.argv[1:])

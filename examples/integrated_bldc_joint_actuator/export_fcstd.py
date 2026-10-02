"""Export the integrated BLDC actuator as a replayable FreeCAD document.

    uv run python examples/integrated_bldc_joint_actuator/export_fcstd.py [--reuse-package]

Captures the product package first (``export.capture_package``) unless
``--reuse-package`` says it is already current (``export_all.py`` does that).
"""

import sys

import simplecadapi as scad

from export import OUT_DIR, PACKAGE_PATH, capture_package

FCSTD_PATH = OUT_DIR / "integrated_bldc_joint_actuator.FCStd"


def main(*, capture: bool = True) -> None:
    if capture:
        capture_package()
    scad.translator.freecad_translator.translate_product_package_to_fcstd(
        PACKAGE_PATH,
        str(FCSTD_PATH),
        document_name="IntegratedBLDCJointActuator",
    )
    print("fcstd", FCSTD_PATH)
    print("fcstd_bytes", FCSTD_PATH.stat().st_size)


if __name__ == "__main__":
    main(capture="--reuse-package" not in sys.argv[1:])

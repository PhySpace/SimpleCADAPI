"""Capture the integrated BLDC joint actuator's product package.

    uv run python examples/integrated_bldc_joint_actuator/export.py

The model is the ``integrated_bldc_joint_actuator.py`` notebook. This script
loads its product and writes ``out/integrated_bldc_joint_actuator.scadpkg``.
The STEP, FCStd and MJCF scripts translate that package; ``export_all.py``
captures it once and runs them in parallel.
"""

from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

from dimensions import (
    PACKAGE_RADIUS,
    PACKAGE_STRUCTURAL_BOTTOM_Z,
    PACKAGE_TOP_Z,
    TOTAL_REDUCTION,
    validate_design_dimensions,
)

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
PACKAGE_PATH = OUT_DIR / "integrated_bldc_joint_actuator.scadpkg"

# STEP, MJCF and FreeCAD read meshes and feature graphs from the definition
# closure, so the tessellated scene projection is left out of the package.
INCLUDE_SCENE = False


def capture_package() -> scad.Assembly:
    """Run the notebook and write its product package; returns the assembly."""
    validate_design_dimensions()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "integrated_bldc_joint_actuator.py")
    scad.capture(run.definition, PACKAGE_PATH, include_scene=INCLUDE_SCENE)
    assert isinstance(run.product, scad.Assembly)
    return run.product


def main() -> None:
    actuator = capture_package()
    print(f"envelope_diameter={PACKAGE_RADIUS * 2.0:.1f}")
    print(f"structural_length={PACKAGE_TOP_Z - PACKAGE_STRUCTURAL_BOTTOM_Z:.1f}")
    print(f"total_reduction={TOTAL_REDUCTION:.1f}")
    print(f"assembly={actuator.assembly_id}")
    print(f"components={len(actuator.component_ids())}")
    print(f"constraints={len(actuator.constraint_ids())}")
    print(f"product_package={PACKAGE_PATH} ({PACKAGE_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

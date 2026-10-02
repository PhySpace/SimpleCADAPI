"""Export the four-bar linkage: product package and STEP.

    uv run python examples/four_bar_linkage/export.py

The model is the ``four_bar_linkage.py`` notebook; this script loads its
product, reports the constraint residuals and writes the exchange files to
``out/``.
"""

from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
PACKAGE_PATH = OUT_DIR / "four_bar_linkage.scadpkg"


def capture_package() -> scad.Assembly:
    """Run the notebook and write its product package; returns the assembly."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "four_bar_linkage.py")
    scad.capture(run.definition, PACKAGE_PATH)
    return run.product


def main() -> None:
    linkage = capture_package()
    report = scad.inspect_assembly_constraints_rconstraintreport(assembly=linkage)
    step_report = scad.exporter.export_product_package_to_step(
        PACKAGE_PATH, OUT_DIR / "four_bar_linkage.step"
    )
    print(
        f"four_bar_solved: components={len(linkage.component_ids())} "
        f"constraints={len(linkage.constraint_ids())} "
        f"residuals_ok={all(r.within_tolerance for r in report.residuals)}"
    )
    print("product package", PACKAGE_PATH)
    print("step", step_report.output_path)


if __name__ == "__main__":
    main()

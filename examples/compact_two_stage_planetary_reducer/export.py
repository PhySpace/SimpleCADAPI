"""Export the compact two-stage planetary reducer: package, AP242 STEP, FCStd.

    uv run python examples/compact_two_stage_planetary_reducer/export.py

The model is the ``compact_two_stage_planetary_reducer.py`` notebook; this
script loads its product, reports the solve and writes the exchange files to
``out/``.
"""

from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

from dimensions import HOUSING_HEIGHT, HOUSING_OUTER_RADIUS, TOTAL_REDUCTION

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
PACKAGE_PATH = OUT_DIR / "compact_two_stage_planetary_reducer.scadpkg"


def capture_package() -> scad.Assembly:
    """Run the notebook and write its product package; returns the assembly."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "compact_two_stage_planetary_reducer.py")
    scad.capture(run.definition, PACKAGE_PATH)
    assert isinstance(run.product, scad.Assembly)
    return run.product


def main() -> None:
    reducer = capture_package()
    report = scad.inspect_assembly_constraints_rconstraintreport(assembly=reducer)
    step_report = scad.exporter.export_product_package_to_step(
        PACKAGE_PATH, OUT_DIR / "compact_two_stage_planetary_reducer.step"
    )
    fcstd_path = OUT_DIR / "compact_two_stage_planetary_reducer.FCStd"
    scad.translator.freecad_translator.translate_product_package_to_fcstd(
        PACKAGE_PATH,
        str(fcstd_path),
        document_name="CompactTwoStagePlanetaryReducer",
    )
    print(
        f"reducer: od={HOUSING_OUTER_RADIUS * 2.0:.1f} height={HOUSING_HEIGHT:.1f} "
        f"ratio={TOTAL_REDUCTION:.1f}:1 components={len(reducer.component_ids())} "
        f"constraints={len(reducer.constraint_ids())} "
        f"residuals_ok={all(r.within_tolerance for r in report.residuals)}"
    )
    print("product package", PACKAGE_PATH)
    print("step", step_report.output_path)
    print(f"fcstd {fcstd_path} ({fcstd_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

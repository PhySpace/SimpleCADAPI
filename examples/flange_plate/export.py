"""Role 5 export: durable package + STEP + STL from the flange_plate notebook.

    uv run python examples/flange_plate/export.py                     # capture + STEP
    uv run --extra gmsh python examples/flange_plate/export.py        # same + STL (gmsh backend)
    uv run python examples/flange_plate/export.py --validate          # fresh-process re-open gate
"""
import sys
from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
PKG = OUT / "flange_plate.scadpkg"


def capture_and_export() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "flange_plate.py")   # cell-cached: cheap on a re-run
    cap = scad.capture(run.definition, PKG)        # the package is for exchange only
    print(f"capture: {PKG.name} exists={PKG.exists()} "
          f"result_type={type(cap).__name__} content_hash={run.definition.content_hash}")

    step_report = scad.exporter.step.export_product_package_to_step(
        data=PKG, output_path=OUT / "flange_plate.step")
    print(f"step: output={getattr(step_report, 'output_path', OUT / 'flange_plate.step')} "
          f"schema={getattr(step_report, 'schema', '?')} "
          f"definitions={getattr(step_report, 'definition_ids', '?')} "
          f"occurrences={getattr(step_report, 'occurrence_count', '?')}")

    try:
        stl_report = scad.exporter.stl.export_product_package_to_stl(
            data=PKG, output_path=OUT / "flange_plate.stl",
            linear_deflection=0.1, angular_deflection_degrees=20.0)
        print(f"stl: vertices={getattr(stl_report, 'vertex_count', '?')} "
              f"triangles={getattr(stl_report, 'triangle_count', '?')} "
              f"backend={getattr(stl_report, 'backend', '?')}")
    except Exception as exc:  # gmsh extra missing -> report, never silent
        print(f"stl: SKIPPED ({type(exc).__name__}: {str(exc)[:100]}) "
              f"— rerun with: uv run --extra gmsh python {Path(__file__).name}")


def validate_reopen() -> None:
    package = scad.read_product_package(PKG)
    scad.validate_product_package(package)
    definition = scad.load_product_package(PKG)
    print(f"reopen: validate OK, root_definition={package.root_definition.definition_id} "
          f"root_kind={package.root_kind} definition_id={definition.definition_id} "
          f"definition_kind={definition.definition_kind} revision={definition.revision} "
          f"(single-solid part product)")


if __name__ == "__main__":
    if "--validate" in sys.argv:
        validate_reopen()
    else:
        capture_and_export()

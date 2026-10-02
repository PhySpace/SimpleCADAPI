"""Export the nested gear trains and check the package round trip.

    uv run python examples/external_reference_gear_train/export.py

The model is the ``nested_external_reference_gear_trains.py`` notebook. This
script writes the product package, STEP, FreeCAD and the assembly definition
archive to ``out/``, then materializes the package again and checks that the
nested stage still solves.
"""

from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
NAME = "nested_external_reference_gear_trains"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / f"{NAME}.py")
    package_path = OUT_DIR / f"{NAME}.scadpkg"
    scad.capture(run.definition, package_path)
    step_report = scad.exporter.export_product_package_to_step(
        package_path, OUT_DIR / f"{NAME}.step"
    )
    fcstd_path = OUT_DIR / f"{NAME}.FCStd"
    scad.translator.freecad_translator.translate_product_package_to_fcstd(
        package_path,
        str(fcstd_path),
        document_name="NestedExternalReferenceGearTrains",
    )
    definition_path = scad.export_assembly_definition(
        run.definition, OUT_DIR / f"{NAME}.assembly-definition.zip"
    )

    loaded = scad.load_product_package(package_path)
    rebuilt = scad.materialize_definition(loaded)
    nested = rebuilt.get_component("train_left").item
    report = scad.inspect_assembly_constraints_rconstraintreport(nested)
    print(f"root={rebuilt.assembly_id} components={len(rebuilt.components)}")
    print(
        f"nested={nested.assembly_id} constraints={len(nested.constraints)} "
        f"solved={report.solved}"
    )
    print(f"definition_refs={len(loaded.definition_refs)} content_hash={loaded.content_hash}")
    print(f"definition_artifact={definition_path}")
    print(f"product_package={package_path}")
    print(f"step={step_report.output_path}")
    print(f"fcstd={fcstd_path}")


if __name__ == "__main__":
    main()

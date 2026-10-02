"""Report the tolerance chain and write its exchange files.

    uv run python examples/dimension_tolerance_chain/report.py

The model is the ``dimension_tolerance_chain.py`` notebook. This script
restores the session recorded in the product's definition, re-runs the
worst-case and RSS analyses on the requirement's target expression, and
writes the model/session JSON, the product package, STEP and FreeCAD files to
``out/``.
"""

import json
from pathlib import Path

import simplecadapi as scad
from simplecadapi.artifacts.feature_graph import load_feature_graph_artifact
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "dimension_tolerance_chain.py")
    definition = run.definition

    # The definition is the durable record: analyse what it stores, not the
    # notebook's live values.
    feature_graph = load_feature_graph_artifact(
        definition.blobs[definition.feature_graph_ref.path]
    )
    session = feature_graph.restore_session()
    requirement = session.tolerance_graph.requirements[0]
    expression = session.expression_graph.get(requirement.target_expr_id)
    if expression is None:
        raise RuntimeError("tolerance target expression was not restored")
    worst_case = scad.analyze_tolerance(value=expression, method="worst_case")
    rss = scad.analyze_tolerance(value=expression, method="rss")
    report = session.validate_tolerances(raise_on_failure=True)

    model_json = scad.export_model_json(session)
    (OUT_DIR / "dimension_tolerance_chain.model.json").write_text(
        model_json, encoding="utf-8"
    )
    (OUT_DIR / "dimension_tolerance_chain.session.json").write_text(
        scad.export_session_json(session), encoding="utf-8"
    )
    package_path = OUT_DIR / "dimension_tolerance_chain.scadpkg"
    scad.capture(definition, package_path)
    step_report = scad.exporter.export_product_package_to_step(
        package_path, OUT_DIR / "dimension_tolerance_chain.step"
    )
    fcstd_path = OUT_DIR / "dimension_tolerance_chain.FCStd"
    scad.translator.freecad_translator.translate_product_package_to_fcstd(
        package_path,
        str(fcstd_path),
        document_name="DimensionToleranceChain",
    )

    print("housing_volume", round(run.product.body.get_volume(), 3))
    print(
        "worst_case",
        round(worst_case.nominal, 3),
        round(worst_case.lower_bound, 3),
        round(worst_case.upper_bound, 3),
    )
    print("result_unit", worst_case.dimension.name, worst_case.unit.symbol)
    print("rss", round(rss.nominal, 3), round(rss.lower_bound, 3), round(rss.upper_bound, 3))
    print("requirements_passed", report.passed)
    print("serialized_tolerance_graph", "tolerance_graph" in json.loads(model_json))
    print("content_hash", definition.content_hash)
    print("product_package", package_path)
    print("ap242_step", step_report.output_path)
    print("fcstd", fcstd_path)


if __name__ == "__main__":
    main()

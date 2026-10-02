"""Export the constrained sketch bracket and summarize its recorded sketches.

    uv run python examples/constrained_sketch/export.py

The model is the ``constrained_sketch.py`` notebook. This script writes the
model/session JSON of the product's recorded feature graph, the product
package, STEP and FreeCAD files to ``out/``, and prints what the graph holds:
the sketch operations, their promotions with solve snapshots, and the
constraints of the guided profiles.
"""

import json
from pathlib import Path

import simplecadapi as scad
from simplecadapi.artifacts.feature_graph import load_feature_graph_artifact
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
PROMOTION_OPS = {"make_face_from_sketch_rface", "make_wire_from_sketch_rwire"}


def _sketch_constraints(promotions: list[dict], sketch_name: str) -> list[dict]:
    node = next(n for n in promotions if n["params"]["sketch"].get("name") == sketch_name)
    return node["params"]["sketch"].get("constraints", [])


def _count_kinds(constraints: list[dict], kinds: set[str]) -> int:
    return sum(1 for constraint in constraints if constraint.get("kind") in kinds)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "constrained_sketch.py")
    definition = run.definition
    session = load_feature_graph_artifact(
        definition.blobs[definition.feature_graph_ref.path]
    ).restore_session()
    model_json = scad.export_model_json(session)
    model_path = OUT_DIR / "constrained_sketch.model.json"
    session_path = OUT_DIR / "constrained_sketch.session.json"
    model_path.write_text(model_json, encoding="utf-8")
    session_path.write_text(scad.export_session_json(session), encoding="utf-8")

    package_path = OUT_DIR / "constrained_sketch.scadpkg"
    scad.capture(definition, package_path)
    step_report = scad.exporter.export_product_package_to_step(
        package_path, OUT_DIR / "constrained_sketch.step"
    )
    fcstd_path = OUT_DIR / "constrained_sketch.FCStd"
    scad.translator.freecad_translator.translate_product_package_to_fcstd(
        package_path,
        str(fcstd_path),
        document_name="SimpleCADConstrainedSketchDemo",
    )

    nodes = json.loads(model_json)["graph"]["nodes"]
    ops = [node["op"] for node in nodes]
    promotions = [node for node in nodes if node["op"] in PROMOTION_OPS]
    diamond = _sketch_constraints(promotions, "guided_diamond_pocket")
    curve = _sketch_constraints(promotions, "curve_guided_relief")
    entity_tags = run.product.get_metadata("example.profile_entity_tags")

    print("graph_nodes", len(ops))
    print("sketch_ops", sum(1 for op in ops if "sketch" in op))
    print("promotion_nodes", len(promotions))
    print(
        "promotion_solve_snapshots",
        sum(1 for node in promotions if "solve_snapshot" in node.get("params", {})),
    )
    print("contains_public_solve_node", "make_solve_sketch_rsketchresult" in ops)
    print("plate_sketch_entity_tags", entity_tags["plate"])
    print("diamond_sketch_entity_tags", entity_tags["diamond"])
    print("diamond_constraint_count", len(diamond))
    print(
        "diamond_parallel_equal_constraints",
        _count_kinds(diamond, {"parallel", "equal_length"}),
    )
    print("curve_sketch_entity_tags", entity_tags["curve"])
    print("curve_constraint_count", len(curve))
    print(
        "curve_tangent_equal_radius_constraints",
        _count_kinds(curve, {"tangent", "equal_radius", "concentric", "point_on"}),
    )
    print("volume", round(run.product.body.get_volume(), 3))
    print("content_hash", definition.content_hash)
    print("wrote", model_path)
    print("wrote", session_path)
    print("wrote", step_report.output_path)
    print("wrote", fcstd_path)
    print("product_package", package_path)


if __name__ == "__main__":
    main()

"""Consume a saved analysis package before rebuilding each STEP guide case."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import simplecadapi as scad
from simplecadapi.inspect import brep
from simplecadapi.runtime import run_notebook

from case_config import CASES, CONFIG, OUT


HERE = Path(__file__).resolve().parent


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_evidence(case: str, reconstruction: Path) -> tuple[dict, dict]:
    target = OUT / case / "target.step"
    package = OUT / case / "analysis"
    check = brep.inspect_analysis_package_rdescriptor(
        package_dir=package, target_path=target, expected_config=CONFIG,
    )
    _write_json(reconstruction / "analysis-package-check.json", check)
    if not check["may_start_reconstruction"]:
        raise RuntimeError(f"{case}: R0 failed: {check['hard_failures']}")

    # The full human-readable report is loaded first. Its feature headings are
    # checked against the catalog before any notebook is run.
    report = (package / "parse-report.md").read_text(encoding="utf-8")
    catalog = _json(package / "feature-index.json")
    hypotheses = _json(package / "reconstruction-hypotheses.json")
    specialist = _json(package / "loft-sweep-specialist.json")
    sections = _json(package / "section-index.json")
    unresolved = (package / "unresolved-features.md").read_text(encoding="utf-8")
    status = _json(package / "run-status.json")
    if not specialist["entries"] or not sections["sections"]:
        raise RuntimeError(f"{case}: specialist or section evidence is empty")

    lines = [
        f"# {case.upper()} analysis evidence", "",
        f"Source: `{package / 'parse-report.md'}` (read in full before candidate construction).",
        "", "| Feature | Report claim | Geometry and confidence | Supporting evidence | First operation | Falsification check |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for feature in catalog["features"]:
        feature_id = feature["feature_id"]
        if report.count(f"## {feature_id} —") != 1:
            raise RuntimeError(f"{case}: report does not describe {feature_id} exactly once")
        hypothesis = hypotheses["hypotheses"].get(feature_id)
        if hypothesis is None:
            raise RuntimeError(f"{case}: missing hypothesis for {feature_id}")
        operation = hypothesis["recommended_operation"]
        if operation["capability"] not in ("native", "emulated"):
            raise RuntimeError(f"{case}: unsupported first operation")
        station_ids = [item["section_id"] for item in sections["sections"] if item.get("feature_id") == feature_id]
        dims = ", ".join(
            f"{key}={value['value']} {value['unit']}"
            for key, value in feature["dimensions"].items()
            if isinstance(value, dict) and value.get("value") is not None
        )
        lines.append(
            f"| `{feature_id}` | {feature['category']} / {feature['subtype']} | "
            f"body `{feature['body_id']}`, location `{feature['location']}`, "
            f"{dims}; confidence **{feature['confidence']['level']}** "
            f"(not calibrated probability) | faces {', '.join(feature['entity_ids'])}; "
            f"sections {', '.join(station_ids)} | `{operation['api']}` "
            f"({operation['capability']}) | Compare section profile and all owned faces; "
            "strict material and geometry-labelled topology gate must pass. |"
        )
    lines.extend(["", "## Unresolved and gaps", "", unresolved.strip(), "", f"Soft gaps: `{status['gaps']}`", ""])
    (reconstruction / "analysis-evidence.md").write_text("\n".join(lines), encoding="utf-8")
    if len(catalog["features"]) != len(hypotheses["hypotheses"]):
        raise RuntimeError(f"{case}: evidence does not cover the catalog")
    return catalog, hypotheses


def _fresh_export(package: Path, destination: Path) -> None:
    code = (
        "from simplecadapi.exporter import export_product_package_to_step; "
        "import sys; export_product_package_to_step(sys.argv[1], sys.argv[2])"
    )
    subprocess.run(
        [sys.executable, "-c", code, str(package), str(destination)],
        check=True, capture_output=True, text=True,
    )


def _dimensions_match(target: dict, candidate: dict, tolerance: float = 1.0e-5) -> bool:
    for name, measured in target.items():
        expected = measured.get("value") if isinstance(measured, dict) else None
        actual = candidate.get(name, {}).get("value")
        if expected is not None and (actual is None or abs(expected - actual) > tolerance):
            return False
    return True


def _l1_report_parameters(feature: dict, hypothesis: dict, package: Path) -> dict:
    last = hypothesis["sections"][-1]
    section_index = _json(package / "section-index.json")
    record = next(item for item in section_index["sections"] if
                  item["section_id"] == last["station_id"].replace(":", "-"))
    section = _json(package / record["data_path"])
    points = [point for edge in section["edges"] for point in edge["samples_3d"]]
    end_width = max(point[0] for point in points) - min(point[0] for point in points)
    end_height = max(point[1] for point in points) - min(point[1] for point in points)
    return {
        "START_WIDTH": feature["dimensions"]["profile_width"]["value"],
        "START_HEIGHT": feature["dimensions"]["profile_height"]["value"],
        "END_WIDTH": round(end_width, 9), "END_HEIGHT": round(end_height, 9),
        "END_CENTER": tuple(last["plane"]["origin"]),
        "RULED": hypothesis["recommended_operation"]["parameters"]["ruled"],
    }


def reconstruct_case(case: str) -> dict:
    if case not in CASES:
        raise ValueError(case)
    target = OUT / case / "target.step"
    reconstruction = OUT / case / "reconstruction"
    reconstruction.mkdir(parents=True, exist_ok=True)
    _write_json(reconstruction / "verdict.json", {
        "case": case, "accepted": False,
        "reason": "Current run has not passed the analysis and reconstruction gates.",
    })
    catalog, hypotheses = _read_evidence(case, reconstruction)
    feature = catalog["features"][0]
    operation = hypotheses["hypotheses"][feature["feature_id"]]["recommended_operation"]
    expected_api = {"l1": "loft_rsolid", "s1": "sweep_rsolid", "p1": "loft_multisection_rsolid"}[case]
    if operation["api"] != expected_api or operation["capability"] not in ("native", "emulated"):
        raise RuntimeError(f"{case}: notebook route does not match the report recommendation")
    (reconstruction / "requirement-brief.md").write_text(
        "# Reconstruction requirement\n\nOne editable whole-body solid; strict STEP geometry and topology identity.\n",
        encoding="utf-8",
    )
    notebook = HERE / f"{case}.py"
    attempts = [({}, "report-recommended operation and measured sections")]
    if case == "l1":
        attempts = [(_l1_report_parameters(
            feature, hypotheses["hypotheses"][feature["feature_id"]],
            OUT / case / "analysis",
        ), "report dimensions, final section contour, and ruled-loft recommendation")]
    if case in ("s1", "p1"):
        proxy = hypotheses["hypotheses"][feature["feature_id"]]["spine"]["recommended"]
        if proxy["curve_type"] != "spatial_bspline_proxy":
            raise RuntimeError(f"{case}: expected a recovered spline proxy")
        points = tuple(tuple(point) for point in proxy["curve_definition"]["interpolation_points"])
        if case == "s1":
            dims = feature["dimensions"]
            attempts = [({
                "IS_FRENET": operation["parameters"]["is_frenet"],
                "PATH_POINTS": points,
                "PROFILE_HEIGHT": dims["profile_height"]["value"],
                "PROFILE_WIDTH": dims["profile_width"]["value"],
            }, "report-recommended sweep frame and recovered spine proxy")]
        else:
            # Stations are measured from the saved cap and section contours.
            stations = (
                ((0.0, 0.0, 0.0), (0.3, 0.0, 1.0), 8.0, 4.0),
                ((3.0, 0.0, 10.0), (0.0, 0.0, 1.0), 14.0, 9.0),
                ((0.0, 0.0, 20.0), (-0.3, 0.0, 1.0), 5.0, 3.0),
            )
            attempts = [({"PATH_POINTS": points, "STATIONS": stations},
                         "report-recommended loft and recovered spine proxy")]
    if case == "s1":
        attempts.append(({
            "IS_FRENET": True,
            "PATH_POINTS": ((0.0, 0.0, 0.0), (1.0, 0.0, 2.0), (3.0, 1.0, 4.0), (5.0, 0.0, 6.0)),
            "PROFILE_HEIGHT": 1.0, "PROFILE_WIDTH": 2.0,
        }, "boundary-curve control-point hypothesis and alternate frame after strict mismatch"))
    elif case == "p1":
        attempts.append(({}, "boundary-curve control-point hypothesis after proxy mismatch"))
    iteration_log = []
    winner = None
    for number, (overrides, reason) in enumerate(attempts, 1):
        run = run_notebook(notebook, overrides=overrides or None, cache=False)
        prefix = reconstruction / f"attempt-{number}"
        package = prefix.with_suffix(".scadpkg")
        scad.capture(run.definition, package, include_scene=False)
        candidate = prefix.with_suffix(".step")
        _fresh_export(package, candidate)
        roundtrip = brep.validate_step_roundtrip_rdescriptor(
            candidate, prefix.with_name(prefix.name + "-roundtrip.step"),
            protected_input_paths=(target,),
        )
        try:
            material = brep.compare_material_rdescriptor(
                target, candidate, include_components=True,
            )
        except (RuntimeError, ValueError) as exc:
            material = {
                "boolean_result_valid": False,
                "strict_equality_supported": False,
                "error": str(exc),
            }
        _write_json(prefix.with_name(prefix.name + "-material.json"), material)
        material_proven = (
            material["boolean_result_valid"]
            and material["strict_equality_supported"]
            and material["missing_material"]["volume"] < 1.0e-9
            and material["excess_material"]["volume"] < 1.0e-9
        )
        try:
            comparison = brep.compare_steps_rbrepcomparison(target, candidate)
        except (RuntimeError, ValueError) as exc:
            iteration_log.append({
                "attempt": number, "hypothesis": operation["api"], "reason": reason,
                "overrides": overrides, "fresh_package_replay": True,
                "roundtrip_passed": roundtrip["passed"],
                "material_proven": material_proven,
                "strict_passed": False, "strict_error": str(exc),
                "package": package.name, "candidate": candidate.name,
            })
            continue
        comparison.write_json(prefix.with_name(prefix.name + "-comparison.json"))
        comparison.write_error_summary_json(prefix.with_name(prefix.name + "-errors.json"))
        iteration_log.append({
            "attempt": number, "hypothesis": operation["api"], "reason": reason,
            "overrides": overrides, "fresh_package_replay": True,
            "roundtrip_passed": roundtrip["passed"],
            "material_proven": material_proven,
            "material_boolean_valid": material["boolean_result_valid"],
            "strict_passed": comparison.hard_gate_passed,
            "target_minus_candidate_volume": comparison.target_minus_candidate_volume,
            "candidate_minus_target_volume": comparison.candidate_minus_target_volume,
            "geometry_labelled_topology_matched": comparison.geometry_labelled_incidence_graph_isomorphic,
            "package": package.name, "candidate": candidate.name,
        })
        if roundtrip["passed"] and material_proven and comparison.hard_gate_passed:
            winner = candidate
            break
    _write_json(reconstruction / "iterations.json", iteration_log)
    if winner is None:
        raise RuntimeError(f"{case}: no accepted candidate; see iterations.json")

    candidate_catalog = brep.inspect_geometric_features_rdescriptor(
        model_or_path=winner, feature_kinds=CONFIG["feature_kinds"],
        tolerance=CONFIG["linear_tolerance"],
        angular_tolerance_degrees=CONFIG["angular_tolerance_degrees"],
        max_features=CONFIG["max_features"],
    )
    candidate_features = candidate_catalog["features"]
    checklist = []
    for target_feature in catalog["features"]:
        matches = [item for item in candidate_features if
                   item["category"] == target_feature["category"] and
                   item["subtype"] == target_feature["subtype"]]
        dimensions_agree = len(matches) == 1 and _dimensions_match(
            target_feature["dimensions"], matches[0]["dimensions"]
        )
        outcome = "built_and_matched" if dimensions_agree else "built_but_mismatched"
        checklist.append({
            "target_feature_id": target_feature["feature_id"],
            "target_category": target_feature["category"],
            "target_entity_ids": target_feature["entity_ids"],
            "target_dimensions": target_feature["dimensions"],
            "target_section_ids": [item["station_id"] for item in hypotheses["hypotheses"][target_feature["feature_id"]]["sections"]],
            "candidate_feature_id": matches[0]["feature_id"] if matches else None,
            "candidate_entity_ids": matches[0]["entity_ids"] if matches else [],
            "candidate_dimensions": matches[0]["dimensions"] if matches else None,
            "dimensions_matched": dimensions_agree,
            "comparison": winner.with_name(winner.stem + "-comparison.json").name,
            "outcome": outcome,
        })
    _write_json(reconstruction / "feature-checklist.json", checklist)
    if any(item["outcome"] != "built_and_matched" for item in checklist):
        raise RuntimeError(f"{case}: recognized feature checklist did not pass")
    verdict = {
        "case": case, "accepted": True, "candidate": str(winner),
        "feature_count": len(checklist), "attempts": len(iteration_log),
        "operation": operation["api"],
        "analysis_package": str(OUT / case / "analysis"),
    }
    _write_json(reconstruction / "verdict.json", verdict)
    return verdict


if __name__ == "__main__":
    for case_id in CASES:
        print(json.dumps(reconstruct_case(case_id), ensure_ascii=False))

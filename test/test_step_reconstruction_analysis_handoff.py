"""R0 handoff gate between the analysis prelude and STEP reconstruction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

import simplecadapi as scad
from simplecadapi.inspect import brep
from simplecadapi.inspect.brep.analysis_package import (
    PACKAGE_JSON_FILES,
    PACKAGE_TEXT_FILES,
)


SDK_VERSION = "test-sdk-1"
CONFIG = {
    "feature_kinds": ["hole", "extrusion", "revolution", "loft", "sweep"],
    "linear_tolerance": 1.0e-6,
    "angular_tolerance_degrees": 0.5,
    "max_features": 100,
    "section_rule": "workflow-deterministic",
}


def _write_step(shape, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = STEPControl_Writer()
    assert writer.Transfer(shape, STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Write(str(path)) == IFSelect_RetDone
    return path


def _box_with_hole():
    hole_axis = gp_Ax2(gp_Pnt(10.0, 8.0, -1.0), gp_Dir(0.0, 0.0, 1.0))
    operation = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeBox(20.0, 16.0, 10.0).Shape(),
        BRepPrimAPI_MakeCylinder(hole_axis, 2.0, 12.0).Shape(),
    )
    operation.Build()
    assert operation.IsDone()
    return operation.Shape()


def _loft():
    first = scad.make_rectangle_rwire(8.0, 4.0, center=(0.0, 0.0, 0.0))
    second = scad.make_rectangle_rwire(3.0, 7.0, center=(1.0, 0.5, 10.0))
    return scad.loft_rsolid([first, second]).wrapped


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(package: Path, target_sha256: str) -> None:
    artifacts = [
        {
            "path": path.relative_to(package).as_posix(),
            "role": path.stem,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "target_sha256": target_sha256,
        }
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.name != "artifact-manifest.json"
    ]
    _write_json(
        package / "artifact-manifest.json",
        {"target_sha256": target_sha256, "artifacts": artifacts},
    )


def _build_package(target: Path, package: Path, config: dict = CONFIG) -> dict:
    """Write a prelude package in the shapes the analysis workflow defines."""

    target_sha256 = _sha256(target)
    catalog = brep.inspect_geometric_features_rdescriptor(
        target,
        feature_kinds=config["feature_kinds"],
        tolerance=config["linear_tolerance"],
        angular_tolerance_degrees=config["angular_tolerance_degrees"],
        max_features=config["max_features"],
    )
    features = catalog["features"]
    package.mkdir(parents=True)
    for name in PACKAGE_TEXT_FILES:
        (package / name).write_text(f"# {name}\n", encoding="utf-8")
    with (package / "parse-report.md").open("a", encoding="utf-8") as stream:
        for feature in features:
            stream.write(f"\n## {feature['feature_id']}\n")
    with (package / "unresolved-features.md").open("a", encoding="utf-8") as stream:
        for face_id in catalog["coverage"]["unowned_face_ids"]:
            stream.write(f"- `{face_id}` owned by no feature\n")
    _write_json(
        package / "analysis-config.json",
        {
            **config,
            "route": "reconstruction_prelude",
            "target_sha256": target_sha256,
            "render_budget": {"max_feature_visual_sets": 10, "timeout_seconds": 60},
        },
    )
    _write_json(
        package / "run-status.json",
        {
            "status": "complete",
            "route": "reconstruction_prelude",
            "sdk_version": SDK_VERSION,
            "failed_phase": None,
            "error_summary": None,
            "target_sha256": target_sha256,
            "gaps": [],
        },
    )
    _write_json(
        package / "target-summary.json",
        {"target_sha256": target_sha256, "summary": brep.inspect_step_rsummary(path=target)},
    )
    _write_json(
        package / "raw-feature-hints.json",
        {"target_sha256": target_sha256, "hints": catalog["raw_feature_hints"]},
    )
    _write_json(package / "feature-index.json", catalog)
    _write_json(
        package / "feature-summary.json",
        {"target_sha256": target_sha256, **catalog["summary"]},
    )
    _write_json(
        package / "reconstruction-hypotheses.json",
        {
            "target_sha256": target_sha256,
            "hypotheses": {
                feature["feature_id"]: feature["reconstruction"]
                for feature in features
                if feature["reconstruction"] is not None
            },
        },
    )
    _write_json(
        package / "loft-sweep-specialist.json",
        {
            "target_sha256": target_sha256,
            "entries": [
                {
                    "feature_id": feature["feature_id"],
                    "roi_entity_ids": feature["entity_ids"],
                    "status": "complete",
                    "reason": None,
                    "specialist_analysis": {},
                }
                for feature in features
                if feature["category"] in {"loft", "sweep"}
            ],
        },
    )
    _write_json(
        package / "section-index.json",
        {"target_sha256": target_sha256, "sections": []},
    )
    _write_json(
        package / "visual-index.json",
        {
            "target_sha256": target_sha256,
            "visuals": [
                {
                    "feature_id": feature["feature_id"],
                    "status": "rendered",
                    "reason": None,
                    "paths": [],
                    "entity_ids": feature["highlight_entity_ids"],
                }
                for feature in features
            ],
        },
    )
    _write_manifest(package, target_sha256)
    return catalog


def _check(package: Path, target: Path, **overrides):
    options = {"expected_config": CONFIG, "sdk_version": SDK_VERSION, **overrides}
    return brep.inspect_analysis_package_rdescriptor(package, target, **options)


def _codes(result) -> set[str]:
    return {failure["code"] for failure in result["hard_failures"]}


def _edit(package: Path, name: str, change) -> None:
    """Change one package file, then re-seal the manifest like a real rerun."""

    path = package / name
    value = _read_json(path)
    change(value)
    _write_json(path, value)
    _write_manifest(package, _read_json(package / "feature-index.json")["target_sha256"])


@pytest.fixture()
def hole_package(tmp_path):
    target = _write_step(_box_with_hole(), tmp_path / "target" / "box.step")
    package = tmp_path / "out" / "analysis"
    catalog = _build_package(target, package)
    return target, package, catalog


def test_complete_package_may_start_reconstruction(hole_package):
    target, package, catalog = hole_package

    result = _check(package, target)

    assert catalog["features"]
    assert result["status"] == "pass"
    assert result["may_start_reconstruction"] is True
    assert result["hard_failures"] == []
    assert result["soft_gaps"] == []
    assert result["target_sha256"] == _sha256(target)
    assert result["checked_artifact_count"] == len(PACKAGE_JSON_FILES) - 1 + len(
        PACKAGE_TEXT_FILES
    )
    assert result["accepted_schema_versions"] == {
        "catalog": ["4.2"],
        "reconstruction": ["1.0"],
    }


def test_loft_package_carries_matching_reconstruction_handoffs(tmp_path):
    target = _write_step(_loft(), tmp_path / "target" / "loft.step")
    package = tmp_path / "out" / "analysis"
    _build_package(target, package)
    hypotheses = _read_json(package / "reconstruction-hypotheses.json")["hypotheses"]

    assert hypotheses
    assert all(item["schema_version"] == "1.0" for item in hypotheses.values())
    assert _check(package, target)["status"] == "pass"

    first = next(iter(hypotheses))
    _edit(
        package,
        "reconstruction-hypotheses.json",
        lambda value: value["hypotheses"][first].update(reconstruction_support="planned"),
    )
    assert "hypothesis_changed" in _codes(_check(package, target))

    _edit(
        package,
        "reconstruction-hypotheses.json",
        lambda value: value["hypotheses"].pop(first),
    )
    assert "hypotheses_mismatch" in _codes(_check(package, target))


def test_changed_target_blocks_reconstruction(hole_package):
    target, package, _ = hole_package
    _write_step(BRepPrimAPI_MakeBox(20.0, 16.0, 11.0).Shape(), target)

    result = _check(package, target)

    assert result["may_start_reconstruction"] is False
    assert "target_hash_mismatch" in _codes(result)
    assert "entity_unresolved" not in _codes(result)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"expected_config": {**CONFIG, "max_features": 50}}, "config_mismatch"),
        ({"expected_config": {**CONFIG, "linear_tolerance": 1.0e-4}}, "config_mismatch"),
        ({"expected_config": {**CONFIG, "extra_key": 1}}, "config_key_missing"),
        ({"sdk_version": "test-sdk-2"}, "sdk_version_mismatch"),
    ],
)
def test_request_mismatch_blocks_reconstruction(hole_package, overrides, code):
    target, package, _ = hole_package

    result = _check(package, target, **overrides)

    assert result["status"] == "fail"
    assert code in _codes(result)


def test_feature_kind_order_does_not_count_as_a_mismatch(hole_package):
    target, package, _ = hole_package
    reordered = {**CONFIG, "feature_kinds": list(reversed(CONFIG["feature_kinds"]))}

    assert _check(package, target, expected_config=reordered)["status"] == "pass"


@pytest.mark.parametrize(
    ("name", "change", "code"),
    [
        (
            "feature-index.json",
            lambda value: value.update(schema_version="4.0"),
            "catalog_schema_unsupported",
        ),
        (
            "feature-index.json",
            lambda value: value.update(truncated=True, complete=False),
            "catalog_incomplete",
        ),
        (
            "feature-index.json",
            lambda value: value["features"][0]["entity_ids"].append("face:9999"),
            "entity_unresolved",
        ),
        (
            "run-status.json",
            lambda value: value.update(status="failed", failed_phase=6),
            "run_not_complete",
        ),
        (
            "run-status.json",
            lambda value: value.pop("sdk_version"),
            "sdk_version_missing",
        ),
    ],
)
def test_stale_or_incomplete_package_blocks_reconstruction(
    hole_package, name, change, code
):
    target, package, _ = hole_package
    _edit(package, name, change)

    result = _check(package, target)

    assert result["may_start_reconstruction"] is False
    assert code in _codes(result)


def test_file_changed_after_sealing_blocks_reconstruction(hole_package):
    target, package, _ = hole_package
    with (package / "parse-report.md").open("a", encoding="utf-8") as stream:
        stream.write("edited after the manifest\n")

    assert "manifest_hash_mismatch" in _codes(_check(package, target))


def test_report_missing_recognized_feature_blocks_reconstruction(hole_package):
    target, package, catalog = hole_package
    feature_id = catalog["features"][0]["feature_id"]
    report = package / "parse-report.md"
    report.write_text(report.read_text(encoding="utf-8").replace(
        f"## {feature_id}", "## omitted"
    ), encoding="utf-8")
    _write_manifest(package, _read_json(package / "feature-index.json")["target_sha256"])

    assert "parse_report_feature_missing" in _codes(_check(package, target))


def test_missing_file_blocks_reconstruction(hole_package):
    target, package, _ = hole_package
    (package / "visual-index.json").unlink()

    result = _check(package, target)

    assert {"missing_file", "manifest_file_missing"} <= _codes(result)


def test_missing_package_or_target_fails_without_raising(tmp_path, hole_package):
    target, package, _ = hole_package

    assert "package_missing" in _codes(_check(tmp_path / "absent", target))
    assert "target_missing" in _codes(_check(package, tmp_path / "absent.step"))


def _skip_first_visual(package: Path) -> str:
    feature_id = _read_json(package / "visual-index.json")["visuals"][0]["feature_id"]

    def change(value):
        value["visuals"][0].update(status="skipped", reason="render budget exceeded")

    _edit(package, "visual-index.json", change)
    return feature_id


def test_declared_visual_gap_passes_as_soft_gate(hole_package):
    target, package, _ = hole_package
    feature_id = _skip_first_visual(package)
    _edit(
        package,
        "run-status.json",
        lambda value: value.update(
            status="complete_with_gaps",
            gaps=[
                {
                    "code": "visual_skipped",
                    "feature_id": feature_id,
                    "reason": "render budget exceeded",
                }
            ],
        ),
    )

    result = _check(package, target)

    assert result["status"] == "pass_with_gaps"
    assert result["may_start_reconstruction"] is True
    assert [gap["feature_id"] for gap in result["soft_gaps"]] == [feature_id]
    assert result["soft_gaps"][0]["code"] == "visual_skipped"


def test_gap_under_complete_status_is_a_hard_failure(hole_package):
    target, package, _ = hole_package
    _skip_first_visual(package)

    assert "undeclared_gaps" in _codes(_check(package, target))


def test_unlisted_gap_is_a_hard_failure(hole_package):
    target, package, _ = hole_package
    _skip_first_visual(package)
    _edit(
        package,
        "run-status.json",
        lambda value: value.update(status="complete_with_gaps", gaps=[]),
    )

    assert "unlisted_gap" in _codes(_check(package, target))


def test_analysis_only_route_cannot_use_gap_status(hole_package):
    target, package, _ = hole_package
    _edit(
        package,
        "run-status.json",
        lambda value: value.update(
            status="complete_with_gaps", route="analysis_only"
        ),
    )

    assert "gap_status_wrong_route" in _codes(_check(package, target))


def test_unowned_faces_must_be_listed_as_unresolved(tmp_path):
    target = _write_step(_box_with_hole(), tmp_path / "target" / "box.step")
    package = tmp_path / "out" / "analysis"
    narrow = {**CONFIG, "feature_kinds": ["sheet_metal"]}
    catalog = _build_package(target, package, narrow)
    unowned = catalog["coverage"]["unowned_face_ids"]

    assert unowned and catalog["coverage"]["owned_face_count"] == 0
    assert _check(package, target, expected_config=narrow)["status"] == "pass"

    (package / "unresolved-features.md").write_text("# none\n", encoding="utf-8")
    _write_manifest(package, catalog["target_sha256"])
    result = _check(package, target, expected_config=narrow)

    assert "unowned_face_unlisted" in _codes(result)
    assert unowned[0] in next(
        failure["detail"]
        for failure in result["hard_failures"]
        if failure["code"] == "unowned_face_unlisted"
    )


def test_catalog_without_coverage_blocks_reconstruction(hole_package):
    target, package, _ = hole_package
    _edit(package, "feature-index.json", lambda value: value.pop("coverage"))

    assert "coverage_missing" in _codes(_check(package, target))


def test_declared_section_gap_passes_as_soft_gate(hole_package):
    target, package, catalog = hole_package
    feature_id = catalog["features"][0]["feature_id"]
    _edit(
        package,
        "section-index.json",
        lambda value: value["sections"].append(
            {
                "section_id": None,
                "feature_id": feature_id,
                "status": "skipped",
                "reason": "section budget exceeded",
            }
        ),
    )
    assert "undeclared_gaps" in _codes(_check(package, target))

    _edit(
        package,
        "run-status.json",
        lambda value: value.update(
            status="complete_with_gaps",
            gaps=[
                {
                    "code": "section_skipped",
                    "feature_id": feature_id,
                    "reason": "section budget exceeded",
                }
            ],
        ),
    )
    result = _check(package, target)

    assert result["status"] == "pass_with_gaps"
    assert [gap["code"] for gap in result["soft_gaps"]] == ["section_skipped"]

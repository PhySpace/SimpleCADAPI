from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeBox

import simplecadapi as scad
from simplecadapi.inverse_engineer.brep import evaluation as benchmark_evaluation
from simplecadapi.kernel.ocp_export import export_step_shapes


_TRUSTED_TEST_PATH = Path(__file__).resolve()


def _config(
    *,
    target_kind: str = "solid",
    sections: tuple[benchmark_evaluation.SectionEvaluationConfig, ...] = (),
) -> benchmark_evaluation.EvaluationConfig:
    return benchmark_evaluation.EvaluationConfig(
        target_kind=target_kind,
        stage_timeout_seconds=30.0,
        material_timeout_seconds=90.0,
        strict_material_tolerance=1.0e-9,
        boundary_linear_deflection=1.0,
        boundary_max_samples=32,
        sections=sections,
        strict_geometric_tolerance=1.0e-7,
    )


def _global_stage() -> dict:
    return {
        "status": "completed",
        "gate_passed": None,
        "elapsed_seconds": 0.01,
        "report": {
            "bounding_box": {"max_absolute_coordinate_delta": 0.0},
            "centroid": {"distance": 0.0},
            "surface_area": {"relative_delta": 0.0},
            "material_body_count": {"delta": 0},
            "volume": {
                "target": 24.0,
                "current": 24.0,
                "absolute_delta": 0.0,
                "relative_delta": 0.0,
            },
        },
        "report_path": None,
        "error": None,
    }


def _strict_material_report(*, supported: bool = True) -> dict:
    return {
        "method": "bidirectional_cut" if supported else "common_volume",
        "missing_material": {"volume": 0.0},
        "excess_material": {"volume": 0.0},
        "boolean_result_valid": True,
        "strict_equality_supported": supported,
        "volume_balance": {"valid": True},
    }


def _inspection(
    *,
    valid: bool = True,
    solid: int = 1,
    shell: int = 1,
    open_shell: int | None = None,
) -> dict:
    payload = {
        "status": "passed" if valid else "failed",
        "gate_passed": valid,
        "elapsed_seconds": 0.01,
        "report": {
            "source": "candidate.step",
            "valid": valid,
            "counts": {
                "solid": solid,
                "shell": shell,
                "open_shell": (
                    open_shell if open_shell is not None else int(solid == 0 and shell > 0)
                ),
                "closed_shell": shell - (
                    open_shell if open_shell is not None else int(solid == 0 and shell > 0)
                ),
                "face_occurrences": 6,
                "edge_occurrences": 24,
                "vertex_occurrences": 48,
                "unique_faces": 6,
                "unique_edges": 12,
                "unique_vertices": 8,
            },
        },
        "report_path": "evaluation/inspection/report.json",
        "error": None,
    }
    return benchmark_evaluation._seal_trusted_evidence(
        payload,
        evidence_kind="inspection",
        context={
            "candidate_path": str(_TRUSTED_TEST_PATH),
            "candidate_sha256": benchmark_evaluation._file_sha256(
                _TRUSTED_TEST_PATH
            ),
        },
    )


def _strict_report(**overrides) -> dict:
    report = {
        "target_minus_candidate_volume": 0.0,
        "candidate_minus_target_volume": 0.0,
        "same_geometric_point_set": True,
        "geometry_labelled_incidence_graph_isomorphic": True,
        "target_graph_nodes_edges": [26, 48],
        "candidate_graph_nodes_edges": [26, 48],
        "geometric_tolerance": 1.0e-7,
        "boolean_volume_tolerance": 1.0e-9,
        "hard_gate_passed": True,
        "diagnostics": {
            "step_validity": {"target": True, "candidate": True},
            "topology_counts": {
                "target": {"face": 6, "edge": 12, "vertex": 8},
                "candidate": {"face": 6, "edge": 12, "vertex": 8},
            },
            "face_edge_topology": {
                "target": [
                    {"edge_ids": [f"edge:{index}" for index in range(4)]}
                    for _ in range(6)
                ],
                "candidate": [
                    {"edge_ids": [f"edge:{index}" for index in range(4)]}
                    for _ in range(6)
                ],
            },
        },
    }
    report.update(overrides)
    return report


def _strict_stage(**report_overrides) -> dict:
    return {
        "status": "passed",
        "gate_passed": True,
        "checks": {"hard_gate": True},
        "report": _strict_report(**report_overrides),
    }


def _write_placeholder_steps(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "target.step"
    candidate = tmp_path / "candidate.step"
    target.write_bytes(b"target")
    candidate.write_bytes(b"candidate")
    return target, candidate


def _classify(**overrides):
    inspection_was_supplied = "candidate_inspection" in overrides
    arguments = {
        "replay_succeeded": True,
        "persistence_succeeded": True,
        "baseline_integrity_passed": True,
        "candidate_bytes_equal_target": False,
        "target_kind": "solid",
        "candidate_inspection": _inspection(),
        "stages": {},
        "strict_topology_requested": False,
        "parameter_representation_required": False,
        "parameter_representation_passed": None,
    }
    arguments.update(overrides)
    inspection_context = benchmark_evaluation._trusted_evidence_context(
        arguments["candidate_inspection"],
        evidence_kind="inspection",
    )
    stages_context = benchmark_evaluation._trusted_evidence_context(
        arguments["stages"],
        evidence_kind="comparison_bundle",
    )
    if (
        stages_context is not None
        and inspection_context is not None
        and not inspection_was_supplied
    ):
        arguments["candidate_inspection"] = benchmark_evaluation._seal_trusted_evidence(
            arguments["candidate_inspection"],
            evidence_kind="inspection",
            context={
                "candidate_path": stages_context["candidate_path"],
                "candidate_sha256": stages_context["candidate_sha256"],
            },
        )
    if not isinstance(arguments["stages"], benchmark_evaluation._TrustedEvidence):
        arguments["stages"] = benchmark_evaluation._seal_trusted_evidence(
            arguments["stages"],
            evidence_kind="comparison_bundle",
            context={
                "target_path": str(_TRUSTED_TEST_PATH),
                "target_sha256": benchmark_evaluation._file_sha256(
                    _TRUSTED_TEST_PATH
                ),
                "candidate_path": str(_TRUSTED_TEST_PATH),
                "candidate_sha256": benchmark_evaluation._file_sha256(
                    _TRUSTED_TEST_PATH
                ),
                "config": {"target_kind": arguments["target_kind"]},
                "diagnostics": False,
                "strict_topology": arguments["strict_topology_requested"],
            },
        )
    return benchmark_evaluation.classify_benchmark_result(**arguments)


def test_comparison_bundle_requests_strict_bidirectional_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []

    def fake_stage(**kwargs):
        requests.append(kwargs["request"])
        if kwargs["name"] == "global":
            return _global_stage()
        if kwargs["name"] == "material":
            assert kwargs["timeout_seconds"] == 90.0
            assert kwargs["request"]["options"] == {
                "boolean_tolerance": None,
                "include_components": True,
            }
            return {
                "status": "completed",
                "gate_passed": None,
                "elapsed_seconds": 0.01,
                "report": _strict_material_report(),
                "report_path": None,
                "error": None,
            }
        raise AssertionError(kwargs["name"])

    monkeypatch.setattr(benchmark_evaluation, "_stage", fake_stage)
    target, candidate = _write_placeholder_steps(tmp_path)
    stages = benchmark_evaluation.run_comparison_bundle(
        _config(),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "evaluation",
    )

    assert [request["task"] for request in requests] == ["global", "material"]
    assert stages["global"]["status"] == "completed"
    assert stages["global"]["gate_passed"] is None
    assert "checks" not in stages["global"]
    assert stages["material"]["strict_point_set_equal"] is True


def test_large_global_differences_do_not_gate_or_skip_strict_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []
    global_stage = _global_stage()
    global_stage["report"].update(
        {
            "bounding_box": {"max_absolute_coordinate_delta": 1.0e9},
            "centroid": {"distance": 1.0e9},
            "surface_area": {"relative_delta": 1.0e9},
            "material_body_count": {"delta": 99},
            "volume": {
                "target": 24.0,
                "current": 2.4e10,
                "absolute_delta": 2.4e10 - 24.0,
                "relative_delta": 1.0e9 - 1.0,
            },
        }
    )

    def fake_stage(**kwargs):
        requests.append(kwargs["request"])
        if kwargs["name"] == "global":
            return global_stage
        if kwargs["name"] == "material":
            return {
                "status": "completed",
                "gate_passed": None,
                "elapsed_seconds": 0.01,
                "report": _strict_material_report(),
                "report_path": None,
                "error": None,
            }
        raise AssertionError(kwargs["name"])

    monkeypatch.setattr(benchmark_evaluation, "_stage", fake_stage)
    target, candidate = _write_placeholder_steps(tmp_path)
    stages = benchmark_evaluation.run_comparison_bundle(
        _config(),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "evaluation",
    )

    assert [request["task"] for request in requests] == ["global", "material"]
    assert stages["global"]["status"] == "completed"
    assert stages["global"]["gate_passed"] is None
    assert "checks" not in stages["global"]
    assert stages["material"]["status"] == "passed"
    assert stages["material"]["gate_passed"] is True
    assert stages["material"]["relative_total_difference"] == pytest.approx(0.0)


def test_sampled_mismatches_are_diagnostics_and_do_not_change_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = benchmark_evaluation.SectionEvaluationConfig(
        section_id="center",
        origin=(0.0, 0.0, 0.0),
        normal=(0.0, 0.0, 1.0),
        samples_per_edge=4,
    )

    def fake_stage(**kwargs):
        if kwargs["name"] == "global":
            return _global_stage()
        if kwargs["name"] == "material":
            return {
                "status": "completed",
                "gate_passed": None,
                "elapsed_seconds": 0.01,
                "report": _strict_material_report(),
                "report_path": None,
                "error": None,
            }
        if kwargs["name"] == "boundary":
            return {
                "status": "completed",
                "gate_passed": None,
                "elapsed_seconds": 0.01,
                "report": {
                    "symmetric": {"hausdorff_approximation": 1.0e9},
                    "target_to_current": {"statistics": {"p95": 1.0e9}},
                    "current_to_target": {"statistics": {"p95": 1.0e9}},
                },
                "report_path": None,
                "error": None,
            }
        if kwargs["name"] == "section-center":
            return {
                "status": "completed",
                "gate_passed": None,
                "elapsed_seconds": 0.01,
                "report": {
                    "target": {"material_area": 100.0, "edge_count": 4},
                    "current": {"material_area": 0.0, "edge_count": 0},
                    "comparison": {
                        "empty_section_mismatch": True,
                        "hausdorff_approximation": 1.0e9,
                    },
                },
                "report_path": None,
                "error": None,
            }
        raise AssertionError(kwargs["name"])

    monkeypatch.setattr(benchmark_evaluation, "_stage", fake_stage)
    target, candidate = _write_placeholder_steps(tmp_path)
    stages = benchmark_evaluation.run_comparison_bundle(
        _config(sections=(section,)),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "evaluation",
        diagnostics=True,
    )

    boundary = stages["boundary"]
    section_stage = stages["sections"]["reports"][0]
    assert boundary["status"] == "completed"
    assert boundary["gate_passed"] is None
    assert "checks" not in boundary
    assert section_stage["status"] == "completed"
    assert section_stage["gate_passed"] is None
    assert section_stage["relative_area_error"] == pytest.approx(1.0)
    assert "checks" not in section_stage
    assert stages["sections"]["status"] == "completed"
    assert stages["sections"]["gate_passed"] is None
    assert _classify(stages=stages) == {
        "classification": "geometry_equivalent",
        "reasons": ["strict_topology_not_requested"],
    }


def test_evaluation_config_validates_closed_contract() -> None:
    section = benchmark_evaluation.SectionEvaluationConfig(
        section_id="center",
        origin=(0.0, 0.0, 0.0),
        normal=(0.0, 0.0, 1.0),
        samples_per_edge=4,
    )
    config = benchmark_evaluation.EvaluationConfig(sections=(section,))

    assert config.sections == (section,)
    assert tuple(config.__dataclass_fields__) == (
        "target_kind",
        "stage_timeout_seconds",
        "material_timeout_seconds",
        "global_max_bbox_delta",
        "global_max_centroid_distance",
        "global_max_relative_volume_error",
        "global_max_relative_area_error",
        "strict_material_tolerance",
        "boundary_linear_deflection",
        "boundary_max_samples",
        "boundary_max_hausdorff",
        "boundary_max_p95",
        "sections",
        "strict_geometric_tolerance",
    )
    assert tuple(section.__dataclass_fields__) == (
        "section_id",
        "origin",
        "normal",
        "tolerance",
        "samples_per_edge",
        "require_nonempty",
        "max_hausdorff",
        "max_relative_area_error",
    )
    with pytest.raises(ValueError, match="at least four"):
        benchmark_evaluation.SectionEvaluationConfig(
            section_id="invalid",
            origin=(0.0, 0.0, 0.0),
            normal=(0.0, 0.0, 1.0),
            samples_per_edge=3,
        )


def test_deprecated_diagnostic_thresholds_are_accepted_but_ignored() -> None:
    config = benchmark_evaluation.EvaluationConfig(
        global_max_bbox_delta=0.0,
        global_max_centroid_distance=0.0,
        global_max_relative_volume_error=0.0,
        global_max_relative_area_error=0.0,
        boundary_max_hausdorff=0.0,
        boundary_max_p95=0.0,
    )
    section = benchmark_evaluation.SectionEvaluationConfig(
        section_id="legacy",
        origin=(0.0, 0.0, 0.0),
        normal=(0.0, 0.0, 1.0),
        require_nonempty=True,
        max_hausdorff=0.0,
        max_relative_area_error=0.0,
    )

    assert config.global_max_bbox_delta == 0.0
    assert section.max_hausdorff == 0.0


@pytest.mark.parametrize("value", [True, 4.0, "4"])
def test_section_samples_per_edge_requires_an_integer(value) -> None:
    with pytest.raises(TypeError, match="samples_per_edge must be an integer"):
        benchmark_evaluation.SectionEvaluationConfig(
            section_id="center",
            origin=(0.0, 0.0, 0.0),
            normal=(0.0, 0.0, 1.0),
            samples_per_edge=value,
        )


@pytest.mark.parametrize("value", [True, 16.0, "16"])
def test_boundary_max_samples_requires_an_integer(value) -> None:
    with pytest.raises(TypeError, match="boundary_max_samples must be an integer"):
        benchmark_evaluation.EvaluationConfig(boundary_max_samples=value)


@pytest.mark.parametrize(
    ("config_type", "field"),
    [
        (benchmark_evaluation.EvaluationConfig, "stage_timeout_seconds"),
        (benchmark_evaluation.EvaluationConfig, "strict_material_tolerance"),
        (benchmark_evaluation.SectionEvaluationConfig, "tolerance"),
    ],
)
def test_numeric_config_fields_reject_booleans(config_type, field) -> None:
    kwargs = {field: True}
    if config_type is benchmark_evaluation.SectionEvaluationConfig:
        kwargs.update(
            section_id="center",
            origin=(0.0, 0.0, 0.0),
            normal=(0.0, 0.0, 1.0),
        )

    with pytest.raises(ValueError, match=field):
        config_type(**kwargs)


def test_evaluation_config_rejects_duplicate_section_ids() -> None:
    section = benchmark_evaluation.SectionEvaluationConfig(
        section_id="center",
        origin=(0.0, 0.0, 0.0),
        normal=(0.0, 0.0, 1.0),
    )

    with pytest.raises(ValueError, match="section IDs must be unique"):
        benchmark_evaluation.EvaluationConfig(sections=(section, section))


def test_identical_solids_produce_real_strict_material_proof(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.step"
    candidate = tmp_path / "candidate.step"
    export_step_shapes(
        [BRepPrimAPI_MakeBox(2.0, 3.0, 4.0).Shape()],
        str(target),
    )
    export_step_shapes(
        [BRepPrimAPI_MakeBox(2.0, 3.0, 4.0).Shape()],
        str(candidate),
    )

    stages = benchmark_evaluation.run_comparison_bundle(
        _config(),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "evaluation",
    )

    material = stages["material"]
    assert material["status"] == "passed"
    assert material["strict_point_set_equal"] is True
    assert material["report"]["method"] == "bidirectional_cut"
    assert material["report"]["strict_equality_supported"] is True
    assert material["report"]["boolean_result_valid"] is True
    assert material["report"]["volume_balance"]["valid"] is True


def test_non_strict_material_estimate_cannot_prove_point_set_equality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_stage(**kwargs):
        if kwargs["name"] == "global":
            return _global_stage()
        return {
            "status": "completed",
            "gate_passed": None,
            "elapsed_seconds": 0.01,
            "report": _strict_material_report(supported=False),
            "report_path": None,
            "error": None,
        }

    monkeypatch.setattr(benchmark_evaluation, "_stage", fake_stage)
    target, candidate = _write_placeholder_steps(tmp_path)
    stages = benchmark_evaluation.run_comparison_bundle(
        _config(),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "evaluation",
    )

    assert stages["material"]["strict_point_set_equal"] is None
    assert stages["material"]["status"] == "failed"
    assert stages["material"]["gate_passed"] is False
    assert stages["material"]["checks"]["strict_equality_supported"] is False


def test_valid_strict_material_residual_proves_point_sets_differ(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _strict_material_report()
    report["missing_material"]["volume"] = 0.01

    def fake_stage(**kwargs):
        if kwargs["name"] == "global":
            return _global_stage()
        return {
            "status": "completed",
            "gate_passed": None,
            "elapsed_seconds": 0.01,
            "report": report,
            "report_path": None,
            "error": None,
        }

    monkeypatch.setattr(benchmark_evaluation, "_stage", fake_stage)
    target, candidate = _write_placeholder_steps(tmp_path)
    stages = benchmark_evaluation.run_comparison_bundle(
        _config(),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "evaluation",
    )

    assert stages["material"]["strict_point_set_equal"] is False
    assert stages["material"]["status"] == "failed"
    assert stages["material"]["gate_passed"] is False
    assert stages["material"]["checks"]["strict_missing_material"] is False


def test_invalid_material_boolean_remains_a_failed_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _strict_material_report()
    report["boolean_result_valid"] = False

    def fake_stage(**kwargs):
        if kwargs["name"] == "global":
            return _global_stage()
        return {
            "status": "completed",
            "gate_passed": None,
            "elapsed_seconds": 0.01,
            "report": report,
            "report_path": None,
            "error": None,
        }

    monkeypatch.setattr(benchmark_evaluation, "_stage", fake_stage)
    target, candidate = _write_placeholder_steps(tmp_path)
    stages = benchmark_evaluation.run_comparison_bundle(
        _config(),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "evaluation",
    )

    assert stages["material"]["status"] == "failed"
    assert stages["material"]["gate_passed"] is False
    assert stages["material"]["strict_point_set_equal"] is None
    assert stages["material"]["checks"]["boolean_result_valid"] is False


def test_material_proof_survives_unavailable_global_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_stage(**kwargs):
        if kwargs["name"] == "global":
            return {
                "status": "error",
                "gate_passed": False,
                "elapsed_seconds": 0.01,
                "report": None,
                "report_path": None,
                "error": "global worker failed",
            }
        return {
            "status": "completed",
            "gate_passed": None,
            "elapsed_seconds": 0.01,
            "report": _strict_material_report(),
            "report_path": None,
            "error": None,
        }

    monkeypatch.setattr(benchmark_evaluation, "_stage", fake_stage)
    target, candidate = _write_placeholder_steps(tmp_path)
    stages = benchmark_evaluation.run_comparison_bundle(
        _config(),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "evaluation",
    )

    assert stages["global"]["status"] == "error"
    assert stages["material"]["status"] == "passed"
    assert stages["material"]["strict_point_set_equal"] is True
    assert stages["material"]["relative_total_difference"] is None


def test_material_timeout_leaves_valid_solid_as_approximation() -> None:
    result = _classify(
        stages={
            "global": {"status": "passed", "gate_passed": True},
            "material": {
                "status": "error",
                "gate_passed": False,
                "error": "evaluation stage timed out",
            },
        },
    )

    assert result == {
        "classification": "approximation",
        "reasons": ["strict_material_equality_unproved"],
    }


def test_failed_material_stage_cannot_claim_strict_equality() -> None:
    result = _classify(
        stages={
            "material": {
                "status": "error",
                "gate_passed": False,
                "strict_point_set_equal": True,
            },
            "strict": {"status": "passed", "gate_passed": True},
        },
        strict_topology_requested=True,
    )

    assert result == {
        "classification": "approximation",
        "reasons": ["strict_material_equality_unproved"],
    }


def test_valid_open_shell_is_approximation_when_equivalence_is_unproved() -> None:
    result = _classify(
        target_kind="open_shell",
        candidate_inspection=_inspection(solid=0, shell=1),
        stages={
            "global": {"status": "passed", "gate_passed": True},
            "material": {"status": "not_applicable", "gate_passed": True},
            "strict": {"status": "not_applicable", "gate_passed": False},
        },
    )

    assert result == {
        "classification": "approximation",
        "reasons": ["open_shell_equivalence_unproved"],
    }


def test_open_shell_still_requires_trusted_comparison_evidence() -> None:
    result = benchmark_evaluation.classify_benchmark_result(
        replay_succeeded=True,
        persistence_succeeded=True,
        baseline_integrity_passed=True,
        candidate_bytes_equal_target=False,
        target_kind="open_shell",
        candidate_inspection=_inspection(solid=0, shell=1),
        stages={},
        strict_topology_requested=False,
        parameter_representation_required=False,
        parameter_representation_passed=None,
    )

    assert result == {
        "classification": "approximation",
        "reasons": ["comparison_evidence_untrusted"],
    }


def test_real_open_shell_reloads_and_classifies_without_fabricating_material(
    tmp_path: Path,
) -> None:
    lower = scad.make_circle_rwire(center=(0.0, 0.0, 0.0), radius=2.0)
    upper = scad.make_circle_rwire(center=(0.0, 0.0, 2.0), radius=1.0)
    shell = scad.loft_rshell(sections=[lower, upper])
    candidate = tmp_path / "candidate.step"
    export_step_shapes([shell.wrapped], str(candidate))

    inspection = benchmark_evaluation.inspect_benchmark_step(
        candidate,
        name="open-shell-inspection",
        output_directory=tmp_path / "evaluation",
        timeout_seconds=30.0,
    )
    stages = benchmark_evaluation.run_comparison_bundle(
        _config(target_kind="open_shell"),
        target_path=candidate,
        candidate_path=candidate,
        output_directory=tmp_path / "comparison",
    )
    report = inspection["report"]
    result = _classify(
        target_kind="open_shell",
        candidate_inspection=inspection,
        stages=stages,
    )

    assert report["counts"]["solid"] == 0
    assert report["counts"]["shell"] == 1
    assert result == {
        "classification": "approximation",
        "reasons": ["open_shell_equivalence_unproved"],
    }


def test_inspection_accepts_valid_multi_root_step(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.step"
    export_step_shapes(
        [
            BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(),
            BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape(),
        ],
        str(candidate),
    )

    inspection = benchmark_evaluation.inspect_benchmark_step(
        candidate,
        name="multi-root-inspection",
        output_directory=tmp_path / "evaluation",
        timeout_seconds=30.0,
    )

    assert inspection["status"] == "passed"
    assert inspection["report"]["counts"]["solid"] == 2


def test_strict_comparison_accepts_identical_multi_root_steps(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    candidate = tmp_path / "candidate.step"
    shapes = [
        BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(),
        BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape(),
    ]
    export_step_shapes(shapes, str(target))
    export_step_shapes(shapes, str(candidate))

    stages = benchmark_evaluation.run_comparison_bundle(
        _config(),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "evaluation",
        strict_topology=True,
    )

    assert stages["material"]["strict_point_set_equal"] is True
    assert stages["strict"]["status"] == "passed"
    assert stages["strict"]["report"]["hard_gate_passed"] is True
    assert _classify(
        stages=stages,
        strict_topology_requested=True,
    ) == {"classification": "exact_brep", "reasons": []}


def test_open_shell_target_rejects_a_fabricated_solid() -> None:
    result = _classify(
        target_kind="open_shell",
        candidate_inspection=_inspection(solid=1, shell=1),
        stages={"global": {"status": "passed", "gate_passed": True}},
    )

    assert result == {
        "classification": "unsupported_or_incomplete",
        "reasons": ["fabricated_solid_for_open_shell"],
    }


def test_strict_topology_failure_does_not_erase_proven_geometry_equivalence() -> None:
    result = _classify(
        stages={
            "global": {"status": "passed", "gate_passed": True},
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": {"status": "error", "gate_passed": False},
        },
        strict_topology_requested=True,
    )

    assert result == {
        "classification": "geometry_equivalent",
        "reasons": ["strict_topology_unproved"],
    }


def test_missing_parameter_representation_does_not_erase_geometry_equivalence() -> None:
    result = _classify(
        stages={
            "global": {"status": "passed", "gate_passed": True},
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": _strict_stage(),
        },
        strict_topology_requested=True,
        parameter_representation_required=True,
        parameter_representation_passed=None,
    )

    assert result == {
        "classification": "geometry_equivalent",
        "reasons": ["parameter_representation_unproved"],
    }


def test_open_shell_target_requires_a_shell_candidate() -> None:
    result = _classify(
        target_kind="open_shell",
        candidate_inspection=_inspection(solid=0, shell=0),
        stages={"global": {"status": "passed", "gate_passed": True}},
    )

    assert result == {
        "classification": "unsupported_or_incomplete",
        "reasons": ["candidate_kind_mismatch"],
    }


def test_solid_target_requires_a_solid_candidate() -> None:
    result = _classify(
        candidate_inspection=_inspection(solid=0, shell=1),
        stages={"global": {"status": "passed", "gate_passed": True}},
    )

    assert result == {
        "classification": "unsupported_or_incomplete",
        "reasons": ["candidate_kind_mismatch"],
    }


def test_open_shell_kind_is_derived_from_trusted_inspection_counts() -> None:
    result = _classify(
        target_kind="open_shell",
        candidate_inspection=_inspection(solid=0, shell=0),
    )

    assert result == {
        "classification": "unsupported_or_incomplete",
        "reasons": ["candidate_kind_mismatch"],
    }


def test_open_shell_target_rejects_an_empty_shell_count_claim() -> None:
    inspection = _inspection(solid=0, shell=1)
    inspection["report"]["counts"]["unique_faces"] = 0

    result = _classify(
        target_kind="open_shell",
        candidate_inspection=inspection,
    )

    assert result == {
        "classification": "unsupported_or_incomplete",
        "reasons": ["candidate_inspection_untrusted"],
    }


def test_strict_material_conflict_does_not_erase_prior_material_proof() -> None:
    result = _classify(
        stages={
            "global": {"status": "passed", "gate_passed": True},
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": {
                "status": "failed",
                "gate_passed": False,
                "report": {
                    "same_geometric_point_set": False,
                    "hard_gate_passed": False,
                },
            },
        },
        strict_topology_requested=True,
    )

    assert result == {
        "classification": "geometry_equivalent",
        "reasons": ["strict_stage_conflicts_with_material_proof"],
    }


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"persistence_succeeded": False}, "step_persistence_failed"),
        ({"baseline_integrity_passed": False}, "baseline_integrity_failed"),
        ({"candidate_bytes_equal_target": True}, "candidate_bytes_equal_target"),
    ],
)
def test_missing_submission_evidence_blocks_classification(override, reason) -> None:
    result = _classify(**override)

    assert result["classification"] == "unsupported_or_incomplete"
    assert reason in result["reasons"]


def test_required_parameter_representation_can_reach_exact_brep() -> None:
    result = _classify(
        stages={
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": _strict_stage(),
        },
        strict_topology_requested=True,
        parameter_representation_required=True,
        parameter_representation_passed=True,
    )

    assert result == {"classification": "exact_brep", "reasons": []}


def test_unsealed_reports_cannot_reach_exact_brep() -> None:
    result = benchmark_evaluation.classify_benchmark_result(
        replay_succeeded=True,
        persistence_succeeded=True,
        baseline_integrity_passed=True,
        candidate_bytes_equal_target=False,
        target_kind="solid",
        candidate_inspection=dict(_inspection()),
        stages={
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": _strict_stage(),
        },
        strict_topology_requested=True,
        parameter_representation_required=False,
        parameter_representation_passed=None,
    )

    assert result == {
        "classification": "unsupported_or_incomplete",
        "reasons": ["candidate_inspection_untrusted"],
    }


def test_mutated_strict_report_invalidates_trusted_bundle() -> None:
    stages = benchmark_evaluation._seal_trusted_evidence(
        {
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": _strict_stage(),
        },
        evidence_kind="comparison_bundle",
        context={
            "target_path": str(_TRUSTED_TEST_PATH),
            "target_sha256": benchmark_evaluation._file_sha256(_TRUSTED_TEST_PATH),
            "candidate_path": str(_TRUSTED_TEST_PATH),
            "candidate_sha256": benchmark_evaluation._file_sha256(
                _TRUSTED_TEST_PATH
            ),
            "config": {"target_kind": "solid"},
            "diagnostics": False,
            "strict_topology": True,
        },
    )
    stages["strict"]["report"]["target_minus_candidate_volume"] = 1.0

    result = _classify(stages=stages, strict_topology_requested=True)

    assert result == {
        "classification": "approximation",
        "reasons": ["comparison_evidence_untrusted"],
    }


def test_comparison_bundle_must_match_inspected_candidate() -> None:
    stages = benchmark_evaluation._seal_trusted_evidence(
        {},
        evidence_kind="comparison_bundle",
        context={
            "target_path": str(_TRUSTED_TEST_PATH),
            "target_sha256": benchmark_evaluation._file_sha256(_TRUSTED_TEST_PATH),
            "candidate_path": "another.step",
            "candidate_sha256": "sha256:not-the-inspection-input",
            "config": {"target_kind": "solid"},
            "diagnostics": False,
            "strict_topology": False,
        },
    )

    result = _classify(stages=stages, candidate_inspection=_inspection())

    assert result == {
        "classification": "approximation",
        "reasons": ["comparison_evidence_context_mismatch"],
    }


def test_changed_candidate_invalidates_exact_evidence(tmp_path: Path) -> None:
    target = tmp_path / "target.step"
    candidate = tmp_path / "candidate.step"
    export_step_shapes([BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()], str(target))
    export_step_shapes([BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()], str(candidate))
    inspection = benchmark_evaluation.inspect_benchmark_step(
        candidate,
        name="candidate-inspection",
        output_directory=tmp_path / "inspection",
        timeout_seconds=30.0,
    )
    stages = benchmark_evaluation.run_comparison_bundle(
        _config(),
        target_path=target,
        candidate_path=candidate,
        output_directory=tmp_path / "comparison",
        strict_topology=True,
    )
    export_step_shapes([BRepPrimAPI_MakeBox(2.0, 1.0, 1.0).Shape()], str(candidate))

    result = benchmark_evaluation.classify_benchmark_result(
        replay_succeeded=True,
        persistence_succeeded=True,
        baseline_integrity_passed=True,
        candidate_bytes_equal_target=False,
        target_kind="solid",
        candidate_inspection=inspection,
        stages=stages,
        strict_topology_requested=True,
        parameter_representation_required=False,
        parameter_representation_passed=None,
    )

    assert result == {
        "classification": "approximation",
        "reasons": ["comparison_evidence_inputs_changed"],
    }


def test_claimed_strict_stage_status_cannot_reach_exact_brep() -> None:
    result = _classify(
        stages={
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": {"status": "passed", "gate_passed": True},
        },
        strict_topology_requested=True,
    )

    assert result == {
        "classification": "geometry_equivalent",
        "reasons": ["strict_topology_unproved"],
    }


def test_strict_report_without_trusted_checks_cannot_reach_exact_brep() -> None:
    strict = _strict_stage()
    strict.pop("checks")
    result = _classify(
        stages={
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": strict,
        },
        strict_topology_requested=True,
    )

    assert result == {
        "classification": "geometry_equivalent",
        "reasons": ["strict_topology_unproved"],
    }


def test_strict_report_must_contain_consistent_exact_brep_evidence() -> None:
    result = _classify(
        stages={
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": _strict_stage(
                geometry_labelled_incidence_graph_isomorphic=False,
            ),
        },
        strict_topology_requested=True,
    )

    assert result == {
        "classification": "geometry_equivalent",
        "reasons": ["strict_topology_unproved"],
    }


def test_failed_strict_report_needs_trusted_evidence_to_disprove_topology() -> None:
    result = _classify(
        stages={
            "material": {
                "status": "passed",
                "gate_passed": True,
                "strict_point_set_equal": True,
            },
            "strict": {
                "status": "failed",
                "gate_passed": False,
                "report": {
                    "same_geometric_point_set": True,
                    "hard_gate_passed": False,
                },
            },
        },
        strict_topology_requested=True,
    )

    assert result == {
        "classification": "geometry_equivalent",
        "reasons": ["strict_stage_conflicts_with_material_proof"],
    }


def test_malformed_inspection_cannot_claim_candidate_validity_or_kind() -> None:
    inspection = _inspection(solid=0, shell=1)
    inspection["report"]["counts"]["shell"] = True

    result = _classify(
        target_kind="open_shell",
        candidate_inspection=inspection,
    )

    assert result == {
        "classification": "unsupported_or_incomplete",
        "reasons": ["candidate_inspection_untrusted"],
    }


def test_stage_resolves_relative_output_before_switching_worker_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    output = Path("evaluation")
    output.mkdir()

    class FakeProcess:
        returncode = 0

        def wait(self, timeout=None):
            return self.returncode

    def fake_popen(command, **kwargs):
        request_path = Path(command[-2])
        report_path = Path(command[-1])
        assert request_path.is_absolute()
        assert report_path.is_absolute()
        assert request_path.parent == report_path.parent
        assert request_path.parent.parent == (tmp_path / "evaluation")
        report_path.write_text("{}", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(benchmark_evaluation.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(benchmark_evaluation, "_create_windows_job", lambda: None)
    result = benchmark_evaluation._stage(
        name="global",
        request={"task": "global"},
        output_directory=output,
        timeout_seconds=1.0,
        python_executable="python",
    )

    assert result["status"] == "completed"


def test_stage_rejects_path_traversal_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="filename-safe"):
        benchmark_evaluation._stage(
            name="../escaped",
            request={"task": "global"},
            output_directory=tmp_path,
            timeout_seconds=1.0,
            python_executable="python",
        )


def test_stage_writes_inside_fresh_exclusive_subdirectories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "evaluation"
    output.mkdir()
    report_directories = []

    class FakeProcess:
        returncode = 0

        def wait(self, timeout=None):
            return self.returncode

    def fake_popen(command, **kwargs):
        report_path = Path(command[-1])
        report_directories.append(report_path.parent)
        report_path.write_text("{}", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(benchmark_evaluation.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(benchmark_evaluation, "_create_windows_job", lambda: None)
    for _ in range(2):
        benchmark_evaluation._stage(
            name="global",
            request={"task": "global"},
            output_directory=output,
            timeout_seconds=1.0,
            python_executable="python",
        )

    assert len(set(report_directories)) == 2
    assert all(path.parent == output for path in report_directories)


def test_stage_returns_structured_failure_when_process_cannot_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_start(*args, **kwargs):
        raise OSError("executable not found")

    monkeypatch.setattr(benchmark_evaluation.subprocess, "Popen", fail_start)

    result = benchmark_evaluation._stage(
        name="global",
        request={"task": "global"},
        output_directory=tmp_path,
        timeout_seconds=1.0,
        python_executable="missing-python",
    )

    assert result["status"] == "error"
    assert result["gate_passed"] is False
    assert result["report"] is None
    assert "failed to start: executable not found" in result["error"]


def test_stage_returns_structured_failure_when_process_isolation_cannot_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_job_creation():
        raise OSError("job unavailable")

    monkeypatch.setattr(
        benchmark_evaluation,
        "_create_windows_job",
        fail_job_creation,
    )

    result = benchmark_evaluation._stage(
        name="global",
        request={"task": "global"},
        output_directory=tmp_path,
        timeout_seconds=1.0,
        python_executable="python",
    )

    assert result["status"] == "error"
    assert result["gate_passed"] is False
    assert result["report"] is None
    assert "failed to start: job unavailable" in result["error"]


def test_stage_timeout_terminates_the_process_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminated = []

    class TimedOutProcess:
        pid = 123
        returncode = None

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("worker", timeout)
            self.returncode = -9
            return self.returncode

    process = TimedOutProcess()
    monkeypatch.setattr(
        benchmark_evaluation.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(benchmark_evaluation, "_create_windows_job", lambda: None)
    monkeypatch.setattr(
        benchmark_evaluation,
        "_terminate_process_tree",
        lambda current, windows_job=None: terminated.append(current),
    )

    result = benchmark_evaluation._stage(
        name="global",
        request={"task": "global"},
        output_directory=tmp_path,
        timeout_seconds=0.01,
        python_executable="python",
    )

    assert terminated == [process]
    assert result["status"] == "error"
    assert "timed out" in result["error"]


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_windows_worker_starts_suspended_before_job_assignment() -> None:
    creationflags = benchmark_evaluation._process_group_options()["creationflags"]

    assert creationflags & benchmark_evaluation._CREATE_SUSPENDED
    assert creationflags & subprocess.CREATE_NEW_PROCESS_GROUP


def test_process_tree_termination_kills_a_spawned_descendant(tmp_path: Path) -> None:
    ready_path = tmp_path / "ready.txt"
    survivor_path = tmp_path / "survivor.txt"
    child_code = (
        "import pathlib,sys,time;"
        "time.sleep(1.0);"
        "pathlib.Path(sys.argv[1]).write_text('survived',encoding='utf-8')"
    )
    parent_code = (
        "import os,pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[3]],"
        "start_new_session=os.name!='nt');"
        "pathlib.Path(sys.argv[2]).write_text(str(child.pid),encoding='utf-8');"
        "time.sleep(30)"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            parent_code,
            child_code,
            str(ready_path),
            str(survivor_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **benchmark_evaluation._process_group_options(),
    )
    windows_job = benchmark_evaluation._create_windows_job()
    try:
        benchmark_evaluation._assign_process_to_windows_job(windows_job, process)
        benchmark_evaluation._resume_windows_process(windows_job, process)
        deadline = time.monotonic() + 5.0
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready_path.exists(), "parent did not spawn its descendant"

        benchmark_evaluation._terminate_process_tree(process, windows_job)
        process.wait(timeout=10.0)
        time.sleep(1.2)

        assert not survivor_path.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10.0)
        benchmark_evaluation._close_windows_job(windows_job)

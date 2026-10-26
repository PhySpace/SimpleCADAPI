"""Contract tests for the STEP computational-geometry analysis workflow."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from simplecadapi.inspect import brep


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "docs" / "skill"
WORKFLOW = (
    SKILL / "references" / "workflows" / "step-computational-geometry-analysis.md"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workflow_exists_and_router_has_one_distinct_analysis_route():
    router = _read(SKILL / "SKILL.md")

    assert WORKFLOW.is_file()
    assert (
        router.count("references/workflows/step-computational-geometry-analysis.md")
        == 1
    )
    assert "Parse a STEP file into a per-instance computational-geometry" in router
    assert "Rebuild an editable model from a STEP file" in router
    assert "read-only" in router


def test_workflow_defines_inputs_phases_gates_failures_and_terminal_boundary():
    text = _read(WORKFLOW)
    prose = re.sub(r"\s+", " ", text.replace("`", ""))

    for heading in (
        "## 1. Scope",
        "## 3. Inputs",
        "## 5. Workflow",
        "## 6. Failure routes",
        "## 7. Deliverables",
        "## 8. Completion gate",
    ):
        assert heading in text
    for phase in range(1, 10):
        assert f"### Phase {phase}:" in text
    assert "Explicit terminal boundary" in text
    assert "geometric_candidate" in text
    assert "not recovered feature history" in prose


def test_workflow_requests_all_v4_feature_kinds_and_declares_complete_catalog_gate():
    text = _read(WORKFLOW)

    for kind in (
        "fillet",
        "chamfer",
        "sheet_metal",
        "hole",
        "extrusion",
        "revolution",
        "loft",
        "sweep",
    ):
        assert f'"{kind}"' in text
    assert "inspect_geometric_features_rdescriptor" in text
    assert "render_geometric_features_rpath" in text
    assert "truncated" in text
    assert "max_features" in text
    assert "highlight_entity_ids" in text
    assert "Visualization consumes saved `feature-index.json`" in text


def test_workflow_lists_required_artifacts_and_forbids_reconstruction_outputs():
    text = _read(WORKFLOW)
    prose = re.sub(r"\s+", " ", text.replace("`", ""))

    for artifact in (
        "analysis-config.json",
        "target-summary.json",
        "raw-feature-hints.json",
        "feature-index.json",
        "feature-summary.json",
        "visual-index.json",
        "section-index.json",
        "sections/data/<section-id>.json",
        "sections/section-atlas.png",
        "artifact-manifest.json",
        "run-status.json",
    ):
        assert artifact in text
    for forbidden in (
        "candidate STEP",
        "model JSON",
        "operation sequence",
        "model audit",
        "strict replay",
        "roundtrip",
        "target/candidate comparison",
        "reconstruction iteration",
    ):
        assert forbidden in prose


def test_workflow_references_exist_and_inspection_domain_registers_renderer():
    text = _read(WORKFLOW)
    domain = _read(SKILL / "references" / "domains" / "step-inspection.md")

    for relative in (
        "references/inspect/brep-reverse-engineering.md",
        "references/domains/step-inspection.md",
        "references/docs/api/inspect_step_rsummary.md",
        "references/docs/api/inspect_geometric_features_rdescriptor.md",
        "references/docs/api/render_geometric_features_rpath.md",
        "references/docs/api/render_region_rpath.md",
        "references/docs/api/inspect_section_rdescriptor.md",
        "references/docs/api/render_sections_rpath.md",
    ):
        assert relative in text
        assert (SKILL / relative).is_file()
    assert "render_sections_rpath" in domain
    assert "step-computational-geometry-analysis.md" in domain


def test_workflow_defines_v4_taxonomy_fields_and_reviewed_palette():
    text = _read(WORKFLOW)

    for subtype in (
        "whole_body_prism",
        "local_boss",
        "rib_or_web",
        "blind_pocket",
        "open_slot_or_notch",
        "through_cut_region",
        "whole_body_full_revolution",
        "whole_body_partial_revolution",
        "local_full_revolved_boss",
        "local_partial_revolved_boss",
        "local_full_revolved_groove",
        "local_partial_revolved_cut",
        "whole_body_profile_loft",
        "whole_body_point_loft",
        "local_lofted_boss",
        "local_lofted_cut",
        "whole_body_path_sweep",
        "local_swept_boss",
        "local_swept_cut",
        "twisted_sweep",
        "helical_sweep",
        "circular_through",
        "circular_blind",
        "counterbore",
        "countersink",
        "circular_stepped",
        "tapered_hole",
        "obround_through",
        "obround_blind",
        "rectangular",
        "polygonal",
        "d_or_keyhole",
        "freeform_profile",
        "profile_stepped",
        "cylindrical_constant",
        "toroidal_constant",
        "spherical_corner",
        "planar_bevel",
        "conical_bevel",
        "flat_sheet_body",
        "formed_sheet_body",
        "cylindrical_bend",
    ):
        assert subtype in text
    for field in (
        "feature_id",
        "category",
        "subtype",
        "display_name",
        "claim",
        "body_id",
        "entity_ids",
        "highlight_entity_ids",
        "support_entity_ids",
        "location",
        "dimensions",
        "profile",
        "relationships",
        "evidence",
        "confidence",
        "visuals",
        "limitations",
        "target_sha256",
    ):
        assert f"`{field}`" in text
    for color in (
        "#29ad57",
        "#06b6d4",
        "#ec4899",
        "#4f46e5",
        "#943dc7",
        "#ef4444",
        "#f2b134",
        "#3b82f6",
        "#f97316",
    ):
        assert color in text
    assert 'category="hole"' in text
    assert "whole-body straight-extrusion candidate" in text


def test_workflow_requires_loop_driven_extrusion_and_meridian_revolution_sections():
    text = _read(WORKFLOW)
    prose = re.sub(r"\s+", " ", text.replace("`", ""))

    assert "complete face area" in prose
    assert "not a required gate" in prose
    assert "25%" in text and "50%" in text and "75%" in text
    assert "meridian" in prose
    assert "0°" in text and "90°" in text and "180°" in text and "270°" in text
    assert "conflict_group_id" in text
    assert "alternative_interpretations" in text


def test_workflow_omits_repository_implementation_log():
    text = _read(WORKFLOW)

    assert "计算几何可视化log.md" not in text
    assert "implementation work" not in text


def test_reviewed_example_generator_is_pinned_to_external_output_root():
    source = _read(ROOT / "tools" / "generate_step_feature_visual_examples.py")

    assert r"D:\Code\step-feat\feat\math-vis-eg" in source
    assert "--output-root" in source
    assert "--v3-only" in source
    assert "--v4-only" in source
    assert all(
        f'"{case_id}"' in source
        for case_id in (
            "E1",
            "E2",
            "E3",
            "E4",
            "E5",
            "E6",
            "R1",
            "R2",
            "R3",
            "R4",
            "R5",
            "R6",
            "A1",
            "A2",
            "N1",
            "N2",
            "N3",
            "N4",
        )
    )
    assert all(
        f'"{case_id}"' in source
        for case_id in ("L1", "L2", "L3", "L4", "S1", "S2", "S3", "S4", "S5")
    )
    assert "inspect_geometric_features_rdescriptor" in source
    assert "render_geometric_features_rpath" in source
    assert "target_sha256" in source and "feature_ids" in source
    assert "artifact-manifest.json" in source
    assert "simplecadapi-dev" not in source


def test_reconstruction_scope_routes_analysis_only_requests_away():
    text = _read(SKILL / "references" / "workflows" / "step-reconstruction.md")

    assert "step-computational-geometry-analysis.md" in text
    assert "evidence and local visual artifacts" in text


def test_analysis_workflow_scopes_termination_to_the_calling_route():
    text = _read(WORKFLOW)
    prose = re.sub(r"\s+", " ", text.replace("`", ""))

    assert "`analysis_only`" in text
    assert "`reconstruction_prelude`" in text
    assert "Route-scoped termination" in text
    assert "applies only to the analysis package directory" in prose
    assert "returns control to R0 of step-reconstruction.md" in prose
    assert "#### Phase 4b:" in text
    assert text.index("### Phase 4:") < text.index("#### Phase 4b:")
    assert text.index("#### Phase 4b:") < text.index("### Phase 5:")
    for artifact in (
        "reconstruction-hypotheses.json",
        "loft-sweep-specialist.json",
    ):
        assert artifact in text


def test_analysis_workflow_declares_versions_gap_status_and_render_budget():
    text = _read(WORKFLOW)
    prose = re.sub(r"\s+", " ", text.replace("`", ""))

    assert "Accepted schema versions" in text
    assert '`feature-index.json` `schema_version`: `"4.2"`' in text
    assert '`reconstruction` handoff `schema_version`: `"1.0"`' in text
    assert "`complete_with_gaps`" in text
    assert "render budget" in prose
    assert "analysis_only runs never use complete_with_gaps" in prose


def test_reconstruction_runs_analysis_prelude_before_feature_inference():
    text = _read(SKILL / "references" / "workflows" / "step-reconstruction.md")
    prose = re.sub(r"\s+", " ", text.replace("`", ""))

    assert "reconstruction_prelude" in text
    for stage in range(8):
        assert f"### R{stage}:" in text
    prelude = text.index("## Analysis prelude")
    assert prelude < text.index("### R0:") < text.index("### R1:")
    assert text.index("### R1:") < text.index("### R7:")
    assert "<absolute-output-directory>/analysis/" in text
    assert "<absolute-output-directory>/reconstruction/" in text
    assert "Inventory the target economically" not in text


def test_reconstruction_requires_report_evidence_and_per_feature_acceptance():
    workflow = _read(SKILL / "references" / "workflows" / "step-reconstruction.md")
    r0 = workflow[workflow.index("### R0:") : workflow.index("### R1:")]
    r3 = workflow[workflow.index("### R3:") : workflow.index("### R4:")]
    r5 = workflow[workflow.index("### R5:") : workflow.index("### R6:")]
    r6 = workflow[workflow.index("### R6:") : workflow.index("### R7:")]
    r7 = workflow[workflow.index("### R7:") : workflow.index("## Validation gates")]
    assert "read `parse-report.md` in full" in r0
    assert "analysis-evidence.md" in r0 and "every catalog `feature_id`" in r0
    assert "analysis-evidence.md" in r3
    assert "For each `feature_id`" in r5
    assert "try another supported operation" in r6
    assert "every in-scope recognized feature" in r7


def test_reconstruction_r0_lists_hard_and_soft_gates():
    text = _read(SKILL / "references" / "workflows" / "step-reconstruction.md")
    prose = re.sub(r"\s+", " ", text.replace("`", ""))

    r0 = text[text.index("### R0:") : text.index("### R1:")]
    for required in (
        "target_sha256",
        "analysis-config.json",
        "schema_version",
        "SDK version",
        "artifact-manifest.json",
        "truncated",
        "feature-index.json",
        "reconstruction-hypotheses.json",
        "loft-sweep-specialist.json",
        "unresolved-features.md",
        "complete_with_gaps",
    ):
        assert required in r0
    assert "Hard gate" in r0 and "Soft gate" in r0
    assert "inspect_analysis_package_rdescriptor" in r0
    assert "may_start_reconstruction" in r0
    assert (
        SKILL / "references" / "docs" / "api" / "inspect_analysis_package_rdescriptor.md"
    ).is_file()
    assert "rerun Phase 1-9" in prose
    assert "never patch a stale package" in prose
    r2 = text[text.index("### R2:") : text.index("### R3:")]
    for capability in ("native", "emulated", "planned", "unsupported"):
        assert f"`{capability}`" in r2


def test_router_and_index_explain_reconstruction_prelude_without_second_route():
    router = _read(SKILL / "SKILL.md")
    index = _read(SKILL / "references" / "README.md")
    prose = re.sub(r"\s+", " ", router.replace("`", ""))

    assert (
        "STEP reconstruction runs the computational-geometry analysis phases "
        "as its prelude"
    ) in prose
    assert "the prelude is not a second route" in prose
    assert "computational-geometry analysis prelude" in index


def test_geometry_guides_consume_the_analysis_package_first():
    for name in (
        "step-reconstruction-geometry-guide.md",
        "step-reconstruction-geometry-guide-cn.md",
    ):
        text = _read(SKILL / "references" / "workflows" / name)
        assert "reconstruction_prelude" in text
        assert "analysis/" in text and "reconstruction/" in text
        assert "feature-index.json" in text
        assert "reconstruction-hypotheses.json" in text
        assert "complete_with_gaps" in text


def test_workflow_is_collected_for_every_skill_build_target():
    module_path = ROOT / "tools" / "skillbuild.py"
    spec = importlib.util.spec_from_file_location("workflow_skillbuild", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    project = module.load_project(ROOT)
    files = module.collect_source_files(
        project.source,
        frozenset(project.targets),
        project.root,
    )

    matching = [
        entry for entry in files if entry.relative == WORKFLOW.relative_to(SKILL)
    ]
    assert len(matching) == 1
    assert matching[0].blocks is None


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_minimal_analysis_artifact_package_ends_before_reconstruction(tmp_path):
    target = tmp_path / "target" / "box-with-through-hole.step"
    output = tmp_path / "analysis"
    target.parent.mkdir(parents=True)
    base = BRepPrimAPI_MakeBox(20.0, 16.0, 10.0).Shape()
    hole_axis = gp_Ax2(gp_Pnt(10.0, 8.0, -1.0), gp_Dir(0.0, 0.0, 1.0))
    operation = BRepAlgoAPI_Cut(
        base,
        BRepPrimAPI_MakeCylinder(hole_axis, 2.0, 12.0).Shape(),
    )
    operation.Build()
    assert operation.IsDone()
    writer = STEPControl_Writer()
    assert writer.Transfer(operation.Shape(), STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Write(str(target)) == IFSelect_RetDone

    target_sha256 = _sha256(target)
    feature_kinds = (
        "fillet",
        "chamfer",
        "sheet_metal",
        "hole",
        "extrusion",
        "revolution",
        "loft",
        "sweep",
    )
    linear_tolerance = 1.0e-6
    angular_tolerance_degrees = 0.5
    max_hints = 100
    output.mkdir()
    (output / "requirement-brief.md").write_text(
        "# STEP computational-geometry analysis\n\n"
        f"- Target: `{target.resolve()}`\n"
        f"- Output: `{output.resolve()}`\n"
        f"- Target SHA-256: `{target_sha256}`\n"
        "- Scope: evidence, highlights, and 2D sections only\n",
        encoding="utf-8",
    )
    _write_json(
        output / "analysis-config.json",
        {
            "target_path": str(target.resolve()),
            "output_path": str(output.resolve()),
            "target_sha256": target_sha256,
            "sdk_version": "test-environment",
            "time": "deterministic-test-run",
            "platform": sys.platform,
            "feature_kinds": list(feature_kinds),
            "linear_tolerance_mm": linear_tolerance,
            "angular_tolerance_degrees": angular_tolerance_degrees,
            "max_hints": max_hints,
            "section_rule": "workflow-deterministic",
        },
    )

    summary = brep.inspect_step_rsummary(path=target)
    _write_json(
        output / "target-summary.json",
        {"target_sha256": target_sha256, "summary": summary},
    )
    hints = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=target,
        feature_kinds=feature_kinds,
        tolerance=linear_tolerance,
        angular_tolerance_degrees=angular_tolerance_degrees,
        max_hints=max_hints,
    )
    assert hints["truncated"] is False
    assert {hint["kind"] for hint in hints["hints"]} >= {
        "hole_region_candidate",
        "extrusion_region_candidate",
    }
    assert all(hint["claim"] == "geometric_candidate" for hint in hints["hints"])
    _write_json(
        output / "manufacturing-hints.json",
        {"target_sha256": target_sha256, "report": hints},
    )
    _write_json(
        output / "feature-index.json",
        {
            "target_sha256": target_sha256,
            "features": [
                {
                    "hint_id": hint["hint_id"],
                    "kind": hint["kind"],
                    "claim": hint["claim"],
                    "body_id": hint["body_id"],
                    "entity_ids": hint["entity_ids"],
                    "highlight_entity_ids": hint["highlight_entity_ids"],
                    "geometry": hint["geometry"],
                    "confidence": hint["confidence"],
                    "evidence": hint["evidence"],
                }
                for hint in hints["hints"]
            ],
        },
    )
    (output / "unresolved-features.md").write_text(
        "# Unresolved features\n\n"
        f"Target SHA-256: `{target_sha256}`\n\n"
        + "\n".join(
            f"- {diagnostic['code']}: {diagnostic.get('failed_checks', [])}"
            for diagnostic in hints["diagnostics"]
        ),
        encoding="utf-8",
    )

    views = ((28.0, -45.0, "isometric"),)
    overview = output / "highlights" / "all-features.png"
    brep.render_manufacturing_hints_rpath(
        model_or_path=target,
        output_path=overview,
        feature_kinds=feature_kinds,
        tolerance=linear_tolerance,
        angular_tolerance_degrees=angular_tolerance_degrees,
        max_hints=max_hints,
        views=views,
        image_size=(4.0, 3.0),
        dpi=60,
    )
    colors = {
        "fillet_region_candidate": "red",
        "chamfer_region_candidate": "yellow",
        "sheet_metal_region_candidate": "blue",
        "sheet_metal_bend_candidate": "orange",
        "hole_region_candidate": "purple",
        "extrusion_region_candidate": "green",
        "revolution_region_candidate": "cyan",
        "loft_region_candidate": "pink",
        "sweep_region_candidate": "indigo",
    }
    highlight_records = []
    for hint in hints["hints"]:
        safe_id = re.sub(r'[<>:"/\\|?*]', "_", hint["hint_id"])
        relative = Path("highlights") / hint["kind"] / f"{safe_id}.png"
        brep.render_region_rpath(
            model_or_path=target,
            entity_ids=hint["highlight_entity_ids"],
            output_path=output / relative,
            title=hint["hint_id"],
            views=views,
            image_size=(4.0, 3.0),
            dpi=60,
        )
        highlight_records.append(
            {
                "hint_id": hint["hint_id"],
                "kind": hint["kind"],
                "color": colors[hint["kind"]],
                "entity_ids": hint["highlight_entity_ids"],
                "path": relative.as_posix(),
                "target_sha256": target_sha256,
            }
        )
    _write_json(
        output / "highlight-index.json",
        {
            "target_sha256": target_sha256,
            "overview": overview.relative_to(output).as_posix(),
            "highlights": highlight_records,
        },
    )

    model_center = np.asarray(summary["bounding_box"]["center"], dtype=float)
    planes = []

    def add_plane(section_id, source, origin, normal, hint_id=None):
        origin_array = np.asarray(origin, dtype=float)
        normal_array = np.asarray(normal, dtype=float)
        normal_array /= np.linalg.norm(normal_array)
        for plane in planes:
            if np.linalg.norm(
                origin_array - np.asarray(plane["origin"])
            ) <= linear_tolerance and abs(
                abs(float(np.dot(normal_array, plane["normal"]))) - 1.0
            ) <= math.sin(
                math.radians(angular_tolerance_degrees)
            ):
                if source not in plane["merged_sources"]:
                    plane["merged_sources"].append(source)
                if hint_id and hint_id not in plane["hint_ids"]:
                    plane["hint_ids"].append(hint_id)
                return
        planes.append(
            {
                "section_id": section_id,
                "source": source,
                "merged_sources": [source],
                "hint_ids": [hint_id] if hint_id else [],
                "origin": origin_array.tolist(),
                "normal": normal_array.tolist(),
                "purpose": "deterministic analysis section",
                "generation_rule": source,
                "target_sha256": target_sha256,
            }
        )

    for hint in hints["hints"]:
        geometry = hint["geometry"]
        if hint["kind"] == "hole_region_candidate":
            direction = np.asarray(geometry["axis"]["direction"], dtype=float)
            direction /= np.linalg.norm(direction)
            axis_point = np.asarray(geometry["axis"]["point"], dtype=float)
            midpoint = (
                axis_point + np.dot(model_center - axis_point, direction) * direction
            )
            globals_by_parallelism = sorted(
                np.eye(3),
                key=lambda axis: abs(float(np.dot(axis, direction))),
            )
            longitudinal_normal = np.cross(globals_by_parallelism[0], direction)
            add_plane(
                f"{hint['hint_id'].replace(':', '_')}_transverse",
                "hole_transverse",
                midpoint,
                direction,
                hint["hint_id"],
            )
            add_plane(
                f"{hint['hint_id'].replace(':', '_')}_longitudinal",
                "hole_longitudinal",
                midpoint,
                longitudinal_normal,
                hint["hint_id"],
            )
        elif hint["kind"] == "extrusion_region_candidate":
            direction = np.asarray(geometry["direction"], dtype=float)
            direction /= np.linalg.norm(direction)
            for fraction in (0.25, 0.5, 0.75):
                origin = (
                    model_center + (fraction - 0.5) * geometry["length"] * direction
                )
                add_plane(
                    f"{hint['hint_id'].replace(':', '_')}_{int(fraction * 100)}",
                    f"extrusion_{int(fraction * 100)}",
                    origin,
                    direction,
                    hint["hint_id"],
                )

    add_plane("global_xy", "global_xy", model_center, (0.0, 0.0, 1.0))
    add_plane("global_xz", "global_xz", model_center, (0.0, 1.0, 0.0))
    add_plane("global_yz", "global_yz", model_center, (1.0, 0.0, 0.0))
    _write_json(
        output / "section-plan.json",
        {"target_sha256": target_sha256, "sections": planes},
    )

    section_descriptors = []
    section_records = []
    titles = []
    for plane in planes:
        section = brep.inspect_section_rdescriptor(
            model_or_path=target,
            origin=plane["origin"],
            normal=plane["normal"],
            tolerance=linear_tolerance,
            compact=False,
        )
        section["section_id"] = plane["section_id"]
        relative = Path("sections") / "data" / f"{plane['section_id']}.json"
        _write_json(
            output / relative,
            {"target_sha256": target_sha256, "section": section},
        )
        section_descriptors.append(section)
        titles.append(
            f"{plane['section_id']} | {plane['source']} | "
            f"{','.join(plane['hint_ids']) or 'global'}"
        )
        section_records.append(
            {
                "section_id": plane["section_id"],
                "panel_index": len(section_records),
                "data_path": relative.as_posix(),
                "source": plane["source"],
                "hint_ids": plane["hint_ids"],
                "target_sha256": target_sha256,
            }
        )
    atlas = output / "sections" / "section-atlas.png"
    brep.render_sections_rpath(
        sections=section_descriptors,
        output_path=atlas,
        titles=titles,
        columns=3,
        image_size_per_panel=(4.0, 3.5),
        dpi=80,
    )
    _write_json(
        output / "section-index.json",
        {
            "target_sha256": target_sha256,
            "atlas": atlas.relative_to(output).as_posix(),
            "sections": section_records,
        },
    )
    (output / "parse-report.md").write_text(
        "# STEP computational-geometry parse report\n\n"
        f"Target SHA-256: `{target_sha256}`\n\n"
        f"Candidates: {hints['summary']['hint_counts']}\n\n"
        f"Highlights: [index](highlight-index.json)\n\n"
        f"Sections: [atlas](sections/section-atlas.png)\n\n"
        "All entries are geometric candidates, not recovered design history.\n",
        encoding="utf-8",
    )
    _write_json(
        output / "run-status.json",
        {
            "status": "complete",
            "failed_stage": None,
            "error_summary": None,
            "target_sha256": target_sha256,
        },
    )

    roles = {
        "requirement-brief.md": "requirement_brief",
        "analysis-config.json": "analysis_config",
        "target-summary.json": "target_summary",
        "manufacturing-hints.json": "authoritative_feature_report",
        "feature-index.json": "feature_index",
        "highlight-index.json": "highlight_index",
        "section-plan.json": "section_plan",
        "section-index.json": "section_index",
        "parse-report.md": "parse_report",
        "unresolved-features.md": "unresolved_features",
        "run-status.json": "run_status",
    }
    artifacts = []
    for path in sorted(path for path in output.rglob("*") if path.is_file()):
        relative = path.relative_to(output).as_posix()
        artifacts.append(
            {
                "path": relative,
                "role": roles.get(relative, "section_or_highlight_artifact"),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "target_sha256": target_sha256,
            }
        )
    _write_json(
        output / "artifact-manifest.json",
        {"target_sha256": target_sha256, "artifacts": artifacts},
    )

    required = {
        "requirement-brief.md",
        "analysis-config.json",
        "target-summary.json",
        "manufacturing-hints.json",
        "feature-index.json",
        "highlight-index.json",
        "section-plan.json",
        "section-index.json",
        "parse-report.md",
        "unresolved-features.md",
        "run-status.json",
        "artifact-manifest.json",
        "highlights/all-features.png",
        "sections/section-atlas.png",
    }
    produced = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert required <= produced
    assert len(highlight_records) == len(hints["hints"])
    assert all((output / record["path"]).is_file() for record in highlight_records)
    merged_sources = {source for plane in planes for source in plane["merged_sources"]}
    assert {
        "hole_transverse",
        "hole_longitudinal",
        "extrusion_25",
        "extrusion_50",
        "extrusion_75",
        "global_xy",
        "global_xz",
        "global_yz",
    } <= merged_sources
    assert len(section_records) == len(planes)
    assert all((output / record["data_path"]).is_file() for record in section_records)
    manifest = json.loads(
        (output / "artifact-manifest.json").read_text(encoding="utf-8")
    )
    assert all(item["target_sha256"] == target_sha256 for item in manifest["artifacts"])
    forbidden_patterns = (
        "*.model.json",
        "operation-sequence.json",
        "model-audit.json",
        "strict-replay-report.json",
        "step-roundtrip-report.json",
        "*-reconstructed.step",
        "*comparison*",
        "*iteration*",
    )
    assert all(not list(output.rglob(pattern)) for pattern in forbidden_patterns)


def test_analysis_workflow_lists_unowned_faces_and_budgets_sections():
    text = _read(WORKFLOW)
    prose = re.sub(r"\s+", " ", text.replace("`", ""))
    reconstruction = _read(SKILL / "references" / "workflows" / "step-reconstruction.md")

    assert "even when recognition reported no diagnostic" in prose
    assert "either owned by a feature or listed in unresolved-features.md" in prose
    assert "section budget" in prose
    assert "section_skipped" in text
    assert 'status: "computed"|"skipped"' in text
    r0 = reconstruction[reconstruction.index("### R0:") : reconstruction.index("### R1:")]
    assert "coverage" in r0 and "unresolved-features.md" in r0

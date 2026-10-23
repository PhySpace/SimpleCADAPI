"""Tests for model-side section evidence (cut, measure, render, pair)."""

from __future__ import annotations

import json
from copy import deepcopy

import numpy as np

import pymupdf
import pytest

import simplecadapi as scad
from simplecadapi.inspect import drawing

TUBE_LENGTH = 50.0
OUTER_RADIUS = 3.5
INNER_RADIUS = 2.5


@pytest.fixture(scope="module")
def tube():
    """Straight tube: OD 7 x wall 1, axis +Y, length 50 (with bore overshoot)."""
    outer_path = scad.make_wire_from_edges_rwire(
        edges=[
            scad.make_segment_redge(start=(0.0, 0.0, 0.0), end=(0.0, TUBE_LENGTH, 0.0))
        ]
    )
    outer_profile = scad.make_face_from_wires_rface(
        outer_wire=scad.make_wire_from_edges_rwire(
            edges=[
                scad.make_circle_redge(
                    center=(0.0, 0.0, 0.0), radius=OUTER_RADIUS, normal=(0.0, 1.0, 0.0)
                )
            ]
        ),
        inner_wires=[],
        normal=(0.0, 1.0, 0.0),
    )
    rod = scad.sweep_rsolid(profile=outer_profile, path=outer_path)

    inner_path = scad.make_wire_from_edges_rwire(
        edges=[
            scad.make_segment_redge(
                start=(0.0, -2.0, 0.0), end=(0.0, TUBE_LENGTH + 2.0, 0.0)
            )
        ]
    )
    inner_profile = scad.make_face_from_wires_rface(
        outer_wire=scad.make_wire_from_edges_rwire(
            edges=[
                scad.make_circle_redge(
                    center=(0.0, -2.0, 0.0),
                    radius=INNER_RADIUS,
                    normal=(0.0, 1.0, 0.0),
                )
            ]
        ),
        inner_wires=[],
        normal=(0.0, 1.0, 0.0),
    )
    bore = scad.sweep_rsolid(profile=inner_profile, path=inner_path)
    return scad.cut_rsolid(rod, bore)


def _diameters(result):
    return sorted(m["value"] for m in result.measurements if m["kind"] == "diameter")


class TestMeasureModelSectionRDimensions:
    def test_transverse_cut_finds_concentric_circles(self, tube):
        result = drawing.measure_model_section_rdimensions(
            tube.wrapped, {"origin": [0.0, 25.0, 0.0], "normal": [0.0, 1.0, 0.0]}
        )

        assert result.closed_contour_count == 2
        diameters = _diameters(result)
        assert diameters[0] == pytest.approx(2.0 * INNER_RADIUS, abs=0.05)
        assert diameters[1] == pytest.approx(2.0 * OUTER_RADIUS, abs=0.05)
        thickness = [
            m["value"] for m in result.measurements if m["kind"] == "thickness"
        ]
        assert any(abs(t - 1.0) < 0.05 for t in thickness)

    def test_longitudinal_cut_finds_wall_strips(self, tube):
        result = drawing.measure_model_section_rdimensions(
            tube.wrapped, {"origin": [0.0, 25.0, 0.0], "normal": [0.0, 0.0, 1.0]}
        )

        assert result.closed_contour_count == 2
        assert _diameters(result) == []
        extents = sorted(
            m["value"] for m in result.measurements if m["kind"].startswith("extent")
        )
        assert any(abs(v - 1.0) < 0.05 for v in extents)
        assert any(abs(v - TUBE_LENGTH) < 0.05 for v in extents)

    def test_write_json_roundtrip(self, tube, tmp_path):
        result = drawing.measure_model_section_rdimensions(
            tube.wrapped, {"origin": [0.0, 25.0, 0.0], "normal": [0.0, 1.0, 0.0]}
        )

        out = result.write_json(tmp_path / "dims.json")
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["closed_contour_count"] == 2
        assert any(m["kind"] == "diameter" for m in payload["measurements"])


class TestRenderModelSectionRPath:
    def test_fixed_output(self, tube, tmp_path):
        transverse = {"origin": [0.0, 25.0, 0.0], "normal": [0.0, 1.0, 0.0]}
        measured = drawing.measure_model_section_rdimensions(tube.wrapped, transverse)
        diameter = next(
            m
            for m in measured.measurements
            if m["kind"] == "diameter" and abs(m["value"] - 2.0 * OUTER_RADIUS) < 0.1
        )
        anchor = [
            diameter["center"][0] + OUTER_RADIUS * 0.7071,
            diameter["center"][1] + OUTER_RADIUS * 0.7071,
        ]

        png = drawing.render_model_section_rpath(
            tube.wrapped,
            transverse,
            dimensions=[
                {
                    "dim_id": "DIM-001",
                    "kind": "diameter",
                    "measured": diameter["value"],
                    "nominal": 2.0 * OUTER_RADIUS,
                    "tol": "+0.2/+0.1",
                    "anchor": anchor,
                }
            ],
            dpi=96,
            out_dir=tmp_path,
            stem="transverse",
        )

        assert png.name == "transverse.png"
        sidecar = json.loads((tmp_path / "transverse.json").read_text(encoding="utf-8"))
        assert sidecar["closed_contour_count"] == 2
        assert sidecar["dimensions"][0]["dim_id"] == "DIM-001"
        assert sidecar["files"] == ["transverse.png"]
        assert png.stat().st_size > 2000

    def test_empty_section_raises(self, tube, tmp_path):
        with pytest.raises(ValueError):
            drawing.render_model_section_rpath(
                tube.wrapped,
                {"origin": [0.0, 25.0, 500.0], "normal": [0.0, 0.0, 1.0]},
                out_dir=tmp_path,
                stem="empty",
            )


PLANE = {"origin": [0.0, 25.0, 0.0], "normal": [0.0, 1.0, 0.0]}
TUBE_SECTION_CHECKS = {
    "expected_origin": [0, 25, 0],
    "expected_normal": [0, 1, 0],
    "expected_x_direction": [0, 0, 1],
    "expected_y_direction": [1, 0, 0],
    "expected_solid_count": 1,
    "expected_face_count": 1,
    "expected_hole_count": 1,
    "material_points": [{"id": "wall", "point": [3, 0]}],
    "void_points": [{"id": "bore", "point": [0, 0]}],
    "point_tolerance_mm": 1e-7,
    "tolerance_basis": "fixture classification precision",
    "evidence": "analytic tube drawing fixture",
}


def _bound_dimension(tube):
    result = drawing.measure_model_section_rdimensions(
        tube.wrapped, PLANE, section_checks=TUBE_SECTION_CHECKS
    )
    record = max(
        (m for m in result.measurements if m["kind"] == "diameter"),
        key=lambda m: m["value"],
    )
    ledger = {
        "dim_id": "DIM-001",
        "feature_id": "outer_wall",
        "view": "A-A",
        "source_id": "fixture-sha256",
        "raw_word_ids": [0],
        "association_evidence": ["leader-0"],
        "datum": "axis-Y",
        "tolerance_basis": "fixture explicit tolerance",
        "tolerance_min": 6.99,
        "tolerance_max": 7.01,
        "nominal": 7,
        "coordinate_status": "verified",
        "value_status": "verified",
        "association_status": "verified",
        "target_geometry": deepcopy(record["target_geometry"]),
        "section_checks": deepcopy(TUBE_SECTION_CHECKS),
        "measurement_contract": {
            "kind": "diameter",
            "definition": "circle_diameter",
            "direction": None,
            "point": None,
            "units": "mm",
            "coordinate_space": "section_local",
        },
    }
    bound = {
        "measurement_id": record["measurement_id"],
        "bound_mm": 1e-5,
        "basis": "test fixture uncertainty assessment",
        "evidence": ["analytic fixture audit"],
    }
    annotation = drawing.build_section_annotation_rrecord(
        record,
        ledger,
        error_assessment=bound,
        anchor=[record["center"][0] + 3.5, record["center"][1]],
    )
    return record, ledger, bound, annotation


def _visual_review(model, plane, ledger, annotation, tmp_path):
    from simplecadapi.inspect.drawing._provenance import file_hash

    png = drawing.render_model_section_rpath(
        model,
        plane,
        dimensions=[annotation],
        validation_ledger=[ledger],
        dpi=72,
        out_dir=tmp_path,
    )
    sidecar = png.with_suffix(".json")
    review = {
        "layout_status": "reviewed",
        "association_status": "verified",
        "evidence": "independent test review",
        **{
            k: annotation[k]
            for k in ("dim_id", "measurement_id", "model_hash", "section_id")
        },
        "render_artifact": {
            "image_path": str(png.resolve()),
            "image_sha256": file_hash(png),
            "sidecar_path": str(sidecar.resolve()),
            "sidecar_sha256": file_hash(sidecar),
        },
    }
    binding = drawing.validate_section_annotations_rreport(
        model, plane, [annotation], [ledger]
    )["dimensions"][0]
    return review, binding


def test_continuous_extrema_and_gap_do_not_depend_on_samples(tube):
    sparse = drawing.measure_model_section_rdimensions(
        tube.wrapped, PLANE, samples_per_edge=6
    )
    dense = drawing.measure_model_section_rdimensions(
        tube.wrapped, PLANE, samples_per_edge=129
    )
    for result in (sparse, dense):
        assert _diameters(result) == pytest.approx([5, 7], abs=1e-9)
        assert sorted(
            m["value"] for m in result.measurements if m["kind"] == "extent_width"
        ) == pytest.approx([5, 7], abs=1e-6)
        gap = next(m for m in result.measurements if m["kind"] == "thickness")
        assert gap["value"] == pytest.approx(1, abs=1e-9)
        assert gap["method"] == "brep_extrema_distance"
        assert gap["association_status"] == "candidate"
        assert all(m["error_bound_mm"] is None for m in result.measurements)
        assert len({m["measurement_id"] for m in result.measurements}) == len(
            result.measurements
        )
    assert sparse.metadata["model_hash"] == dense.metadata["model_hash"]
    assert (
        sparse.measurements[0]["measurement_id"]
        != dense.measurements[0]["measurement_id"]
    )


def test_directional_material_thickness_reports_distinct_intervals(tube):
    result = drawing.measure_model_section_rdimensions(
        tube.wrapped,
        PLANE,
        directional_thickness=[{"id": "radial", "point": [0, 0], "direction": [1, 0]}],
    )
    intervals = [m for m in result.measurements if m["kind"] == "thickness_directional"]
    assert len(intervals) == 2
    assert [m["value"] for m in intervals] == pytest.approx([1, 1], abs=1e-8)
    assert np.asarray([m["span"] for m in intervals]) == pytest.approx(
        np.array([[-3.5, -2.5], [2.5, 3.5]]), abs=1e-8
    )
    with pytest.raises(ValueError, match="nonzero direction"):
        drawing.measure_model_section_rdimensions(
            tube.wrapped,
            PLANE,
            directional_thickness=[{"id": "bad", "point": [0, 0], "direction": [0, 0]}],
        )


def test_independent_annotation_binding_and_negative_cases(tube, tmp_path):
    record, ledger, bound, annotation = _bound_dimension(tube)

    def validate(item, plane=PLANE):
        return drawing.validate_section_annotations_rreport(
            tube.wrapped, plane, [item], [ledger]
        )

    assert validate(annotation)["status"] == "verified"
    assert annotation["measured"] == record["value"]
    for key, value in [
        ("measured", 999),
        ("model_hash", "stale"),
        ("section_id", "stale"),
        ("measurement_id", "invented"),
        ("feature_id", "inner_wall"),
        ("nominal", 999),
        ("tol", "+999"),
        ("units", "pt"),
        ("display_decimals", -1),
        ("anchor", [0, 0]),
        ("anchor_kind", "placeholder"),
        ("target_geometry", {"contours": [999], "edge_indices": [999]}),
    ]:
        bad = {**annotation, key: value}
        assert validate(bad)["status"] == "rejected", key
    assert validate(annotation, {**PLANE, "origin": [0, 26, 0]})["status"] == "rejected"
    raw = {**annotation, "measured": 999}
    png = drawing.render_model_section_rpath(
        tube.wrapped, PLANE, dimensions=[raw], dpi=72, out_dir=tmp_path
    )
    meta = json.loads(png.with_suffix(".json").read_text())
    assert "999" in meta["dimensions"][0]["display_text"][0]
    assert meta["binding_validation"]["status"] == "unverified"
    with pytest.raises(ValueError, match="validation rejected"):
        drawing.render_model_section_rpath(
            tube.wrapped,
            PLANE,
            dimensions=[raw],
            validation_ledger=[ledger],
            out_dir=tmp_path,
        )


def test_precision_and_three_independent_gates(tube, tmp_path):
    record, ledger, bound, annotation = _bound_dimension(tube)
    assess = drawing.assess_dimension_rverdict
    assert assess(ledger, record)["model_measurement"]["status"] == "pending"
    verdict = assess(ledger, record, error_assessment=bound)
    assert verdict["model_measurement"]["status"] == "passed"
    assert verdict["output_expression"]["status"] == "pending"
    assert verdict["status"] == "pending"
    crossing = {**ledger, "tolerance_min": record["value"]}
    assert (
        assess(crossing, record, error_assessment=bound)["model_measurement"]["status"]
        == "pending"
    )
    assert (
        assess(
            {**ledger, "tolerance_max": 6.98, "tolerance_min": 6.9},
            record,
            error_assessment=bound,
        )["model_measurement"]["status"]
        == "failed"
    )
    assert (
        assess(
            ledger,
            {**record, "accuracy_class": "fit_candidate", "fit_residual_rms_mm": 0},
            error_assessment=bound,
        )["model_measurement"]["status"]
        == "pending"
    )
    assert (
        assess(
            {**ledger, "association_status": "ambiguous"},
            record,
            error_assessment=bound,
        )["original_interpretation"]["status"]
        == "pending"
    )
    output, binding = _visual_review(tube.wrapped, PLANE, ledger, annotation, tmp_path)
    assert (
        assess(
            ledger,
            record,
            error_assessment=bound,
            output_evidence=output,
            output_annotation=annotation,
            binding_validation=binding,
        )["status"]
        == "passed"
    )
    partial = assess(
        ledger,
        record,
        error_assessment=bound,
        output_evidence={"layout_status": "reviewed"},
    )
    assert partial["status"] != "passed"
    coverage = drawing.summarize_dimension_coverage_rreport(
        [partial], expected_dim_ids=["DIM-001", "DIM-002"]
    )
    assert coverage["layout_reviewed"]["count"] == 0
    assert coverage["association_verified"]["count"] == 1
    assert coverage["value_verified"]["missing"] == ["DIM-002"]


@pytest.mark.parametrize("dpi", [72, 150, 300])
@pytest.mark.parametrize("plane", [PLANE, {"origin": [0, 25, 0], "normal": [0, 0, 1]}])
def test_section_pixel_roundtrip_layout_and_placeholder(tube, tmp_path, dpi, plane):
    dimensions = [
        {"dim_id": f"DIM-{i}", "measured": 7.00012345, "display_decimals": 5}
        for i in range(16)
    ]
    png = drawing.render_model_section_rpath(
        tube.wrapped, plane, dimensions=dimensions, dpi=dpi, out_dir=tmp_path
    )
    meta = json.loads(png.with_suffix(".json").read_text())
    forward, inverse = np.asarray(meta["local_to_pixel"]), np.asarray(
        meta["pixel_to_local"]
    )
    for point in ([0, 0, 1], [0.231, -0.517, 1], [2.1, 3.2, 1]):
        assert inverse @ forward @ point == pytest.approx(point, abs=1e-10)
    assert meta["plane"]["x_direction"] and meta["plane"]["y_direction"]
    assert meta["layout"]["automatic_status"] == "passed"
    for item in meta["dimensions"]:
        assert item["anchor_kind"] == "placeholder"
        assert item["association_status"] == "unverified"
        assert item["leader_path_pt"] == []
        assert "7.00012" in item["display_text"][0]
        assert item["unrounded_value"] == 7.00012345


def test_ellipse_fit_is_only_candidate_and_extrema_are_continuous():
    import math
    from simplecadapi._cpp.occt.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace,
    )
    from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakePrism
    from simplecadapi._cpp.occt.gp import gp_Ax2, gp_Pnt, gp_Dir, gp_Elips, gp_Vec

    angle = math.radians(27)
    ellipse = gp_Elips(
        gp_Ax2(
            gp_Pnt(0, 0, 5),
            gp_Dir(0, 0, 1),
            gp_Dir(math.cos(angle), math.sin(angle), 0),
        ),
        5,
        4.95,
    )
    wire = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(ellipse).Edge()).Wire()
    # A planar analytic boundary isolates the extrema algorithm from OCCT's
    # separate approximation of plane/extrusion intersections.
    shape = BRepBuilderAPI_MakeFace(wire).Face()
    result = drawing.measure_model_section_rdimensions(
        shape, {"origin": [0, 0, 5], "normal": [0, 0, 1]}, samples_per_edge=6
    )
    fit = next(m for m in result.measurements if m["kind"] == "diameter")
    assert fit["method"] == "least_squares_circle_candidate"
    assert fit["fit_residual_rms_mm"] > 0
    assert fit["error_bound_mm"] is None
    # Local x is global -Y, local y is global X, per the recorded plane basis.
    width = next(m for m in result.measurements if m["kind"] == "extent_width")
    expected = 2 * math.sqrt((5 * math.sin(angle)) ** 2 + (4.95 * math.cos(angle)) ** 2)
    assert width["value"] == pytest.approx(expected, abs=1e-6)
    # OCCT may turn the extruded ellipse's section into an approximate BSpline.
    # Even a continuous bound must NOT claim intersection tolerance as its
    # total error. Keep this upstream error source visible in the evidence.
    solid = BRepPrimAPI_MakePrism(shape, gp_Vec(0, 0, 10)).Shape()
    cut = drawing.measure_model_section_rdimensions(
        solid, {"origin": [0, 0, 10], "normal": [0, 0, 1]}, samples_per_edge=6
    )
    envelope = next(m for m in cut.measurements if m["kind"] == "extent_width")
    assert envelope["error_bound_mm"] is None
    assert (
        drawing.assess_dimension_rverdict(
            {
                "tolerance_min": expected - 1e-6,
                "tolerance_max": expected + 1e-6,
                "tolerance_basis": "analytic extrusion",
            },
            envelope,
        )["model_measurement"]["status"]
        == "pending"
    )


def test_eccentric_gap_and_actual_model_change_invalidate_evidence(tube):
    from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Cut
    from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from simplecadapi._cpp.occt.gp import gp_Ax2, gp_Pnt, gp_Dir

    outer = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)), 3.5, 50
    ).Shape()
    inner = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0.6, -1, 0), gp_Dir(0, 1, 0)), 2.5, 52
    ).Shape()
    changed = BRepAlgoAPI_Cut(outer, inner).Shape()
    result = drawing.measure_model_section_rdimensions(
        changed, PLANE, samples_per_edge=7
    )
    assert next(
        m["value"] for m in result.measurements if m["kind"] == "thickness"
    ) == pytest.approx(0.4, abs=1e-8)
    _, ledger, _, annotation = _bound_dimension(tube)
    assert (
        drawing.validate_section_annotations_rreport(
            changed, PLANE, [annotation], [ledger]
        )["status"]
        == "rejected"
    )


def test_formal_render_records_valid_binding_and_independent_reviews(tube, tmp_path):
    _, ledger, _, annotation = _bound_dimension(tube)
    png = drawing.render_model_section_rpath(
        tube.wrapped,
        PLANE,
        dimensions=[annotation],
        validation_ledger=[ledger],
        dpi=96,
        out_dir=tmp_path,
        stem="formal",
    )
    meta = json.loads(png.with_suffix(".json").read_text())
    assert meta["binding_validation"]["status"] == "verified"
    assert meta["dimensions"][0]["association_status"] == "verified"
    assert len(meta["dimensions"][0]["leader_path_px"]) == 3
    assert meta["layout"]["readability_review"] == "pending"
    assert meta["layout"]["feature_association_review"] == "pending"


def test_material_strategy_retains_its_actual_edges_and_ignores_environment(
    tube, monkeypatch
):
    from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from simplecadapi._cpp.occt.BRepExtrema import BRepExtrema_DistShapeShape
    from simplecadapi._cpp.occt.gp import gp_Pnt
    from simplecadapi.inspect.drawing._section_geometry import section_geometry

    monkeypatch.setenv("SIMPLECADAPI_MATERIAL_SECTION", "1")
    legacy, _ = section_geometry(tube.wrapped, PLANE, section_strategy="edges")
    assert legacy["contour_method"] == "section_edges"
    material, edges = section_geometry(
        tube.wrapped,
        PLANE,
        section_strategy="material",
        section_checks=TUBE_SECTION_CHECKS,
    )
    assert material["validation"]["status"] == "passed"
    assert material["contour_method"] == "material_face_intersection"
    for edge in material["edges"]:
        for point in edge["samples_3d"][::13]:
            distance = BRepExtrema_DistShapeShape(
                BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex(), edges[edge["index"]]
            )
            assert distance.IsDone() and distance.Value() < 1e-7


def test_non_latin_section_labels_record_font(tube, tmp_path):
    png = drawing.render_model_section_rpath(
        tube.wrapped,
        PLANE,
        dimensions=[{"dim_id": "壁厚", "measured": 1}],
        dpi=72,
        out_dir=tmp_path,
    )
    metadata = json.loads(png.with_suffix(".json").read_text())
    assert metadata["dimensions"][0]["fontname"] == "china-s"
    assert metadata["layout"]["automatic_status"] == "passed"


def test_evidence_cli_rereads_step_and_keeps_visual_review_separate(tube, tmp_path):
    import subprocess
    import sys
    from types import SimpleNamespace
    from simplecadapi._cpp.occt.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from simplecadapi._cpp.occt.IFSelect import IFSelect_RetDone

    writer = STEPControl_Writer()
    writer.Transfer(tube.wrapped, STEPControl_AsIs)
    step = tmp_path / "model.step"
    assert writer.Write(str(step)) == IFSelect_RetDone
    _, ledger, _, annotation = _bound_dimension(SimpleNamespace(wrapped=str(step)))
    review, _ = _visual_review(str(step), PLANE, ledger, annotation, tmp_path)
    evidence = {
        "plane": PLANE,
        "ledger": [ledger],
        "annotations": [annotation],
        "output_reviews": {"DIM-001": review},
    }
    evidence_path, report_path = tmp_path / "evidence.json", tmp_path / "report.json"
    evidence_path.write_text(json.dumps(evidence))
    command = [
        sys.executable,
        "tools/verify_drawing_evidence.py",
        "--model",
        str(step),
        "--evidence",
        str(evidence_path),
        "--out",
        str(report_path),
    ]
    run = subprocess.run(command, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(report_path.read_text())["status"] == "passed"
    evidence["output_reviews"] = {}
    evidence_path.write_text(json.dumps(evidence))
    assert subprocess.run(command, capture_output=True).returncode == 1
    assert (
        json.loads(report_path.read_text())["dimensions"][0]["output_expression"][
            "status"
        ]
        == "pending"
    )
    evidence["annotations"][0]["measured"] = 999
    evidence_path.write_text(json.dumps(evidence))
    assert subprocess.run(command, capture_output=True).returncode == 1
    assert (
        json.loads(report_path.read_text())["binding_validation"]["status"]
        == "rejected"
    )


def test_section_basis_mismatch_is_not_silently_ignored(tube):
    with pytest.raises(ValueError, match="canonical section basis"):
        drawing.measure_model_section_rdimensions(
            tube.wrapped, {**PLANE, "x_direction": [1, 0, 0]}
        )

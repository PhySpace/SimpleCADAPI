"""Real BREP cases for cavities, dense fillets, section direction and fit limits."""

from copy import deepcopy
import hashlib
import io
import json
import math
import re

import numpy as np
import pymupdf
import pytest
from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Cut
from simplecadapi._cpp.occt.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_MakeFace,
)
from simplecadapi._cpp.occt.BRepFilletAPI import BRepFilletAPI_MakeFillet
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi._cpp.occt.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakePrism,
)
from simplecadapi._cpp.occt.Geom import Geom_Circle, Geom_TrimmedCurve
from simplecadapi._cpp.occt.TopAbs import TopAbs_EDGE
from simplecadapi._cpp.occt.TopExp import TopExp_Explorer
from simplecadapi._cpp.occt.TopoDS import TopoDS
from simplecadapi._cpp.occt.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Vec

from simplecadapi.inspect import drawing
from simplecadapi.inspect.drawing._circle_fit import fit_circle_diagnostics
from simplecadapi.inspect.drawing.section import _fit_circle
from simplecadapi.inspect.drawing._section_geometry import section_geometry
from simplecadapi.inspect.drawing._section_validation import validate_section
from simplecadapi.inspect.drawing._material_geometry import material_section_geometry


@pytest.fixture(scope="module")
def perforated_fillet_plate():
    shape = BRepPrimAPI_MakeBox(40, 30, 6).Shape()
    for x in (8, 20, 32):
        for y in (8, 22):
            drill = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(x, y, -1), gp_Dir(0, 0, 1)),
                1.5 if (x, y) == (8, 8) else 2,
                8,
            ).Shape()
            shape = BRepAlgoAPI_Cut(shape, drill).Shape()
    operation = BRepFilletAPI_MakeFillet(shape)
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    count = 0
    while explorer.More():
        operation.Add(0.4, TopoDS.Edge_s(explorer.Current()))
        count += 1
        explorer.Next()
    operation.Build()
    assert count >= 30 and operation.IsDone()
    shape = operation.Shape()
    assert BRepCheck_Analyzer(shape).IsValid()
    return shape


def plate_case(direction):
    z_cut = abs(direction[2]) == 1
    origin = [0, 0, 0.2] if z_cut else [0, 8, 0]
    axes = {
        (0, 0, 1): ([0, -1, 0], [1, 0, 0]),
        (0, 0, -1): ([0, 1, 0], [1, 0, 0]),
        (0, 1, 0): ([0, 0, 1], [1, 0, 0]),
        (0, -1, 0): ([0, 0, -1], [1, 0, 0]),
    }
    x_axis, y_axis = axes[tuple(direction)]

    def local(world):
        delta = np.asarray(world) - origin
        return [float(np.dot(delta, x_axis)), float(np.dot(delta, y_axis))]

    material = (
        [[4, 4, 0.2], [10, 8, 0.2]] if z_cut else [[x, 8, 3] for x in (4, 14, 26, 36)]
    )
    void = (
        [[x, y, 0.2] for x in (8, 20, 32) for y in (8, 22)]
        if z_cut
        else [[x, 8, 3] for x in (8, 20, 32)]
    )
    checks = {
        "expected_origin": origin,
        "expected_normal": direction,
        "expected_x_direction": x_axis,
        "expected_y_direction": y_axis,
        "expected_solid_count": 1,
        "expected_face_count": 1 if z_cut else 4,
        "expected_hole_count": 6 if z_cut else 0,
        "material_points": [
            {"id": f"M{i}", "point": local(p)} for i, p in enumerate(material)
        ],
        "void_points": [{"id": f"V{i}", "point": local(p)} for i, p in enumerate(void)],
        "point_tolerance_mm": 1e-7,
        "tolerance_basis": "fixture point classification precision",
        "evidence": "independently specified six-hole plate drawing fixture",
    }
    return {"origin": origin, "normal": direction}, checks


@pytest.mark.parametrize("strategy", ["auto", "material", "edges"])
@pytest.mark.parametrize("direction", [[0, 0, 1], [0, 0, -1], [0, 1, 0], [0, -1, 0]])
def test_real_fillet_plate_cavities_and_view_directions(
    perforated_fillet_plate, strategy, direction, tmp_path
):
    plane, checks = plate_case(direction)
    result = drawing.measure_model_section_rdimensions(
        perforated_fillet_plate, plane, section_strategy=strategy, section_checks=checks
    )
    assert result.section_validation["status"] == "passed", result.section_validation
    assert result.configuration["contour_method"] == (
        "section_edges" if strategy == "edges" else "material_face_intersection"
    )
    for probe in result.section_validation["probes"]:
        assert (
            probe["model"] == probe["section"] == probe["display"] == probe["expected"]
        )
    png = drawing.render_model_section_rpath(
        perforated_fillet_plate,
        plane,
        section_strategy=strategy,
        section_checks=checks,
        out_dir=tmp_path,
        dpi=96,
    )
    sidecar = json.loads(png.with_suffix(".json").read_text())
    assert sidecar["section_validation"]["status"] == "passed"
    pixels = pymupdf.Pixmap(png)
    transform = np.asarray(sidecar["local_to_pixel"])
    for probe in checks["void_points"]:
        x, y, _ = transform @ [*probe["point"], 1]
        # The bore center is far from every real boundary. Hatch must not fill it.
        assert (
            min(
                pixels.pixel(i, j)[0]
                for i in range(int(x) - 2, int(x) + 3)
                for j in range(int(y) - 2, int(y) + 3)
            )
            > 245
        )
    if abs(direction[2]) == 1:
        # This hatch point borders the smaller, asymmetric bore. Its mirrored
        # location would be void at the larger bore, exposing a mirrored view.
        x, y, _ = transform @ [*checks["material_points"][1]["point"], 1]
        assert (
            min(
                pixels.pixel(i, j)[0]
                for i in range(int(x) - 2, int(x) + 3)
                for j in range(int(y) - 2, int(y) + 3)
            )
            < 220
        )


def test_wrong_direction_missing_void_coverage_and_boundary_probes(
    perforated_fillet_plate,
):
    plane, checks = plate_case([0, 0, 1])
    bad = deepcopy(checks)
    bad["expected_normal"] = [0, 0, -1]
    result = drawing.measure_model_section_rdimensions(
        perforated_fillet_plate, plane, section_checks=bad
    )
    assert any(
        f["owner"] == "section_definition"
        for f in result.section_validation["failures"]
    )
    bad = deepcopy(checks)
    bad["void_points"] = bad["void_points"][:1]
    result = drawing.measure_model_section_rdimensions(
        perforated_fillet_plate, plane, section_checks=bad
    )
    assert result.section_validation["status"] == "pending"
    assert any("every hole" in s for s in result.section_validation["missing"])
    # A boundary point cannot stand in for a material-interior observation.
    box = BRepPrimAPI_MakeBox(10, 10, 2).Shape()
    plane = {"origin": [0, 0, 1], "normal": [0, 0, 1]}
    bad.update(
        expected_origin=[0, 0, 1],
        expected_hole_count=0,
        expected_face_count=1,
        material_points=[{"id": "boundary", "point": [0, 5]}],
        void_points=[],
    )
    result = drawing.measure_model_section_rdimensions(box, plane, section_checks=bad)
    assert any("boundary" in s for s in result.section_validation["missing"])


def test_distinguish_wrong_model_material_from_corrupt_display(perforated_fillet_plate):
    plane, checks = plate_case([0, 0, 1])
    solid_plate = BRepPrimAPI_MakeBox(40, 30, 6).Shape()
    wrong = drawing.measure_model_section_rdimensions(
        solid_plate, plane, section_checks=checks
    )
    assert any(
        f["owner"] == "model_geometry_or_requirement"
        for f in wrong.section_validation["failures"]
    )
    section, _ = section_geometry(perforated_fillet_plate, plane, section_checks=checks)
    material, _, faces, holes = material_section_geometry(
        perforated_fillet_plate, section, 64, 1e-7
    )
    broken = deepcopy(section)
    broken["contours"] = [c for c in broken["contours"] if c["role"] != "hole"]
    report = validate_section(
        perforated_fillet_plate, broken, material, faces, holes, checks
    )
    assert report["status"] == "failed"
    assert any(f["owner"] == "section_display" for f in report["failures"])
    assert not any(
        f["owner"] == "model_geometry_or_requirement" for f in report["failures"]
    )


def arc_wire(start, end):
    circle = Geom_Circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 10)
    return BRepBuilderAPI_MakeWire(
        BRepBuilderAPI_MakeEdge(Geom_TrimmedCurve(circle, start, end)).Edge()
    ).Wire()


@pytest.mark.parametrize("angle", [math.radians(120), 2 * math.pi - 0.01])
def test_real_partial_arc_and_gapped_contour_are_diagnostic_only(angle, tmp_path):
    wire = arc_wire(0, angle)
    plane = {"origin": [0, 0, 0], "normal": [0, 0, 1]}
    result = drawing.measure_model_section_rdimensions(
        wire, plane, section_strategy="edges"
    )
    assert result.open_contour_count > 0
    assert not any(m["kind"] == "diameter" for m in result.measurements)
    assert all(d["status"] == "open_contour" for d in result.circle_diagnostics)
    png = drawing.render_model_section_rpath(
        wire, plane, section_strategy="edges", out_dir=tmp_path, dpi=72
    )
    meta = json.loads(png.with_suffix(".json").read_text())
    assert meta["evidence_status"] == "diagnostic_only"
    assert not meta["section_validation"]["basic"]["section_closed"]


def test_nonuniform_samples_do_not_use_point_mean_as_circle_center():
    angles = np.r_[
        np.linspace(0, 0.03, 1000), np.linspace(0, 2 * math.pi, 80, endpoint=False)
    ]
    points = np.column_stack((10 * np.cos(angles) + 14, 10 * np.sin(angles) - 8))
    assert np.linalg.norm(points.mean(axis=0) - [14, -8]) > 9
    x, y, r, residual = _fit_circle(points)
    assert [x, y, r] == pytest.approx([14, -8, 10], abs=1e-10)
    assert residual < 1e-12
    diagnostics = fit_circle_diagnostics(points)
    assert diagnostics["coverage_degrees"] > 350
    assert diagnostics["residual_max_mm"] < 1e-10


def test_full_solid_with_unequal_circular_edges_recovers_center_and_diameter():
    circle = Geom_Circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 10)
    knots = np.r_[np.linspace(0, 0.1, 31), math.pi, 2 * math.pi]
    wire = BRepBuilderAPI_MakeWire()
    for a, b in zip(knots, knots[1:]):
        wire.Add(
            BRepBuilderAPI_MakeEdge(
                Geom_TrimmedCurve(circle, float(a), float(b))
            ).Edge()
        )
    solid = BRepPrimAPI_MakePrism(
        BRepBuilderAPI_MakeFace(wire.Wire()).Face(), gp_Vec(0, 0, 4)
    ).Shape()
    plane = {"origin": [0, 0, 2], "normal": [0, 0, 1]}
    for strategy in ("edges", "material"):
        section, _ = section_geometry(
            solid, plane, samples_per_edge=16, section_strategy=strategy
        )
        points = np.asarray(section["contours"][0]["samples_2d"])
        assert np.linalg.norm(points.mean(axis=0)) > 8
        result = drawing.measure_model_section_rdimensions(
            solid, plane, samples_per_edge=16, section_strategy=strategy
        )
        diameter = next(m for m in result.measurements if m["kind"] == "diameter")
        assert diameter["method"] == "analytic_circle"
        assert diameter["center"] == pytest.approx([0, 0], abs=1e-8)
        assert diameter["value"] == pytest.approx(20, abs=1e-8)
        fit = result.circle_diagnostics[0]
        assert fit["center"] == pytest.approx([0, 0], abs=1e-8)
        assert fit["residual_max_mm"] < 1e-8


@pytest.mark.parametrize(
    "points",
    [
        np.column_stack((np.arange(20), np.zeros(20))),
        np.column_stack((np.arange(20), 1e-9 * np.sin(np.arange(20)))),
        np.ones((20, 2)),
    ],
)
def test_collinear_nearly_collinear_and_repeated_points_are_rejected(points):
    fit = fit_circle_diagnostics(points)
    assert fit["status"] == "degenerate" and fit["radius"] is None
    assert math.isinf(_fit_circle(points)[3])


def test_short_arc_residual_does_not_establish_full_circle():
    angles = np.linspace(0, math.pi / 3, 200)
    fit = fit_circle_diagnostics(
        np.column_stack((10 * np.cos(angles), 10 * np.sin(angles)))
    )
    assert fit["residual_rms_mm"] < 1e-10
    assert fit["coverage_degrees"] == pytest.approx(60)
    assert fit["status"] == "insufficient_coverage"
    assert fit["error_bound_mm"] is None


def test_nearly_collinear_real_solid_section_does_not_become_circle():
    solid = BRepPrimAPI_MakeBox(20, 1e-6, 2).Shape()
    result = drawing.measure_model_section_rdimensions(
        solid, {"origin": [0, 0, 1], "normal": [0, 0, 1]}
    )
    assert result.closed_contour_count == 1
    assert not any(m["kind"] == "diameter" for m in result.measurements)
    assert result.circle_diagnostics[0]["status"] == "degenerate"


def test_closed_notched_tube_is_not_promoted_to_full_circle():
    tube = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeCylinder(10, 4).Shape(), BRepPrimAPI_MakeCylinder(8, 4).Shape()
    ).Shape()
    notch = BRepPrimAPI_MakeBox(gp_Pnt(0, -1, -1), 12, 2, 6).Shape()
    solid = BRepAlgoAPI_Cut(tube, notch).Shape()
    result = drawing.measure_model_section_rdimensions(
        solid, {"origin": [0, 0, 2], "normal": [0, 0, 1]}
    )
    assert result.closed_contour_count == 1
    assert not any(m["kind"] == "diameter" for m in result.measurements)
    assert result.circle_diagnostics[0]["status"] != "analytic_circle"


def test_formal_evidence_requires_independent_complete_section_checks(tmp_path):
    from test_drawing_evidence_contracts import (
        fixture,
        ledger_for,
        contract,
        annotate,
        reviewed_evidence,
    )
    from test_drawing_evidence_contracts import verify

    model, records = fixture()
    record = records["extent_width"]
    row = ledger_for(record, contract("extent_width", [1, 0]), 20)
    annotation = annotate(record, row)
    evidence = reviewed_evidence(model, row, annotation, tmp_path)
    assert verify(model, evidence)["status"] == "passed"
    row["section_checks"]["expected_normal"] = [0, 0, -1]
    assert verify(model, evidence)["status"] != "passed"
    with pytest.raises(ValueError, match="section"):
        drawing.render_model_section_rpath(
            model,
            evidence["plane"],
            dimensions=[annotation],
            validation_ledger=[row],
            out_dir=tmp_path,
        )
    record = drawing.measure_model_section_rdimensions(
        model, evidence["plane"]
    ).measurements[0]
    assert record["section_validation"]["status"] == "pending"


def test_formal_render_rejects_sampling_that_misdisplays_material(tmp_path):
    from test_drawing_evidence_contracts import ledger_for, contract, uncertainty

    model = BRepPrimAPI_MakeCylinder(10, 2).Shape()
    plane = {"origin": [0, 0, 1], "normal": [0, 0, 1]}
    # At r=9 this point is safely inside the circle, but outside the triangle
    # produced by a four-sample display. Independent solid classification stays IN.
    point = [9 * math.cos(math.pi / 3), 9 * math.sin(math.pi / 3)]
    checks = {
        "expected_origin": [0, 0, 1],
        "expected_normal": [0, 0, 1],
        "expected_x_direction": [0, -1, 0],
        "expected_y_direction": [1, 0, 0],
        "expected_solid_count": 1,
        "expected_face_count": 1,
        "expected_hole_count": 0,
        "material_points": [{"id": "M", "point": point}],
        "void_points": [],
        "point_tolerance_mm": 1e-7,
        "tolerance_basis": "independent interior point precision",
        "evidence": "circle fixture",
    }
    result = drawing.measure_model_section_rdimensions(
        model, plane, section_checks=checks
    )
    record = next(m for m in result.measurements if m["kind"] == "diameter")
    row = ledger_for(record, contract("diameter", None, "circle_diameter"), 20)
    annotation = drawing.build_section_annotation_rrecord(
        record, row, error_assessment=uncertainty(record), anchor=[10, 0]
    )
    with pytest.raises(ValueError, match="section_display"):
        drawing.render_model_section_rpath(
            model,
            plane,
            dimensions=[annotation],
            validation_ledger=[row],
            samples_per_edge=4,
            out_dir=tmp_path,
        )
    assert not (tmp_path / "section.png").exists()


def test_invalid_strategy_and_material_on_open_wire_are_explicit():
    wire = arc_wire(0, math.pi)
    plane = {"origin": [0, 0, 0], "normal": [0, 0, 1]}
    for strategy in ("material", "invalid"):
        with pytest.raises(ValueError, match="strategy"):
            drawing.measure_model_section_rdimensions(
                wire, plane, section_strategy=strategy
            )


def test_expected_solid_count_uses_original_model_before_material_union():
    from simplecadapi._cpp.occt.BRep import BRep_Builder
    from simplecadapi._cpp.occt.TopoDS import TopoDS_Compound
    from test_drawing_evidence_contracts import box_checks

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(10, 20, 2).Shape())
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(5, 0, 0), 10, 20, 2).Shape())
    checks = box_checks()
    result = drawing.measure_model_section_rdimensions(
        compound, {"origin": [0, 0, 1], "normal": [0, 0, 1]}, section_checks=checks
    )
    assert result.section_validation["basic"]["solid_count"] == 2
    assert any(
        f["reason"] == "unexpected solid_count"
        for f in result.section_validation["failures"]
    )


@pytest.mark.parametrize("strategy", ["edges", "material"])
def test_section_diagnostics_preserve_model_geometry(perforated_fillet_plate, strategy):
    from simplecadapi.inspect.drawing._provenance import model_metadata

    before = model_metadata(perforated_fillet_plate)["model_hash"]
    plane, checks = plate_case([0, 0, 1])
    drawing.measure_model_section_rdimensions(
        perforated_fillet_plate,
        plane,
        section_strategy=strategy,
        section_checks=checks,
        directional_thickness=[
            {"id": "wall-line", "point": [-4, 4], "direction": [1, 0]}
        ],
    )
    assert model_metadata(perforated_fillet_plate)["model_hash"] == before


def _brep_bytes(shape):
    from simplecadapi._cpp.occt.BRepTools import BRepTools
    from simplecadapi._cpp.occt.TopTools import TopTools_FormatVersion

    stream = io.BytesIO()
    BRepTools.Write_s(
        shape,
        stream,
        False,
        False,
        TopTools_FormatVersion.TopTools_FormatVersion_VERSION_3,
    )
    return stream.getvalue()


def _overlapping_boxes(count=2):
    from simplecadapi._cpp.occt.BRep import BRep_Builder
    from simplecadapi._cpp.occt.TopoDS import TopoDS_Compound

    bodies = [
        BRepPrimAPI_MakeBox(gp_Pnt(5 * i, 0, 0), 10, 20, 2).Shape()
        for i in range(count)
    ]
    root = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(root)
    for body in bodies:
        builder.Add(root, body)
    return root, bodies


def _assert_brep_unchanged(root, bodies, snapshots):
    # Bytes cover the 2D curve table and all other persistent BREP data. Check
    # constituent solids as well: a shallow compound copy still shares them.
    for shape, before in zip([root, *bodies], snapshots):
        after = _brep_bytes(shape)
        counts = [
            re.search(rb"^Curve2ds (\d+)", data, re.MULTILINE).group(1)
            for data in (before, after)
        ]
        assert (
            before == after
        ), f"input BREP changed; Curve2ds {counts[0]} -> {counts[1]}"


@pytest.mark.parametrize(
    "strategy", [None, "edges", "material"], ids=["default", "edges", "material"]
)
@pytest.mark.parametrize("indexed_input", [False, True], ids=["raw", "indexed"])
def test_overlapping_multibody_section_preserves_original_brep(
    strategy, indexed_input, tmp_path
):
    from simplecadapi.inspect.brep import index_shape_rbrepmodel

    root, bodies = _overlapping_boxes()
    snapshots = [_brep_bytes(shape) for shape in [root, *bodies]]
    original_hash = hashlib.sha256(snapshots[0]).hexdigest()
    model = index_shape_rbrepmodel(shape=root) if indexed_input else root
    plane = {"origin": [0, 0, 1], "normal": [0, 0, 1]}
    options = {} if strategy is None else {"section_strategy": strategy}
    _assert_brep_unchanged(root, bodies, snapshots)
    for _ in range(2):
        result = drawing.measure_model_section_rdimensions(
            model=model, plane=plane, **options
        )
        _assert_brep_unchanged(root, bodies, snapshots)
        assert result.metadata["model_hash"] == original_hash
        assert result.metadata["source_id"] == original_hash
        assert all(m["model_hash"] == original_hash for m in result.measurements)
        assert result.closed_contour_count == 1
        assert {m["kind"]: m["value"] for m in result.measurements}[
            "extent_height"
        ] == pytest.approx(15, abs=1e-6)
    png = drawing.render_model_section_rpath(
        model=model, plane=plane, out_dir=tmp_path, dpi=72, **options
    )
    _assert_brep_unchanged(root, bodies, snapshots)
    assert (
        json.loads(png.with_suffix(".json").read_text())["model_hash"] == original_hash
    )


@pytest.mark.parametrize("count", [2, 3])
def test_material_union_preserves_inputs_on_cold_and_cached_calls(count):
    from simplecadapi._cpp.occt.TopAbs import TopAbs_SOLID
    from simplecadapi.inspect.brep import index_shape_rbrepmodel

    root, bodies = _overlapping_boxes(count)
    snapshots = [_brep_bytes(shape) for shape in [root, *bodies]]
    indexed = index_shape_rbrepmodel(shape=root)
    merged = indexed._material_union()
    _assert_brep_unchanged(root, bodies, snapshots)
    assert BRepCheck_Analyzer(merged).IsValid()
    explorer = TopExp_Explorer(merged, TopAbs_SOLID)
    solid_count = 0
    while explorer.More():
        solid_count += 1
        explorer.Next()
    assert solid_count == 1
    assert indexed._material_union().IsSame(merged)
    _assert_brep_unchanged(root, bodies, snapshots)

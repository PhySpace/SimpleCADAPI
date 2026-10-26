from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import simplecadapi as scad
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_Transform,
)
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.Geom import Geom_BezierSurface
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TColStd import TColStd_Array2OfReal
from OCP.TColgp import TColgp_Array2OfPnt
from OCP.TopoDS import TopoDS_Compound
from OCP.gp import gp_Ax2, gp_Dir, gp_Elips, gp_Pnt, gp_Trsf, gp_Vec
from simplecadapi.kernel.ocp_export import export_step_shapes
from simplecadapi.inspect import brep
import simplecadapi.inspect.brep.compare as compare_module


def _box():
    return scad.make_box_rsolid(width=4.0, height=3.0, depth=2.0)


def _two_arc_cylinder():
    first = scad.make_angle_arc_redge(
        center=(0.0, 0.0, 0.0),
        radius=1.0,
        start_angle=0.0,
        end_angle=math.pi,
        normal=(0.0, 0.0, 1.0),
    )
    second = scad.make_angle_arc_redge(
        center=(0.0, 0.0, 0.0),
        radius=1.0,
        start_angle=math.pi,
        end_angle=2.0 * math.pi,
        normal=(0.0, 0.0, 1.0),
    )
    wire = scad.make_wire_from_edges_rwire(edges=[first, second])
    face = scad.make_face_from_wire_rface(wire=wire, normal=(0.0, 0.0, 1.0))
    return scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=2.0)


def test_inspect_namespace_is_public_and_not_top_level_flattened():
    assert scad.inspect.brep is brep
    assert "inspect" in scad.__all__
    assert not hasattr(scad, "inspect_step_rsummary")


def test_inspection_tools_reject_active_model_graph():
    shape = _box().wrapped

    with scad.GraphSession():
        with pytest.raises(RuntimeError, match="cannot run inside an active GraphSession"):
            brep.inspect_shape_rbrepinspection(shape=shape)


def test_inspect_shape_reports_unique_and_occurrence_counts():
    report = brep.inspect_shape_rbrepinspection(_box().wrapped)

    assert report.valid is True
    assert report.counts["unique_faces"] == 6
    assert report.counts["unique_edges"] == 12
    assert report.counts["unique_vertices"] == 8
    assert report.counts["edge_occurrences"] == 24
    assert report.surface_type_counts == {"Plane": 6}
    assert report.edge_type_counts == {"Line": 12}
    assert report.volume == pytest.approx(24.0)


def test_indexed_model_preserves_agent_entity_contract():
    model = brep.index_shape_rbrepmodel(_box().wrapped, source="box.step")
    summary = model.summary()

    assert summary["model_path"] == "box.step"
    assert summary["length_unit"] == "mm"
    assert summary["root_shape_type"] == "Solid"
    assert summary["body_count"] == 1
    assert summary["material_body_count"] == 1
    assert summary["face_count"] == 6
    assert summary["edge_count"] == 12
    assert summary["vertex_count"] == 8
    assert summary["volume"] == pytest.approx(24.0)
    assert summary["surface_area"] == pytest.approx(52.0)
    assert summary["centroid"] == pytest.approx([0.0, 0.0, 1.0])
    assert summary["surface_type_statistics"] == {"PLANE": 6}
    assert summary["curve_type_statistics"] == {"LINE": 12}
    assert summary["entity_id_format"]["face"] == "face:<zero-based-index>"
    assert "parameter_groups" not in summary

    body = model.describe_entity("solid:0")
    assert body["entity_id"] == "body:0"
    assert body["geometry"]["volume"] == pytest.approx(24.0)
    assert len(body["adjacency"]["faces"]) == 6

    face = model.describe_entity("F0")
    assert face["entity_id"] == "face:0"
    assert face["geometry"]["type"] == "PLANE"
    assert face["geometry"]["normal_at_center"] is not None
    assert len(face["adjacency"]["edges"]) == 4
    assert len(face["adjacency"]["neighboring_faces"]) == 4

    edge = model.describe_entity(face["adjacency"]["edges"][0])
    assert edge["geometry"]["type"] == "LINE"
    assert edge["geometry"]["length"] > 0.0
    assert len(edge["adjacency"]["vertices"]) == 2
    assert edge["adjacency"]["faces"]

    vertex = model.describe_entity(edge["adjacency"]["vertices"][0])
    assert vertex["geometry"]["type"] == "POINT"
    assert len(vertex["adjacency"]["edges"]) == 3
    assert len(vertex["adjacency"]["faces"]) == 3


def test_model_summary_parameter_groups_are_bounded_and_non_inferential():
    model = brep.index_shape_rbrepmodel(_box().wrapped, source="box.step")

    summary = model.summary(
        include_parameter_groups=True,
        max_parameter_groups=1,
        examples_per_group=2,
    )
    groups = summary["parameter_groups"]

    assert groups["pattern_inference"] == "not_performed"
    assert "not proof" in groups["interpretation"]
    assert groups["surfaces"]["groups"] == [
        {
            "geometry_type": "PLANE",
            "parameters": {},
            "count": 6,
            "example_entity_ids": ["face:0", "face:1"],
        }
    ]
    assert groups["curves"]["groups"] == [
        {
            "geometry_type": "LINE",
            "parameters": {},
            "count": 12,
            "example_entity_ids": ["edge:0", "edge:1"],
        }
    ]


def test_canonical_axis_group_is_invariant_to_carrier_location():
    direction = (1.0, 1.0, 1.0)
    distance = 1000.0 / math.sqrt(3.0)

    assert brep.model._canonical_axis((0.0, 0.0, 0.0), direction) == (
        brep.model._canonical_axis((distance, distance, distance), direction)
    )


def test_canonical_direction_ignores_components_below_group_precision():
    assert brep.model._canonical_direction((2.0e-12, 1.0, 0.0)) == (
        brep.model._canonical_direction((-2.0e-12, 1.0, 0.0))
    )


def test_indexed_model_reports_analytic_surface_parameters():
    cylinder = scad.make_cylinder_rsolid(radius=5.0, height=10.0)
    model = brep.index_shape_rbrepmodel(cylinder.wrapped)
    cylinder_id = next(
        f"face:{index}"
        for index in range(len(model.faces))
        if model.describe_entity(f"face:{index}")["geometry"]["type"] == "CYLINDER"
    )

    descriptor = model.describe_entity(cylinder_id)

    assert descriptor["geometry"]["parameters"]["radius"] == pytest.approx(5.0)
    assert descriptor["geometry"]["parameters"]["axis"]["direction"] == pytest.approx(
        [0.0, 0.0, 1.0]
    )


def test_indexed_model_reports_edge_endpoint_derivatives_and_exact_curve_definition():
    edge = scad.make_spline_redge(
        control_points=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 1.0, 0.0),
            (3.0, 1.0, 0.0),
        ],
        degree=3,
    )
    descriptor = brep.index_shape_rbrepmodel(edge.wrapped).describe_entity(
        "edge:0",
        include_curve_definition=True,
    )
    geometry = descriptor["geometry"]
    parameters = geometry["parameters"]
    differentials = geometry["endpoint_differentials"]

    assert [value for point in parameters["control_points"] for value in point] == (
        pytest.approx([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 2.0, 1.0, 0.0, 3.0, 1.0, 0.0])
    )
    assert parameters["degree"] == 3
    assert parameters["knot_values"] == pytest.approx([0.0, 1.0])
    assert parameters["multiplicities"] == [4, 4]
    assert parameters["weights"] is None
    assert differentials["derivative_parameterization"] == (
        "edge_oriented_curve_parameter"
    )
    assert differentials["start"]["point"] == pytest.approx([0.0, 0.0, 0.0])
    assert differentials["start"]["d1"] == pytest.approx([3.0, 0.0, 0.0])
    assert differentials["start"]["d2"] == pytest.approx([0.0, 6.0, 0.0])
    assert differentials["start"]["d3"] == pytest.approx([0.0, -12.0, 0.0])
    assert differentials["start"]["unit_tangent"] == pytest.approx([1.0, 0.0, 0.0])
    assert differentials["start"]["outward_unit_tangent"] == pytest.approx(
        [-1.0, 0.0, 0.0]
    )
    assert differentials["end"]["point"] == pytest.approx([3.0, 1.0, 0.0])
    assert differentials["end"]["outward_unit_tangent"] == pytest.approx(
        [1.0, 0.0, 0.0]
    )


def test_indexed_model_reports_ellipse_major_axis_direction():
    ellipse = gp_Elips(
        gp_Ax2(
            gp_Pnt(1.0, 2.0, 3.0),
            gp_Dir(0.0, 0.0, 1.0),
            gp_Dir(0.0, 1.0, 0.0),
        ),
        5.0,
        2.0,
    )
    edge = BRepBuilderAPI_MakeEdge(ellipse).Edge()

    parameters = brep.index_shape_rbrepmodel(edge).describe_entity("edge:0")["geometry"][
        "parameters"
    ]

    assert parameters["x_direction"] == pytest.approx([0.0, 1.0, 0.0])


def test_indexed_model_reports_bounded_surface_definition_only_on_opt_in():
    profile = scad.make_rectangle_rface(1.0, 0.3)
    solid = scad.twisted_sweep_rsolid(profile, distance=2.0, twist_angle=90.0)
    model = brep.index_shape_rbrepmodel(solid.wrapped)
    face_id = next(
        f"face:{index}"
        for index in range(len(model.faces))
        if model.describe_entity(f"face:{index}")["geometry"]["type"] == "BSPLINE"
    )

    default = model.describe_entity(face_id)
    detailed = model.describe_entity(
        face_id,
        include_surface_definition=True,
        max_surface_control_points=32,
    )
    parameters = detailed["geometry"]["parameters"]

    assert "control_points" not in default["geometry"]["parameters"]
    assert parameters["surface_definition_scope"] == "untrimmed_carrier"
    assert parameters["control_point_count"] == (
        parameters["u_pole_count"] * parameters["v_pole_count"]
    )
    assert len(parameters["control_points"]) == parameters["u_pole_count"]
    assert len(parameters["control_points"][0]) == parameters["v_pole_count"]
    assert len(parameters["u_knot_values"]) == parameters["u_knot_count"]
    assert len(parameters["v_knot_values"]) == parameters["v_knot_count"]

    with pytest.raises(brep.BRepEntityError, match="control points; maximum is 1"):
        model.describe_entity(
            face_id,
            include_surface_definition=True,
            max_surface_control_points=1,
        )


def test_indexed_model_reports_rational_bezier_surface_definition():
    poles = TColgp_Array2OfPnt(1, 2, 1, 2)
    weights = TColStd_Array2OfReal(1, 2, 1, 2)
    for u_index in (1, 2):
        for v_index in (1, 2):
            poles.SetValue(
                u_index,
                v_index,
                gp_Pnt(
                    float(u_index - 1),
                    float(v_index - 1),
                    0.2 if (u_index, v_index) == (2, 2) else 0.0,
                ),
            )
            weights.SetValue(
                u_index,
                v_index,
                2.0 if (u_index, v_index) == (2, 2) else 1.0,
            )
    surface = Geom_BezierSurface(poles, weights)
    face = BRepBuilderAPI_MakeFace(surface, 1.0e-7).Face()

    parameters = brep.index_shape_rbrepmodel(face).describe_entity(
        "face:0",
        include_surface_definition=True,
    )["geometry"]["parameters"]

    assert parameters["rational"] is True
    assert parameters["weights"] == [[1.0, 1.0], [1.0, 2.0]]


def test_indexed_model_handles_degenerate_edges():
    model = brep.index_shape_rbrepmodel(scad.make_sphere_rsolid(radius=5.0).wrapped)
    degenerate = next(
        model.describe_entity(f"edge:{index}")
        for index in range(len(model.edges))
        if model.describe_entity(f"edge:{index}")["geometry"]["type"] == "DEGENERATE"
    )

    assert degenerate["geometry"]["length"] == 0.0
    assert degenerate["geometry"]["tangent_at_midpoint"] is None
    assert degenerate["geometry"]["degenerated"] is True
    assert degenerate["geometry"]["underlying_curve_type"] is not None


def test_indexed_model_rejects_bad_entity_ids():
    model = brep.index_shape_rbrepmodel(_box().wrapped)

    with pytest.raises(brep.BRepEntityError, match="Entity id must look"):
        model.describe_entity("not-an-entity")
    with pytest.raises(brep.BRepEntityError, match="out of range"):
        model.describe_entity("face:100")


def test_entity_inspection_parity_accepts_existing_report_schema():
    shape = _box().wrapped
    report = brep.inspect_shape_rbrepinspection(shape).to_dict()
    parity = brep.compare_model_to_inspection_rentityinspectionparity(
        brep.index_shape_rbrepmodel(shape, source="box.step"),
        report,
    )

    assert parity.valid is True
    assert parity.issues == ()
    assert parity.checked_faces == 6
    assert parity.checked_edges == 12
    assert parity.degenerate_edges == 0


def test_entity_inspection_parity_reports_mismatch():
    shape = _box().wrapped
    report = brep.inspect_shape_rbrepinspection(shape).to_dict()
    report["volume"] += 1.0

    parity = brep.compare_model_to_inspection_rentityinspectionparity(brep.index_shape_rbrepmodel(shape), report)

    assert parity.valid is False
    assert any(issue.startswith("volume:") for issue in parity.issues)


def test_entity_inspection_parity_handles_extra_report_entities():
    report = brep.inspect_shape_rbrepinspection(_box().wrapped).to_dict()
    model = brep.index_shape_rbrepmodel(scad.make_cylinder_rsolid(1.0, 2.0).wrapped)

    parity = brep.compare_model_to_inspection_rentityinspectionparity(model, report)

    assert parity.valid is False
    assert parity.checked_faces == min(len(model.faces), len(report["faces"]))
    assert any(issue.startswith("face_records:") for issue in parity.issues)


def test_entity_inspection_parity_uses_raw_root_properties():
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    first = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(1.0, 0.0, 0.0))
    second = BRepBuilderAPI_Transform(first, transform, True).Shape()
    builder.Add(compound, first)
    builder.Add(compound, second)
    report = brep.inspect_shape_rbrepinspection(compound).to_dict()

    parity = brep.compare_model_to_inspection_rentityinspectionparity(
        brep.index_shape_rbrepmodel(compound),
        report,
    )

    assert parity.valid is True


def test_inspect_bspline_edge_includes_reconstruction_parameters():
    wire = scad.make_spline_rwire(
        control_points=[
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (2.0, 1.0, 0.0),
            (3.0, 0.0, 0.0),
        ],
        degree=3,
    )

    report = brep.inspect_shape_rbrepinspection(wire.wrapped)
    spline = report.edges[0]

    assert spline["type"] == "BSplineCurve"
    assert spline["degree"] == 3
    assert spline["poles"] == 4
    assert len(spline["control_points"]) == 4
    assert len(spline["knot_values"]) == spline["knots"]
    assert len(spline["multiplicities"]) == spline["knots"]


def test_compare_same_shape_passes_geometry_and_topology():
    shape = _box().wrapped
    comparison = brep.compare_shapes_rbrepcomparison(shape, shape)

    assert comparison.same_geometric_point_set is True
    assert comparison.geometry_labelled_incidence_graph_isomorphic is True
    assert comparison.hard_gate_passed is True
    assert comparison.target_minus_candidate_volume == 0.0
    assert comparison.candidate_minus_target_volume == 0.0
    assert comparison.diagnostics["step_validity"] == {
        "target": True,
        "candidate": True,
    }
    assert comparison.diagnostics["bounding_box"]["equal"] is True
    assert comparison.diagnostics["topology_counts"]["equal"] is True
    assert comparison.diagnostics["surface_types"]["equal"] is True
    assert comparison.diagnostics["curve_types"]["equal"] is True
    assert comparison.diagnostics["acceptance_standard_changed"] is False
    diagnostic_state = comparison.to_error_summary()
    assert diagnostic_state["errors"] == []
    assert diagnostic_state["root_cause_groups"] == []


def test_comparison_error_summary_reports_all_errors_by_common_cause():
    target = _box().wrapped
    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(1.0, 0.0, 0.0))
    candidate = BRepBuilderAPI_Transform(target, transform, True).Shape()
    comparison = brep.compare_shapes_rbrepcomparison(target, candidate)
    diagnostic_state = comparison.to_error_summary()

    codes = [error["code"] for error in diagnostic_state["errors"]]
    assert "bounding_box_mismatch" in codes
    assert "material_point_set_mismatch" in codes
    assert len(diagnostic_state["errors"]) > 1
    assert any(
        group["group_id"] == "root_cause.datum_scale_placement"
        for group in diagnostic_state["root_cause_groups"]
    )
    assert diagnostic_state["iteration_policy"] == {
        "all_errors_reported": True,
        "group_by_common_root_cause": True,
        "single_error_only": False,
        "single_code_change_only": False,
        "fresh_direct_replay_export_compare_required": True,
    }


def test_compare_normalizes_duplicate_solid_material():
    solid = BRepPrimAPI_MakeBox(2.0, 3.0, 4.0).Shape()
    duplicate = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(duplicate)
    builder.Add(duplicate, solid)
    builder.Add(duplicate, solid)

    comparison = brep.compare_shapes_rbrepcomparison(duplicate, solid)

    assert comparison.same_geometric_point_set is True
    assert comparison.target_minus_candidate_volume == 0.0
    assert comparison.candidate_minus_target_volume == 0.0


def test_strict_material_comparison_uses_direct_cuts_despite_volume_cancellation():
    target = BRepPrimAPI_MakeBox(1.0e6, 1.0e6, 1.0e6).Shape()
    notch = BRepPrimAPI_MakeBox(
        gp_Pnt(999999.0, 999999.0, 999999.0),
        1.0,
        1.0,
        1.0,
    ).Shape()
    cut = BRepAlgoAPI_Cut(target, notch)
    assert cut.IsDone()
    candidate = cut.Shape()

    volume_only = brep.compare_material_rdescriptor(
        target,
        candidate,
        include_components=False,
    )
    strict = brep.compare_shapes_rbrepcomparison(
        target,
        candidate,
        boolean_volume_tolerance=0.5,
    )

    assert volume_only["missing_material"]["volume"] == 0.0
    assert strict.target_minus_candidate_volume == pytest.approx(1.0)
    assert strict.same_geometric_point_set is False


def test_strict_comparison_recomputes_untrusted_precomputed_volumes():
    target = BRepPrimAPI_MakeBox(10.0, 1.0, 1.0).Shape()
    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(0.09, 0.0, 0.0))
    candidate = BRepBuilderAPI_Transform(target, transform, True).Shape()

    comparison = brep.compare_shapes_rbrepcomparison(
        target,
        candidate,
        material_difference_volumes=(0.0, 0.0),
    )

    assert comparison.target_minus_candidate_volume == pytest.approx(0.09)
    assert comparison.candidate_minus_target_volume == pytest.approx(0.09)
    assert comparison.same_geometric_point_set is False


def test_fuzzy_strict_comparison_cannot_claim_material_equality():
    target = BRepPrimAPI_MakeBox(1000.0, 1.0, 1.0).Shape()
    candidate = BRepPrimAPI_MakeBox(999.91, 1.0, 1.0).Shape()

    comparison = brep.compare_shapes_rbrepcomparison(
        target,
        candidate,
        boolean_fuzzy_tolerance=0.1,
        boolean_volume_tolerance=0.01,
    )

    assert comparison.target_minus_candidate_volume == pytest.approx(0.09)
    assert comparison.same_geometric_point_set is False


def test_strict_cut_is_configured_before_one_build(monkeypatch):
    instances = []

    class RecordingCut:
        def __init__(self, *args):
            self.constructor_args = args
            self.events = []
            self.result = None
            instances.append(self)

        def SetArguments(self, shapes):
            self.result = list(shapes)[0]
            self.events.append("arguments")

        def SetTools(self, shapes):
            assert len(list(shapes)) == 1
            self.events.append("tools")

        def SetRunParallel(self, value):
            assert value is True
            self.events.append("parallel")

        def SetUseOBB(self, value):
            assert value is True
            self.events.append("obb")

        def SetToFillHistory(self, value):
            assert value is False
            self.events.append("history")

        def SetNonDestructive(self, value):
            assert value is True
            self.events.append("non_destructive")

        def SetFuzzyValue(self, value):
            assert value == pytest.approx(1.0e-9)
            self.events.append("fuzzy")

        def Build(self):
            self.events.append("build")

        def IsDone(self):
            return True

        def Shape(self):
            return self.result

    monkeypatch.setattr(compare_module, "BRepAlgoAPI_Cut", RecordingCut)
    shape = _box().wrapped

    assert compare_module._cut_volume(shape, shape, 1.0e-9) == pytest.approx(24.0)
    assert instances[0].constructor_args == ()
    assert instances[0].events == [
        "arguments",
        "tools",
        "parallel",
        "obb",
        "history",
        "non_destructive",
        "fuzzy",
        "build",
    ]


def test_strict_cut_does_not_accept_an_invalid_boolean_result(monkeypatch):
    class InvalidResult:
        def __init__(self, shape):
            pass

        def IsValid(self):
            return False

    monkeypatch.setattr(compare_module, "BRepCheck_Analyzer", InvalidResult)
    shape = _box().wrapped

    with pytest.raises(RuntimeError, match="invalid shape"):
        compare_module._cut_volume(shape, shape, None)


def test_compare_detects_same_geometry_with_different_topology():
    full_circle = scad.make_cylinder_rsolid(radius=1.0, height=2.0)
    two_arcs = _two_arc_cylinder()

    comparison = brep.compare_shapes_rbrepcomparison(full_circle.wrapped, two_arcs.wrapped)

    assert comparison.same_geometric_point_set is True
    assert comparison.geometry_labelled_incidence_graph_isomorphic is False
    assert comparison.hard_gate_passed is False


def test_center_slice_specs_follow_shape_bounds():
    specs = brep.make_center_slice_specs_rslicespeclist(
        minimum=(-2.0, 4.0, 10.0),
        maximum=(6.0, 8.0, 14.0),
    )

    assert [(spec.plane, spec.value) for spec in specs] == [
        ("yz", 2.0),
        ("xz", 6.0),
        ("xy", 12.0),
    ]


def test_compare_shape_slices_has_zero_xor_for_same_shape():
    shape = _box().wrapped
    comparison = brep.compare_shape_slices_rslicecomparison(
        shape,
        shape,
        slices=(brep.SliceSpec("xy", 1.0), brep.SliceSpec("xz", 1.5)),
        samples=(11, 9),
    )

    assert comparison.total_samples == 198
    assert comparison.xor_samples == 0
    assert comparison.sampled_slices_identical is True


def test_step_round_trip_uses_public_inspection_namespace(tmp_path: Path):
    step = tmp_path / "box.step"
    export_step_shapes([_box().wrapped], str(step))

    report = brep.inspect_step_rbrepinspection(path=step)
    comparison = brep.compare_steps_rbrepcomparison(
        target_path=step,
        candidate_path=step,
    )
    summary = brep.inspect_step_rsummary(path=step)
    comparison_path = comparison.write_json(tmp_path / "comparison.json")
    error_summary_path = comparison.write_error_summary_json(
        tmp_path / "error_summary.json"
    )

    assert report.counts["unique_faces"] == 6
    assert comparison.hard_gate_passed is True
    assert summary["volume"] == pytest.approx(24.0)
    assert json.loads(comparison_path.read_text(encoding="utf-8"))["diagnostics"][
        "topology_counts"
    ]["equal"] is True
    diagnostic_state = json.loads(error_summary_path.read_text(encoding="utf-8"))
    assert diagnostic_state["errors"] == []
    assert diagnostic_state["root_cause_groups"] == []


def test_step_model_helpers_cache_and_return_stable_ids(tmp_path: Path):
    step = tmp_path / "box.step"
    export_step_shapes([_box().wrapped], str(step))
    brep.clear_step_model_cache_rnone()

    first = brep.load_step_rbrepmodel(step)
    second = brep.load_step_rbrepmodel(step)
    summary = brep.inspect_step_rsummary(step)
    face = brep.inspect_step_entity_rdescriptor(step, "face:0")

    assert first is second
    assert summary["face_count"] == 6
    assert face == first.describe_entity("face:0")
    assert face["entity_id"] == "face:0"

    brep.clear_step_model_cache_rnone()


def test_step_model_combines_multiple_transferred_roots(tmp_path: Path):
    step = tmp_path / "two-roots.step"
    first = _box().wrapped
    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(10.0, 0.0, 0.0))
    second = BRepBuilderAPI_Transform(first, transform, True).Shape()
    writer = STEPControl_Writer()
    assert writer.Transfer(first, STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Transfer(second, STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Write(str(step)) == IFSelect_RetDone

    with pytest.raises(ValueError, match="Expected one STEP root"):
        brep.load_step_rshape(path=step)

    shape = brep.load_step_rshape(path=step, require_single_root=False)
    report = brep.inspect_shape_rbrepinspection(shape=shape)
    model = brep.load_step_rbrepmodel(step)

    assert report.counts["solid"] == 2
    assert model.summary()["body_count"] == 2
    assert model.summary()["material_body_count"] == 2
    assert model.summary()["volume"] == pytest.approx(48.0)

    brep.clear_step_model_cache_rnone()


def test_inspection_repr_is_a_summary_not_a_face_dump():
    """The default repr is a digest: printing an inspection in a REPL must
    not spill the per-face records (tens of thousands of characters on a
    real part). The full record is to_dict() / .faces / .edges."""
    inspection = brep.inspect_shape_rbrepinspection(_box().wrapped)
    text = repr(inspection)
    assert "valid=True" in text
    assert "unique_faces" in text
    assert "uv_bounds" not in text
    assert len(text) < 600
    # the full record is untouched
    assert len(inspection.faces) == 6
    assert inspection.to_dict()["faces"] == inspection.faces

from __future__ import annotations

import math

import numpy as np
import pytest
import simplecadapi as scad
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
from OCP.GC import GC_MakeArcOfCircle
from OCP.TopoDS import TopoDS_Compound
from OCP.gp import gp_Pnt, gp_Vec

from simplecadapi.inspect import brep
from simplecadapi.inspect.brep.operation_hints import _axes_coaxial


def _hints(report, kind):
    return [hint for hint in report["hints"] if hint["kind"] == kind]


def _shape(value):
    return value.wrapped if hasattr(value, "wrapped") else value


def _cut(base, *tools):
    result = _shape(base)
    for tool in tools:
        operation = BRepAlgoAPI_Cut(result, _shape(tool))
        operation.Build()
        assert operation.IsDone()
        result = operation.Shape()
    assert BRepCheck_Analyzer(result).IsValid()
    return result


def _fuse(first, second):
    operation = BRepAlgoAPI_Fuse(_shape(first), _shape(second))
    operation.Build()
    assert operation.IsDone()
    result = operation.Shape()
    assert BRepCheck_Analyzer(result).IsValid()
    return result


def _through_hole_shape(radius=2.0):
    base = scad.make_box_rsolid(width=20.0, height=16.0, depth=10.0)
    tool = scad.make_cylinder_rsolid(
        radius=radius,
        height=12.0,
        bottom_face_center=(0.0, 0.0, -1.0),
    )
    return _cut(base, tool)


def _blind_hole_shape(radius=2.0, depth=6.0):
    base = scad.make_box_rsolid(width=20.0, height=16.0, depth=10.0)
    tool = scad.make_cylinder_rsolid(
        radius=radius,
        height=depth + 1.0,
        bottom_face_center=(0.0, 0.0, 11.0),
        axis=(0.0, 0.0, -1.0),
    )
    return _cut(base, tool)


def _counterbore_shape():
    base = scad.make_box_rsolid(width=20.0, height=16.0, depth=10.0)
    through = scad.make_cylinder_rsolid(
        radius=2.0,
        height=12.0,
        bottom_face_center=(0.0, 0.0, -1.0),
    )
    recess = scad.make_cylinder_rsolid(
        radius=4.0,
        height=3.0,
        bottom_face_center=(0.0, 0.0, 11.0),
        axis=(0.0, 0.0, -1.0),
    )
    return _cut(base, through, recess)


def _countersink_shape():
    base = scad.make_box_rsolid(width=20.0, height=16.0, depth=10.0)
    through = scad.make_cylinder_rsolid(
        radius=2.0,
        height=12.0,
        bottom_face_center=(0.0, 0.0, -1.0),
    )
    sink = scad.make_cone_rsolid(
        bottom_radius=4.0,
        top_radius=2.0,
        height=2.0,
        bottom_face_center=(0.0, 0.0, 10.0),
        axis=(0.0, 0.0, -1.0),
    )
    return _cut(base, through, sink)


def _compound(*shapes):
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, _shape(shape))
    return compound


def _polygon_wire(points):
    builder = BRepBuilderAPI_MakePolygon()
    for point in points:
        builder.Add(gp_Pnt(*point))
    builder.Close()
    assert builder.IsDone()
    return builder.Wire()


def _loft_shape(*, twist_degrees=0.0, scale=0.65):
    bottom = [(-4.0, -3.0, 0.0), (4.0, -3.0, 0.0), (4.0, 3.0, 0.0), (-4.0, 3.0, 0.0)]
    angle = math.radians(twist_degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    top = [
        (
            scale * (x * cosine - y * sine),
            scale * (x * sine + y * cosine),
            10.0,
        )
        for x, y, _ in bottom
    ]
    builder = BRepOffsetAPI_ThruSections(True, True)
    builder.AddWire(_polygon_wire(bottom))
    builder.AddWire(_polygon_wire(top))
    builder.Build()
    assert builder.IsDone()
    return builder.Shape()


def _curved_profile_prism():
    p0 = gp_Pnt(-4.0, -3.0, 0.0)
    p1 = gp_Pnt(4.0, -3.0, 0.0)
    p2 = gp_Pnt(4.0, 3.0, 0.0)
    p3 = gp_Pnt(-4.0, 3.0, 0.0)
    arc = GC_MakeArcOfCircle(p2, gp_Pnt(0.0, 6.0, 0.0), p3).Value()
    wire_builder = BRepBuilderAPI_MakeWire()
    wire_builder.Add(BRepBuilderAPI_MakeEdge(p0, p1).Edge())
    wire_builder.Add(BRepBuilderAPI_MakeEdge(p1, p2).Edge())
    wire_builder.Add(BRepBuilderAPI_MakeEdge(arc).Edge())
    wire_builder.Add(BRepBuilderAPI_MakeEdge(p3, p0).Edge())
    assert wire_builder.IsDone()
    face = BRepBuilderAPI_MakeFace(wire_builder.Wire()).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0.0, 0.0, 10.0), True).Shape()


def _split_side_profile_prism():
    wire = _polygon_wire(
        [
            (-4.0, -3.0, 0.0),
            (0.0, -3.0, 0.0),
            (4.0, -3.0, 0.0),
            (4.0, 3.0, 0.0),
            (-4.0, 3.0, 0.0),
        ]
    )
    face = BRepBuilderAPI_MakeFace(wire).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0.0, 0.0, 10.0), True).Shape()


def test_through_hole_reports_axis_diameter_ends_and_depth():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _through_hole_shape(),
        feature_kinds=("hole",),
    )
    hints = _hints(report, "hole_region_candidate")

    assert len(hints) == 1
    geometry = hints[0]["geometry"]
    assert geometry["form"] == "through_hole"
    assert geometry["diameters"] == pytest.approx([4.0])
    assert geometry["total_depth"] == pytest.approx(10.0)
    assert geometry["entry_face_id"].startswith("face:")
    assert geometry["exit_face_id"].startswith("face:")
    assert geometry["bottom_face_id"] is None
    assert hints[0]["confidence"]["level"] == "strong"


def test_blind_hole_reports_bottom_and_depth():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _blind_hole_shape(),
        feature_kinds=("hole",),
    )
    hint = _hints(report, "hole_region_candidate")[0]

    assert hint["geometry"]["form"] == "blind_hole"
    assert hint["geometry"]["diameters"] == pytest.approx([4.0])
    assert hint["geometry"]["total_depth"] == pytest.approx(6.0)
    assert hint["geometry"]["exit_face_id"] is None
    assert hint["geometry"]["bottom_face_id"].startswith("face:")


def test_counterbore_reports_ordered_cylindrical_segments():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _counterbore_shape(),
        feature_kinds=("hole",),
    )
    hint = _hints(report, "hole_region_candidate")[0]

    assert hint["geometry"]["form"] == "counterbore"
    assert hint["geometry"]["diameters"] == pytest.approx([8.0, 4.0])
    assert hint["geometry"]["depths"] == pytest.approx([2.0, 8.0])
    assert [segment["carrier"] for segment in hint["geometry"]["segments"]] == [
        "cylinder",
        "cylinder",
    ]


def test_countersink_reports_conical_segment():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _countersink_shape(),
        feature_kinds=("hole",),
    )
    hint = _hints(report, "hole_region_candidate")[0]

    assert hint["geometry"]["form"] == "countersink"
    assert hint["geometry"]["diameters"] == pytest.approx([8.0, 4.0])
    assert [segment["carrier"] for segment in hint["geometry"]["segments"]] == [
        "cone",
        "cylinder",
    ]


def test_cylindrical_boss_is_not_a_hole():
    base = scad.make_box_rsolid(width=20.0, height=16.0, depth=10.0)
    boss = scad.make_cylinder_rsolid(
        radius=2.0,
        height=4.0,
        bottom_face_center=(0.0, 0.0, 10.0),
    )
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _fuse(base, boss),
        feature_kinds=("hole",),
    )

    assert _hints(report, "hole_region_candidate") == []


def test_coaxial_faces_from_different_bodies_are_not_merged():
    first = _blind_hole_shape(radius=2.0)
    second_base = scad.make_box_rsolid(
        width=20.0,
        height=16.0,
        depth=10.0,
        bottom_face_center=(0.0, 0.0, 20.0),
    )
    second_tool = scad.make_cylinder_rsolid(
        radius=3.0,
        height=7.0,
        bottom_face_center=(0.0, 0.0, 31.0),
        axis=(0.0, 0.0, -1.0),
    )
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _compound(first, _cut(second_base, second_tool)),
        feature_kinds=("hole",),
    )
    hints = _hints(report, "hole_region_candidate")

    assert len(hints) == 2
    assert {hint["body_id"] for hint in hints} == {"body:0", "body:1"}
    assert all(len(hint["geometry"]["diameters"]) == 1 for hint in hints)


def test_open_shell_and_indeterminate_material_side_do_not_emit_strong_holes(
    monkeypatch,
):
    open_shell = BRepPrimAPI_MakeCylinder(4.0, 10.0).Shell()
    open_report = brep.inspect_manufacturing_hints_rdescriptor(
        open_shell,
        feature_kinds=("hole",),
    )
    assert not any(
        hint["confidence"]["level"] == "strong"
        for hint in _hints(open_report, "hole_region_candidate")
    )

    from simplecadapi.inspect.brep import operation_hints

    monkeypatch.setattr(operation_hints, "_classifier", lambda *args: None)
    indeterminate_report = brep.inspect_manufacturing_hints_rdescriptor(
        _through_hole_shape(),
        feature_kinds=("hole",),
    )
    assert not any(
        hint["confidence"]["level"] == "strong"
        for hint in _hints(indeterminate_report, "hole_region_candidate")
    )


def test_axis_grouping_honors_linear_and_angular_tolerances():
    axis = (np.asarray([0.0, 0.0, 0.0]), np.asarray([0.0, 0.0, 1.0]))
    shifted = (np.asarray([0.002, 0.0, 0.0]), np.asarray([0.0, 0.0, 1.0]))
    tilted = (
        np.asarray([0.0, 0.0, 0.0]),
        np.asarray(
            [math.sin(math.radians(1.0)), 0.0, math.cos(math.radians(1.0))]
        ),
    )

    assert not _axes_coaxial(axis, shifted, 0.001, 0.5)
    assert _axes_coaxial(axis, shifted, 0.003, 0.5)
    assert not _axes_coaxial(axis, tilted, 0.001, 0.5)
    assert _axes_coaxial(axis, tilted, 0.001, 1.5)


def test_box_and_curved_profile_are_whole_body_extrusions():
    for shape in (
        scad.make_box_rsolid(width=8.0, height=6.0, depth=10.0).wrapped,
        _curved_profile_prism(),
    ):
        report = brep.inspect_manufacturing_hints_rdescriptor(
            shape,
            feature_kinds=("extrusion",),
        )
        hints = _hints(report, "extrusion_region_candidate")

        assert hints
        assert all(hint["confidence"]["level"] == "strong" for hint in hints)
        assert any(hint["geometry"]["length"] == pytest.approx(10.0) for hint in hints)
        assert all(hint["geometry"]["profile_loop_refs"] for hint in hints)


def test_split_coplanar_side_carrier_is_normalized_for_extrusion_coverage():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _split_side_profile_prism(),
        feature_kinds=("extrusion",),
    )
    axial = [
        hint
        for hint in _hints(report, "extrusion_region_candidate")
        if hint["geometry"]["length"] == pytest.approx(10.0)
    ]

    assert len(axial) == 1
    assert len(axial[0]["geometry"]["side_face_ids"]) == 5
    assert len(axial[0]["geometry"]["profile_loop_refs"][0]["edge_ids"]) == 5


def test_multi_body_extrusions_are_stably_sorted_by_body_and_entity_ids():
    first = scad.make_box_rsolid(width=8.0, height=6.0, depth=10.0)
    second = scad.make_box_rsolid(
        width=8.0,
        height=6.0,
        depth=10.0,
        bottom_face_center=(20.0, 0.0, 0.0),
    )
    shape = _compound(first, second)

    report = brep.inspect_manufacturing_hints_rdescriptor(
        shape,
        feature_kinds=("extrusion",),
    )
    repeated = brep.inspect_manufacturing_hints_rdescriptor(
        shape,
        feature_kinds=("extrusion",),
    )
    hints = _hints(report, "extrusion_region_candidate")

    assert report == repeated
    assert [hint["body_id"] for hint in hints] == [
        "body:0",
        "body:0",
        "body:0",
        "body:1",
        "body:1",
        "body:1",
    ]
    assert all(
        hint["entity_ids"] == sorted(
            hint["entity_ids"], key=lambda value: int(value.split(":", 1)[1])
        )
        for hint in hints
    )


def test_inner_loop_prism_preserves_hole_and_extrusion_history_ambiguity():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _through_hole_shape(),
        feature_kinds=("hole", "extrusion"),
    )
    hole = _hints(report, "hole_region_candidate")
    extrusions = _hints(report, "extrusion_region_candidate")

    assert len(hole) == 1
    axial = [
        hint
        for hint in extrusions
        if hint["geometry"]["length"] == pytest.approx(10.0)
    ]
    assert axial
    assert axial[0]["confidence"]["level"] == "strong"
    assert axial[0]["geometry"]["history_ambiguity"] == "profile_inner_loop_or_later_hole"
    assert [loop["role"] for loop in axial[0]["geometry"]["profile_loop_refs"]] == [
        "outer",
        "inner",
    ]


@pytest.mark.parametrize(
    "shape",
    [
        scad.make_cone_rsolid(bottom_radius=4.0, top_radius=2.0, height=10.0).wrapped,
        _loft_shape(scale=0.65),
        _loft_shape(scale=1.0, twist_degrees=30.0),
    ],
)
def test_rotational_tapered_and_lofted_bodies_are_not_strong_extrusions(shape):
    report = brep.inspect_manufacturing_hints_rdescriptor(
        shape,
        feature_kinds=("extrusion",),
    )

    assert not any(
        hint["confidence"]["level"] == "strong"
        for hint in _hints(report, "extrusion_region_candidate")
    )


def test_cylinder_is_revolution_primary_with_extrusion_only_as_alternative():
    report = brep.inspect_geometric_features_rdescriptor(
        scad.make_cylinder_rsolid(radius=4.0, height=10.0).wrapped,
        feature_kinds=("extrusion", "revolution"),
    )
    revolutions = [
        item for item in report["features"] if item["category"] == "revolution"
    ]

    assert len(revolutions) == 1
    assert revolutions[0]["subtype"] == "whole_body_full_revolution"
    assert any(
        item["category"] == "extrusion"
        for item in revolutions[0]["relationships"]["alternative_interpretations"]
    )
    assert not any(item["category"] == "extrusion" for item in report["features"])


def test_local_boss_parallel_faces_do_not_form_whole_body_extrusion():
    base = scad.make_box_rsolid(width=20.0, height=16.0, depth=4.0)
    boss = scad.make_box_rsolid(
        width=6.0,
        height=6.0,
        depth=3.0,
        bottom_face_center=(0.0, 0.0, 4.0),
    )
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _fuse(base, boss),
        feature_kinds=("extrusion",),
    )

    hints = _hints(report, "extrusion_region_candidate")
    assert any(hint["geometry"]["form"] == "local_boss" for hint in hints)
    assert not any(
        hint["geometry"]["form"] == "whole_body_prism" for hint in hints
    )


def test_operation_hints_are_stable_reversible_and_resolvable():
    shape = _through_hole_shape()
    options = {"feature_kinds": ("hole", "extrusion")}

    first = brep.inspect_manufacturing_hints_rdescriptor(shape, **options)
    second = brep.inspect_manufacturing_hints_rdescriptor(shape, **options)
    reversed_report = brep.inspect_manufacturing_hints_rdescriptor(
        shape.Reversed(),
        **options,
    )
    model = brep.index_shape_rbrepmodel(shape)

    assert first == second
    assert first == reversed_report
    assert [hint["kind"] for hint in first["hints"]] == [
        hint["kind"] for hint in reversed_report["hints"]
    ]
    forward_hole = _hints(first, "hole_region_candidate")[0]
    reversed_hole = _hints(reversed_report, "hole_region_candidate")[0]
    assert forward_hole["geometry"] == reversed_hole["geometry"]
    assert forward_hole["confidence"] == reversed_hole["confidence"]
    assert [
        evidence for evidence in forward_hole["evidence"] if evidence["required"]
    ] == [
        evidence for evidence in reversed_hole["evidence"] if evidence["required"]
    ]
    for hint in first["hints"]:
        model.resolve_entity(hint["body_id"])
        for entity_id in (
            hint["entity_ids"]
            + hint["highlight_entity_ids"]
            + hint["support_entity_ids"]
        ):
            model.resolve_entity(entity_id)
        for loop in hint["geometry"].get("profile_loop_refs", []):
            model.resolve_entity(loop["face_id"])
            for edge_id in loop["edge_ids"]:
                model.resolve_entity(edge_id)

from __future__ import annotations

import math
import subprocess
import sys

import numpy as np
import pytest
import simplecadapi as scad
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax1, gp_Ax3, gp_Cylinder, gp_Dir, gp_Pnt, gp_Trsf

from simplecadapi.inspect import brep
from simplecadapi.inspect.brep.manufacturing import (
    _axes_coaxial,
    _chamfer_hints,
    _cylinder_trim_overlap,
    _face_facts,
    _paired_bend_faces_from_fillet_hints,
    _plane_pair_candidates,
)


def _hints(report, kind):
    return [hint for hint in report["hints"] if hint["kind"] == kind]


def _shape(value):
    return value.wrapped if hasattr(value, "wrapped") else value


def _cut_shape(base, *tools):
    result = _shape(base)
    for tool in tools:
        operation = BRepAlgoAPI_Cut(result, _shape(tool))
        operation.Build()
        assert operation.IsDone()
        result = operation.Shape()
    return result


def _through_hole_shape():
    base = scad.make_box_rsolid(width=20.0, height=16.0, depth=10.0)
    tool = scad.make_cylinder_rsolid(
        radius=2.0,
        height=12.0,
        bottom_face_center=(0.0, 0.0, -1.0),
    )
    return _cut_shape(base, tool)


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
    return _cut_shape(base, through, sink)


def test_manufacturing_hints_are_public_and_geometry_only():
    result = brep.inspect_manufacturing_hints_rdescriptor(
        scad.make_box_rsolid(20.0, 10.0, 1.0).wrapped
    )

    assert result["units"] == {"length": "mm", "angle": "degree"}
    assert result["summary"]["analyzed_body_count"] == 1
    assert result["summary"]["analyzed_face_count"] == 6


def test_fillet_candidate_uses_tangent_support_evidence():
    box = scad.make_box_rsolid(10.0, 8.0, 4.0)
    filleted = scad.fillet_rsolid(box, [box.get_edges(0)], 1.0)

    report = brep.inspect_manufacturing_hints_rdescriptor(
        filleted.wrapped, feature_kinds=("fillet",)
    )
    hints = _hints(report, "fillet_region_candidate")

    assert len(hints) == 1
    assert hints[0]["geometry"]["carrier_type"] == "CYLINDER"
    assert hints[0]["geometry"]["radius"] == pytest.approx(1.0)
    assert hints[0]["geometry"]["effective_length"] == pytest.approx(4.0)
    assert hints[0]["geometry"]["sweep_angle_degrees"] > 0.0
    assert hints[0]["geometry"]["surface_area"] > 0.0
    assert len(hints[0]["support_entity_ids"]) >= 2
    assert hints[0]["confidence"]["level"] == "strong"


def test_plain_cylinder_is_not_a_fillet_candidate():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        BRepPrimAPI_MakeCylinder(5.0, 10.0).Shape(),
        feature_kinds=("fillet",),
    )

    assert _hints(report, "fillet_region_candidate") == []


def test_chamfer_candidate_bridges_two_support_faces():
    box = scad.make_box_rsolid(10.0, 8.0, 4.0)
    chamfered = scad.chamfer_rsolid(box, [box.get_edges(0)], 1.0)

    report = brep.inspect_manufacturing_hints_rdescriptor(
        chamfered.wrapped, feature_kinds=("chamfer",)
    )
    hints = _hints(report, "chamfer_region_candidate")

    assert len(hints) == 1
    assert hints[0]["geometry"]["form"] == "planar_bevel"
    assert hints[0]["geometry"]["length"] == pytest.approx(4.0)
    assert hints[0]["geometry"]["face_width"] > 0.0
    assert len(hints[0]["support_entity_ids"]) == 2
    assert hints[0]["claim"] == "geometric_candidate"


def test_conical_chamfer_uses_axial_plane_and_configured_linear_tolerance():
    class FakeModel:
        bodies = [object()]

        @staticmethod
        def adjacency_details(entity_id):
            assert entity_id == "body:0"
            return {"faces": ["face:0", "face:1", "face:2", "face:3"]}

    axis = {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0]}
    facts = {
        "face:0": {
            "type": "CONE",
            "area": 2.0,
            "normal": np.array([1.0, 0.0, 0.0]),
            "neighbors": ["face:1", "face:2", "face:3"],
            "parameters": {
                "axis": axis,
                "semi_angle_degrees": 45.0,
                "reference_radius": 2.0,
            },
        },
        "face:1": {
            "type": "PLANE",
            "area": 10.0,
            "normal": np.array([0.0, 0.0, 1.0]),
            "neighbors": [],
            "parameters": {},
        },
        "face:2": {
            "type": "PLANE",
            "area": 10.0,
            "normal": np.array([1.0, 0.0, 0.0]),
            "neighbors": [],
            "parameters": {},
        },
        "face:3": {
            "type": "CYLINDER",
            "area": 10.0,
            "normal": np.array([1.0, 0.0, 0.0]),
            "neighbors": [],
            "parameters": {
                "axis": {
                    "point": [5.0e-5, 0.0, 0.0],
                    "direction": [0.0, 0.0, 1.0],
                }
            },
        },
    }

    hints = _chamfer_hints(FakeModel(), facts, None, 0.5, 1.0e-4)

    assert len(hints) == 1
    assert hints[0]["support_entity_ids"] == ["face:3", "face:1"]
    assert _chamfer_hints(FakeModel(), facts, None, 0.5, 1.0e-6) == []


def test_conical_chamfer_never_borrows_supports_from_another_body():
    class FakeModel:
        bodies = [object(), object()]

        @staticmethod
        def adjacency_details(entity_id):
            return {
                "body:0": {"faces": ["face:0", "face:1"]},
                "body:1": {"faces": ["face:2"]},
            }[entity_id]

    axis = {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0]}
    facts = {
        "face:0": {
            "type": "CONE",
            "area": 2.0,
            "normal": np.array([1.0, 0.0, 0.0]),
            "neighbors": ["face:1", "face:2"],
            "parameters": {
                "axis": axis,
                "semi_angle_degrees": 45.0,
                "reference_radius": 2.0,
            },
        },
        "face:1": {
            "type": "PLANE",
            "area": 10.0,
            "normal": np.array([0.0, 0.0, 1.0]),
            "neighbors": [],
            "parameters": {},
        },
        "face:2": {
            "type": "CYLINDER",
            "area": 10.0,
            "normal": np.array([1.0, 0.0, 0.0]),
            "neighbors": [],
            "parameters": {"axis": axis},
        },
    }

    hints = _chamfer_hints(FakeModel(), facts, None, 0.5, 1.0e-7)

    assert hints == []


def test_flat_plate_is_sheet_candidate_but_has_no_bend():
    plate = scad.make_box_rsolid(20.0, 10.0, 1.0)

    report = brep.inspect_manufacturing_hints_rdescriptor(
        plate.wrapped, feature_kinds=("sheet_metal",)
    )
    sheets = _hints(report, "sheet_metal_body_candidate")

    assert len(sheets) == 1
    assert sheets[0]["geometry"]["thickness"] == pytest.approx(1.0)
    assert sheets[0]["geometry"]["bend_count"] == 0
    assert sheets[0]["geometry"]["formed"] is False
    assert sheets[0]["geometry"]["paired_skin_area_fraction"] > 0.70
    assert _hints(report, "sheet_metal_bend_candidate") == []


def test_cylindrical_sheet_body_is_candidate_but_not_formed_bend():
    inner = BRepPrimAPI_MakeCylinder(9.0, 20.0).Shape()
    transform = gp_Trsf()
    transform.SetRotation(
        gp_Ax1(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0)),
        math.radians(30.0),
    )
    rotated_inner = BRepBuilderAPI_Transform(inner, transform, False).Shape()
    cut = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeCylinder(10.0, 20.0).Shape(),
        rotated_inner,
    )
    cut.Build()
    assert cut.IsDone()

    report = brep.inspect_manufacturing_hints_rdescriptor(
        cut.Shape(), feature_kinds=("sheet_metal",)
    )
    sheets = _hints(report, "sheet_metal_body_candidate")

    assert len(sheets) == 1
    assert sheets[0]["geometry"]["thickness"] == pytest.approx(1.0)
    assert sheets[0]["geometry"]["formed"] is False
    assert sheets[0]["geometry"]["bend_count"] == 0
    assert _hints(report, "sheet_metal_bend_candidate") == []


def test_axis_matching_uses_configured_tolerances():
    first = {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0]}
    second = {
        "point": [5.0e-7, 0.0, 10.0],
        "direction": [0.0, math.sin(math.radians(0.2)), math.cos(math.radians(0.2))],
    }

    assert _axes_coaxial(first, second, 1.0e-6, 0.5) is True
    shifted = {
        **second,
        "point": [
            second["point"][index] + 37.0 * second["direction"][index]
            for index in range(3)
        ],
    }
    assert _axes_coaxial(first, shifted, 1.0e-6, 0.5) is True
    assert _axes_coaxial(first, second, 1.0e-8, 0.5) is False
    assert _axes_coaxial(first, second, 1.0e-6, 0.1) is False


def test_plane_pairing_ignores_untrimmed_carrier_origin_choice():
    model = brep.index_shape_rbrepmodel(
        scad.make_box_rsolid(20.0, 10.0, 1.0).wrapped
    )
    facts = _face_facts(model)
    opposing = next(
        (first, second)
        for first in facts
        for second in facts
        if first < second
        and facts[first]["type"] == facts[second]["type"] == "PLANE"
        and float(np.dot(facts[first]["normal"], facts[second]["normal"])) < -0.999
        and abs(facts[first]["area"] - 200.0) < 1.0e-6
        and abs(facts[second]["area"] - 200.0) < 1.0e-6
    )
    baseline = _plane_pair_candidates(opposing, facts, 0.5, 1.0e-7)
    facts[opposing[1]]["parameters"]["origin"] = [999.0, -123.0, 456.0]
    shifted = _plane_pair_candidates(opposing, facts, 0.5, 1.0e-7)

    assert len(baseline) == len(shifted) == 1
    assert shifted[0]["thickness"] == pytest.approx(baseline[0]["thickness"])


def test_disjoint_coaxial_cylinder_trims_do_not_pair():
    common = {
        "parameters": {
            "axis": {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0]},
            "u_range": [0.0, math.pi / 2.0],
            "v_range": [0.0, 10.0],
        },
    }
    first = {**common, "centroid": np.array([4.0, 4.0, 5.0])}
    second = {**common, "centroid": np.array([-3.0, -3.0, 5.0])}

    assert _cylinder_trim_overlap(first, second, 1.0e-7, 0.5, 1.0) is False


def test_disjoint_real_cylindrical_faces_do_not_pair():
    axis = gp_Ax3(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
    first_shape = BRepBuilderAPI_MakeFace(
        gp_Cylinder(axis, 4.0), 0.0, math.pi / 2.0, 0.0, 10.0
    ).Face()
    second_shape = BRepBuilderAPI_MakeFace(
        gp_Cylinder(axis, 3.0), math.pi, 1.5 * math.pi, 0.0, 10.0
    ).Face()
    first = _face_facts(brep.index_shape_rbrepmodel(first_shape))["face:0"]
    second = _face_facts(brep.index_shape_rbrepmodel(second_shape))["face:0"]

    assert _cylinder_trim_overlap(first, second, 1.0e-7, 0.5, 1.0) is False


def _make_bent_plate(inside_radius=3.0, outside_radius=4.0):
    root_half = math.sqrt(0.5)
    edges = [
        scad.make_line_redge(
            (outside_radius, -10.0, 0.0), (outside_radius, 0.0, 0.0)
        ),
        scad.make_three_point_arc_redge(
            (outside_radius, 0.0, 0.0),
            (
                outside_radius * root_half,
                outside_radius * root_half,
                0.0,
            ),
            (0.0, outside_radius, 0.0),
        ),
        scad.make_line_redge(
            (0.0, outside_radius, 0.0), (-10.0, outside_radius, 0.0)
        ),
        scad.make_line_redge(
            (-10.0, outside_radius, 0.0), (-10.0, inside_radius, 0.0)
        ),
        scad.make_line_redge(
            (-10.0, inside_radius, 0.0), (0.0, inside_radius, 0.0)
        ),
        scad.make_three_point_arc_redge(
            (0.0, inside_radius, 0.0),
            (inside_radius * root_half, inside_radius * root_half, 0.0),
            (inside_radius, 0.0, 0.0),
        ),
        scad.make_line_redge(
            (inside_radius, 0.0, 0.0), (inside_radius, -10.0, 0.0)
        ),
        scad.make_line_redge(
            (inside_radius, -10.0, 0.0), (outside_radius, -10.0, 0.0)
        ),
    ]
    wire = scad.make_wire_from_edges_rwire(edges)
    profile = scad.make_face_from_wire_rface(wire)
    return scad.extrude_rsolid(profile, (0.0, 0.0, 1.0), 20.0)


def _make_double_bend_plate():
    root_half = math.sqrt(0.5)
    edges = [
        scad.make_line_redge((-4.0, 10.0, 0.0), (-4.0, 0.0, 0.0)),
        scad.make_three_point_arc_redge(
            (-4.0, 0.0, 0.0),
            (-4.0 * root_half, -4.0 * root_half, 0.0),
            (0.0, -4.0, 0.0),
        ),
        scad.make_line_redge((0.0, -4.0, 0.0), (10.0, -4.0, 0.0)),
        scad.make_three_point_arc_redge(
            (10.0, -4.0, 0.0),
            (10.0 + 4.0 * root_half, -4.0 * root_half, 0.0),
            (14.0, 0.0, 0.0),
        ),
        scad.make_line_redge((14.0, 0.0, 0.0), (14.0, 10.0, 0.0)),
        scad.make_line_redge((14.0, 10.0, 0.0), (13.0, 10.0, 0.0)),
        scad.make_line_redge((13.0, 10.0, 0.0), (13.0, 0.0, 0.0)),
        scad.make_three_point_arc_redge(
            (13.0, 0.0, 0.0),
            (10.0 + 3.0 * root_half, -3.0 * root_half, 0.0),
            (10.0, -3.0, 0.0),
        ),
        scad.make_line_redge((10.0, -3.0, 0.0), (0.0, -3.0, 0.0)),
        scad.make_three_point_arc_redge(
            (0.0, -3.0, 0.0),
            (-3.0 * root_half, -3.0 * root_half, 0.0),
            (-3.0, 0.0, 0.0),
        ),
        scad.make_line_redge((-3.0, 0.0, 0.0), (-3.0, 10.0, 0.0)),
        scad.make_line_redge((-3.0, 10.0, 0.0), (-4.0, 10.0, 0.0)),
    ]
    wire = scad.make_wire_from_edges_rwire(edges)
    profile = scad.make_face_from_wire_rface(wire)
    return scad.extrude_rsolid(profile, (0.0, 0.0, 1.0), 20.0)


def test_coaxial_opposed_cylinders_form_sheet_metal_bend_hint():
    bend = _make_bent_plate()

    report = brep.inspect_manufacturing_hints_rdescriptor(
        bend.wrapped, feature_kinds=("sheet_metal",)
    )
    sheets = _hints(report, "sheet_metal_body_candidate")
    bends = _hints(report, "sheet_metal_bend_candidate")

    assert len(sheets) == 1
    assert sheets[0]["geometry"]["thickness"] == pytest.approx(1.0)
    assert sheets[0]["geometry"]["bend_count"] == 1
    assert sheets[0]["geometry"]["formed"] is True
    assert len(bends) == 1
    assert bends[0]["geometry"]["inside_radius"] == pytest.approx(3.0)
    assert bends[0]["geometry"]["outside_radius"] == pytest.approx(4.0)
    assert len(bends[0]["geometry"]["adjacent_skin_face_ids"]) == 4

    fillet_only = brep.inspect_manufacturing_hints_rdescriptor(
        bend.wrapped, feature_kinds=("fillet",)
    )
    assert _hints(fillet_only, "fillet_region_candidate") == []


def test_thick_bend_cylinders_remain_fillet_candidates():
    thick_bend = _make_bent_plate(inside_radius=3.0, outside_radius=8.0)

    default = brep.inspect_manufacturing_hints_rdescriptor(thick_bend.wrapped)
    fillet_only = brep.inspect_manufacturing_hints_rdescriptor(
        thick_bend.wrapped, feature_kinds=("fillet",)
    )

    assert _hints(default, "sheet_metal_body_candidate") == []
    assert _hints(default, "fillet_region_candidate")
    assert _hints(fillet_only, "fillet_region_candidate") == _hints(
        default, "fillet_region_candidate"
    )


def test_multiple_sheet_bends_are_not_fillet_candidates():
    bend = _make_double_bend_plate()

    default = brep.inspect_manufacturing_hints_rdescriptor(bend.wrapped)
    fillet_only = brep.inspect_manufacturing_hints_rdescriptor(
        bend.wrapped, feature_kinds=("fillet",)
    )

    assert len(_hints(default, "sheet_metal_bend_candidate")) == 2
    assert _hints(default, "fillet_region_candidate") == []
    assert _hints(fillet_only, "fillet_region_candidate") == []


def test_thick_cube_is_not_sheet_metal_candidate():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        scad.make_box_rsolid(10.0, 10.0, 10.0).wrapped,
        feature_kinds=("sheet_metal",),
    )

    assert _hints(report, "sheet_metal_body_candidate") == []


def test_reversed_plate_preserves_sheet_candidate():
    plate = scad.make_box_rsolid(20.0, 10.0, 1.0).wrapped.Reversed()

    report = brep.inspect_manufacturing_hints_rdescriptor(
        plate, feature_kinds=("sheet_metal",)
    )

    assert len(_hints(report, "sheet_metal_body_candidate")) == 1


def test_feature_kind_selection_is_compositional():
    box = scad.make_box_rsolid(10.0, 8.0, 4.0)
    filleted = scad.fillet_rsolid(box, [box.get_edges(0)], 1.0)

    default = brep.inspect_manufacturing_hints_rdescriptor(filleted.wrapped)
    only = brep.inspect_manufacturing_hints_rdescriptor(
        filleted.wrapped, feature_kinds=("fillet",)
    )

    assert _hints(default, "fillet_region_candidate") == _hints(
        only, "fillet_region_candidate"
    )


def test_default_feature_kinds_remain_legacy_and_skip_operation_hints(monkeypatch):
    from simplecadapi.inspect.brep import manufacturing

    def fail_if_called(*args, **kwargs):
        raise AssertionError("operation-hint analysis should not run by default")

    monkeypatch.setattr(manufacturing, "_hole_hints", fail_if_called, raising=False)
    monkeypatch.setattr(
        manufacturing, "_extrusion_hints", fail_if_called, raising=False
    )
    monkeypatch.setattr(
        manufacturing, "revolution_hints", fail_if_called, raising=False
    )
    shape = scad.make_box_rsolid(10.0, 8.0, 4.0).wrapped

    default = brep.inspect_manufacturing_hints_rdescriptor(shape)
    explicit_legacy = brep.inspect_manufacturing_hints_rdescriptor(
        shape,
        feature_kinds=("fillet", "chamfer", "sheet_metal"),
    )

    assert manufacturing.FEATURE_KINDS == ("fillet", "chamfer", "sheet_metal")
    assert default == explicit_legacy
    assert not {
        "hole_region_candidate",
        "extrusion_region_candidate",
        "revolution_region_candidate",
    }.intersection(hint["kind"] for hint in default["hints"])


def test_sweep_and_loft_share_precomputed_section_families(monkeypatch):
    from simplecadapi.inspect.brep import manufacturing

    whole = [{"family": "whole"}]
    local = [{"family": "local"}]
    points = [{"family": "point"}]
    calls = {"whole": 0, "local": 0, "points": 0}
    received = {}

    def whole_families(*_):
        calls["whole"] += 1
        return whole

    def local_families(*_):
        calls["local"] += 1
        return local

    def point_families(*_):
        calls["points"] += 1
        return points

    def sweep(*_, whole_families, local_families):
        received["sweep"] = (whole_families, local_families)
        return [], []

    def loft(*_, whole_families, local_families, point_families):
        received["loft"] = (whole_families, local_families, point_families)
        return [], []

    monkeypatch.setattr(manufacturing, "whole_body_section_families", whole_families)
    monkeypatch.setattr(manufacturing, "local_section_families", local_families)
    monkeypatch.setattr(manufacturing, "whole_body_point_families", point_families)
    monkeypatch.setattr(manufacturing, "sweep_hints", sweep)
    monkeypatch.setattr(manufacturing, "loft_hints", loft)

    brep.inspect_manufacturing_hints_rdescriptor(
        scad.make_box_rsolid(10.0, 8.0, 4.0).wrapped,
        feature_kinds=("sweep", "loft"),
    )

    assert calls == {"whole": 1, "local": 1, "points": 1}
    assert received["sweep"] == (whole, local)
    assert received["loft"] == (whole, local, points)


def test_revolution_is_available_only_when_explicitly_requested():
    profile = scad.make_rectangle_rface(
        width=2.0,
        height=4.0,
        center=(3.0, 0.0, 0.0),
    )
    body = scad.revolve_rsolid(
        profile,
        axis=(0.0, 1.0, 0.0),
        angle=360.0,
        origin=(0.0, 0.0, 0.0),
    )

    default = brep.inspect_manufacturing_hints_rdescriptor(body.wrapped)
    explicit = brep.inspect_manufacturing_hints_rdescriptor(
        body.wrapped,
        feature_kinds=("revolution",),
    )

    assert not _hints(default, "revolution_region_candidate")
    assert any(
        item["geometry"]["form"] == "whole_body_full_revolution"
        for item in _hints(explicit, "revolution_region_candidate")
    )


def test_new_feature_kinds_compose_with_legacy_kinds_in_stable_order():
    shape = _through_hole_shape()
    options = {"feature_kinds": ("chamfer", "hole", "extrusion")}

    report = brep.inspect_manufacturing_hints_rdescriptor(shape, **options)
    repeated = brep.inspect_manufacturing_hints_rdescriptor(shape, **options)

    assert report == repeated
    assert [(hint["kind"], hint["hint_id"]) for hint in report["hints"]] == [
        ("extrusion_region_candidate", "extrusion_region_candidate:0"),
        ("hole_region_candidate", "hole_region_candidate:0"),
    ]


def test_new_feature_hints_preserve_truncation_metadata():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _through_hole_shape(),
        feature_kinds=("hole", "extrusion"),
        max_hints=1,
    )

    assert [hint["kind"] for hint in report["hints"]] == [
        "extrusion_region_candidate"
    ]
    assert report["summary"]["hint_count"] == 1
    assert report["truncated"] is True
    assert report["omitted_hint_count"] == 1


def test_countersink_cone_is_not_also_reported_as_a_chamfer():
    report = brep.inspect_manufacturing_hints_rdescriptor(
        _countersink_shape(),
        feature_kinds=("hole", "chamfer"),
    )

    holes = _hints(report, "hole_region_candidate")
    assert len(holes) == 1
    assert holes[0]["geometry"]["form"] == "countersink"
    assert _hints(report, "chamfer_region_candidate") == []


def test_specialized_fillet_request_skips_sheet_metal_pair_scan(monkeypatch):
    from simplecadapi.inspect.brep import manufacturing

    def fail_if_called(*args, **kwargs):
        raise AssertionError("sheet-metal analysis should not run")

    monkeypatch.setattr(manufacturing, "_sheet_metal_hints", fail_if_called)
    box = scad.make_box_rsolid(10.0, 8.0, 4.0)
    filleted = scad.fillet_rsolid(box, [box.get_edges(0)], 1.0)

    report = brep.inspect_manufacturing_hints_rdescriptor(
        filleted.wrapped, feature_kinds=("fillet",)
    )

    assert len(_hints(report, "fillet_region_candidate")) == 1


def test_lightweight_bend_pairing_never_crosses_body_boundaries(monkeypatch):
    from simplecadapi.inspect.brep import manufacturing

    axis = {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0]}
    hints = [
        {
            "body_id": "body:0",
            "entity_ids": ["face:0"],
            "geometry": {"carrier_type": "CYLINDER"},
        },
        {
            "body_id": "body:1",
            "entity_ids": ["face:1"],
            "geometry": {"carrier_type": "CYLINDER"},
        },
    ]
    facts = {
        "face:0": {
            "area": 30.0,
            "side": -1,
            "parameters": {"axis": axis, "radius": 3.0},
        },
        "face:1": {
            "area": 40.0,
            "side": 1,
            "parameters": {"axis": axis, "radius": 4.0},
        },
    }
    monkeypatch.setattr(
        manufacturing, "_cylinder_material_side", lambda fact: fact["side"]
    )
    monkeypatch.setattr(
        manufacturing, "_cylinder_trim_overlap", lambda *args, **kwargs: True
    )

    bend_faces = _paired_bend_faces_from_fillet_hints(
        type("FakeModel", (), {})(),
        hints,
        facts,
        {
            "linear": 1.0e-7,
            "radius": 1.0e-6,
            "angular_degrees": 0.5,
        },
    )

    assert bend_faces == set()


def test_public_chamfer_request_passes_effective_linear_tolerance(monkeypatch):
    from simplecadapi.inspect.brep import manufacturing

    observed = {}

    def capture(model, facts, excluded_face_ids, angular_tolerance, linear_tolerance):
        observed["linear_tolerance"] = linear_tolerance
        return []

    monkeypatch.setattr(manufacturing, "_chamfer_hints", capture)
    box = scad.make_box_rsolid(10.0, 8.0, 4.0)

    brep.inspect_manufacturing_hints_rdescriptor(
        box.wrapped,
        feature_kinds=("chamfer",),
        tolerance=1.0e-3,
    )

    assert observed["linear_tolerance"] == pytest.approx(1.0e-3)


def test_manufacturing_hint_options_are_validated():
    box = scad.make_box_rsolid(2.0, 2.0, 0.2)

    with pytest.raises(ValueError, match="unsupported values"):
        brep.inspect_manufacturing_hints_rdescriptor(
            box.wrapped, feature_kinds=("fold",)
        )
    with pytest.raises(ValueError, match="tolerance"):
        brep.inspect_manufacturing_hints_rdescriptor(box.wrapped, tolerance=0.0)
    with pytest.raises(ValueError, match="too large"):
        brep.inspect_manufacturing_hints_rdescriptor(box.wrapped, tolerance=1.0e308)
    with pytest.raises(ValueError, match="max_hints"):
        brep.inspect_manufacturing_hints_rdescriptor(box.wrapped, max_hints=0)


def test_manufacturing_hint_renderer_writes_grouped_highlight(tmp_path):
    output = tmp_path / "manufacturing-hints.png"
    code = f"""
import simplecadapi as scad
from simplecadapi.inspect import brep
box = scad.make_box_rsolid(10.0, 8.0, 4.0)
filleted = scad.fillet_rsolid(box, [box.get_edges(0)], 1.0)
brep.render_manufacturing_hints_rpath(
    filleted.wrapped,
    {str(output)!r},
    feature_kinds=("fillet",),
    views=((28.0, -45.0, "isometric"),),
    image_size=(4.0, 3.0),
    dpi=60,
)
"""

    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert output.stat().st_size > 0


def test_manufacturing_hint_renderer_forwards_analysis_options(monkeypatch, tmp_path):
    from simplecadapi.inspect.brep import manufacturing

    observed = {}

    def capture(model, **options):
        observed.update(options)
        raise RuntimeError("captured analysis options")

    monkeypatch.setattr(
        manufacturing, "inspect_manufacturing_hints_rdescriptor", capture
    )
    shape = scad.make_box_rsolid(2.0, 2.0, 0.2).wrapped

    with pytest.raises(RuntimeError, match="captured"):
        brep.render_manufacturing_hints_rpath(
            shape,
            tmp_path / "unused.png",
            feature_kinds=("hole", "extrusion"),
            tolerance=1.0e-4,
            angular_tolerance_degrees=0.25,
            max_hints=7,
        )

    assert observed == {
        "feature_kinds": ("hole", "extrusion"),
        "tolerance": 1.0e-4,
        "angular_tolerance_degrees": 0.25,
        "max_hints": 7,
    }


def test_manufacturing_hint_renderer_groups_hole_and_extrusion_colors(
    monkeypatch, tmp_path
):
    from simplecadapi.inspect.brep import manufacturing, render

    class FakeModel:
        root = object()

        def resolve_entity(self, entity_id):
            return None, None, entity_id

    captured = {}
    fake_model = FakeModel()
    monkeypatch.setattr(manufacturing, "_model", lambda value: fake_model)
    monkeypatch.setattr(
        manufacturing,
        "inspect_manufacturing_hints_rdescriptor",
        lambda model, **options: {
            "hints": [
                {
                    "kind": "extrusion_region_candidate",
                    "entity_ids": ["face:0"],
                    "highlight_entity_ids": ["face:0"],
                },
                {
                    "kind": "hole_region_candidate",
                    "entity_ids": ["face:1"],
                    "highlight_entity_ids": ["face:1"],
                },
            ]
        },
    )
    monkeypatch.setattr(render, "_mesh_polydata", lambda shapes, *args: tuple(shapes))
    monkeypatch.setattr(render, "_edge_polydata", lambda shapes, **kwargs: tuple(shapes))

    def capture_render(context, output_path, **kwargs):
        captured.update(kwargs)
        return output_path

    monkeypatch.setattr(render, "_render_polydata_views", capture_render)
    output = tmp_path / "new-hint-colors.png"

    assert (
        brep.render_manufacturing_hints_rpath(
            fake_model,
            output,
            feature_kinds=("hole", "extrusion"),
        )
        == output
    )
    assert captured["highlighted_groups"] == [
        (("face:0",), (41 / 255, 173 / 255, 87 / 255), 1.0),
        (("face:1",), (148 / 255, 61 / 255, 199 / 255), 1.0),
    ]
    assert captured["legend"] == [
        ("Extrusion candidates", (41 / 255, 173 / 255, 87 / 255)),
        ("Hole candidates", (148 / 255, 61 / 255, 199 / 255)),
    ]


def test_manufacturing_hint_renderer_uses_cyan_for_revolution(monkeypatch, tmp_path):
    from simplecadapi.inspect.brep import manufacturing, render

    class FakeModel:
        root = object()

        def resolve_entity(self, entity_id):
            return None, None, entity_id

    captured = {}
    fake_model = FakeModel()
    monkeypatch.setattr(manufacturing, "_model", lambda value: fake_model)
    monkeypatch.setattr(
        manufacturing,
        "inspect_manufacturing_hints_rdescriptor",
        lambda model, **options: {
            "hints": [
                {
                    "kind": "revolution_region_candidate",
                    "entity_ids": ["face:0"],
                    "highlight_entity_ids": ["face:0"],
                }
            ]
        },
    )
    monkeypatch.setattr(render, "_mesh_polydata", lambda shapes, *args: tuple(shapes))
    monkeypatch.setattr(render, "_edge_polydata", lambda shapes, **kwargs: tuple(shapes))

    def capture_render(context, output_path, **kwargs):
        captured.update(kwargs)
        return output_path

    monkeypatch.setattr(render, "_render_polydata_views", capture_render)

    brep.render_manufacturing_hints_rpath(
        fake_model,
        tmp_path / "revolution.png",
        feature_kinds=("revolution",),
    )

    assert captured["highlighted_groups"] == [
        (("face:0",), (6 / 255, 182 / 255, 212 / 255), 1.0)
    ]
    assert captured["legend"] == [
        ("Revolution candidates", (6 / 255, 182 / 255, 212 / 255))
    ]


def test_manufacturing_hints_reject_active_graph_session():
    shape = scad.make_box_rsolid(2.0, 2.0, 0.2).wrapped

    with scad.GraphSession():
        with pytest.raises(RuntimeError, match="cannot run inside an active GraphSession"):
            brep.inspect_manufacturing_hints_rdescriptor(
                shape,
                feature_kinds=("hole", "extrusion"),
            )

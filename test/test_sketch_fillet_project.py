"""fillet_corner_rsketch / chamfer_corner_rsketch / project_rsketch: corner rounding and reference geometry.

Sketches are built with the public add_* / constrain_* functions; results are read through ``Sketch.to_dict()``, the diff
report and ``inspect_sketch_rsketchresult``.
"""

from __future__ import annotations

import json
import math

import pytest

import simplecadapi as scad
from simplecadapi.recording.serializer import export_graph_json, import_graph_json, replay_graph


def rectangle(dimensions=True, name="rect"):
    """10 x 6, anchored at a, H/V lines; the corner b joins l0 (bottom) and l1 (right side)."""
    sketch = scad.make_sketch_rsketch(name)
    for pid, xy in {"a": (0, 0), "b": (10, 0), "c": (10, 6), "d": (0, 6)}.items():
        sketch = scad.add_point_rsketch(sketch, pid, *xy)
    for lid, p, q in [("l0", "a", "b"), ("l1", "b", "c"), ("l2", "c", "d"), ("l3", "d", "a")]:
        sketch = scad.add_line_rsketch(sketch, lid, p, q)
    sketch = scad.constrain_fix_rsketch(sketch, "a")
    for lid in ("l0", "l2"):
        sketch = scad.constrain_horizontal_rsketch(sketch, lid)
    for lid in ("l1", "l3"):
        sketch = scad.constrain_vertical_rsketch(sketch, lid)
    if dimensions:
        sketch = scad.constrain_length_rsketch(sketch, "l0", 10.0)
        sketch = scad.constrain_length_rsketch(sketch, "l1", 6.0)
    return sketch


def entity(sketch, eid):
    return next(e for e in sketch.to_dict()["entities"] if e["id"] == eid)


def xy(sketch, pid):
    e = entity(sketch, pid)
    return (e["x"], e["y"])


def kinds(sketch):
    return [c["kind"] for c in sketch.to_dict()["constraints"]]


def detail(caught):
    return str(caught.value)


# ---- fillet ---------------------------------------------------------------------------------------------------------------


def test_fillet_a_rectangle_corner_makes_a_tangent_arc_counter_clockwise():
    before = rectangle()
    after = scad.fillet_corner_rsketch(before, "l0", "l1", 2.0)
    arc = entity(after, "a1")
    assert arc["kind"] == "arc"
    assert xy(after, arc["start"]) == pytest.approx((8.0, 0.0))
    assert xy(after, arc["end"]) == pytest.approx((10.0, 2.0))
    assert xy(after, arc["center"]) == pytest.approx((8.0, 2.0))
    assert entity(after, "l0")["end"] == arc["start"] and entity(after, "l1")["start"] == arc["end"]
    kinds_after = kinds(after)
    assert kinds_after.count("tangent") == 2 and kinds_after.count("radius") == 1
    assert kinds_after.count("horizontal") == 2 and kinds_after.count("vertical") == 2  # kept
    assert kinds_after.count("length") == 0  # the dimensions on the shortened lines no longer hold
    diff = scad.diff_sketch_rsketchdiff(before, after)
    assert "b" in diff["removed"]  # the corner point
    assert sorted(diff["removed_constraints"]) == ["c_length_0", "c_length_1"]
    assert diff["created"] == ["p1", "p2", "p3", "a1"]
    notes = after.get_metadata("last_edit")["notes"]
    assert any("c_length_0" in n and "dropped" in n for n in notes)


def test_the_fillet_survives_a_resolve_and_the_profile_is_a_closed_wire_with_the_arc():
    after = scad.fillet_corner_rsketch(rectangle(), "l0", "l1", 2.0)
    result = scad.inspect_sketch_rsketchresult(after, strict=False)
    assert result.status in ("solved", "underconstrained")
    assert result.dof == 2  # the two lengths that were dropped; nothing else is loose
    wire = scad.make_wire_from_sketch_rwire(after)
    assert wire.is_closed and len(scad.ql.edges().resolve(wire)) == 5
    face = scad.make_face_from_sketch_rface(after)
    # 10 x 6 minus the corner the quarter circle leaves out: r^2 (1 - pi/4)
    assert face.get_area() == pytest.approx(60.0 - 4.0 * (1.0 - math.pi / 4.0), rel=1e-6)


def test_the_radius_dimension_is_driving():
    after = scad.fillet_corner_rsketch(rectangle(), "l0", "l1", 2.0)
    radius = next(c for c in after.to_dict()["constraints"] if c["kind"] == "radius")
    assert radius["value"] == 2.0 and radius["driving"] is True and radius["targets"][0]["entity_id"] == "a1"


def test_an_oblique_corner_puts_the_tangent_points_at_r_over_tan_half_the_angle():
    sketch = scad.make_sketch_rsketch("oblique")
    sketch = scad.add_point_rsketch(sketch, "a", 0, 0)
    sketch = scad.add_point_rsketch(sketch, "b", 10, 0)
    sketch = scad.add_point_rsketch(sketch, "c", 10 + 10 * math.cos(2 * math.pi / 3), 10 * math.sin(2 * math.pi / 3))
    sketch = scad.add_line_rsketch(sketch, "l0", "a", "b")
    sketch = scad.add_line_rsketch(sketch, "l1", "b", "c")
    after = scad.fillet_corner_rsketch(sketch, "l0", "l1", 1.0)
    arc = entity(after, "a1")
    reach = 1.0 / math.tan(math.radians(30))
    for role in ("start", "end"):
        x, y = xy(after, arc[role])
        assert math.hypot(x - 10.0, y) == pytest.approx(reach)
    cx, cy = xy(after, arc["center"])
    for role in ("start", "end"):
        x, y = xy(after, arc[role])
        assert math.hypot(x - cx, y - cy) == pytest.approx(1.0)


def test_a_corner_point_that_a_constraint_uses_stays_with_construction_legs():
    sketch = scad.constrain_distance_rsketch(rectangle(), "b", "d", math.hypot(10, 6), constraint_id="diag")
    after = scad.fillet_corner_rsketch(sketch, "l0", "l1", 2.0)
    assert "b" in {e["id"] for e in after.to_dict()["entities"]}
    legs = [e for e in after.to_dict()["entities"] if e["kind"] == "line" and e["construction"]]
    assert len(legs) == 2 and kinds(after).count("collinear") == 2
    assert scad.inspect_sketch_rsketchresult(after, strict=False).dof == 1
    assert any("still used by constraints" in n for n in after.get_metadata("last_edit")["notes"])


def test_fillet_refusals_name_the_ids_and_the_maximum_radius():
    sketch = scad.make_sketch_rsketch("refuse")
    for pid, p in {"a": (0, 0), "b": (10, 0), "c": (10, 6), "d": (20, 0)}.items():
        sketch = scad.add_point_rsketch(sketch, pid, *p)
    for lid, p, q in [("h", "a", "b"), ("v", "b", "c"), ("w", "b", "d"), ("z", "c", "d")]:
        sketch = scad.add_line_rsketch(sketch, lid, p, q)
    sketch = scad.add_circle_rsketch(sketch, "k", "a", 1.0)
    cases = [
        (("h", "w", 1.0), "parallel"),
        (("h", "z", 1.0), "do not share an end point"),
        (("h", "v", 7.0), "allows a radius of at most 6"),
        (("h", "v", 0.0), "greater than zero"),
        (("h", "v", -2.0), "greater than zero"),
        (("h", "v", float("nan")), "finite number"),
        (("h", "h", 1.0), "two different lines"),
        (("h", "nope", 1.0), "'nope'"),
        (("h", "k", 1.0), "is a circle"),
    ]
    for args, expected in cases:
        with pytest.raises(ValueError) as caught:
            scad.fillet_corner_rsketch(sketch, *args)
        text = detail(caught)
        assert "Operation: fillet_corner_rsketch" in text and expected in text, (args, text)


def test_the_input_sketch_is_not_changed_and_the_result_is_deterministic():
    before = rectangle()
    snapshot = json.dumps(before.to_dict(), sort_keys=True)
    one = scad.fillet_corner_rsketch(before, "l0", "l1", 2.0)
    assert json.dumps(before.to_dict(), sort_keys=True) == snapshot
    two = scad.fillet_corner_rsketch(before, "l0", "l1", 2.0)
    assert json.dumps(one.to_dict(), sort_keys=True) == json.dumps(two.to_dict(), sort_keys=True)


def test_lines_may_be_given_in_either_order_and_meet_at_either_end():
    for a, b in (("l0", "l1"), ("l1", "l0")):
        after = scad.fillet_corner_rsketch(rectangle(), a, b, 1.5)
        arc = entity(after, "a1")
        assert xy(after, arc["center"]) == pytest.approx((8.5, 1.5))
        assert scad.inspect_sketch_rsketchresult(after, strict=False).status != "conflicting"


# ---- chamfer --------------------------------------------------------------------------------------------------------------


def test_chamfer_cuts_the_corner_at_the_distance_along_each_line():
    before = rectangle()
    after = scad.chamfer_corner_rsketch(before, "l0", "l1", 2.0)
    cut = entity(after, "l4")
    assert xy(after, cut["start"]) == pytest.approx((8.0, 0.0)) and xy(after, cut["end"]) == pytest.approx((10.0, 2.0))
    assert "b" not in {e["id"] for e in after.to_dict()["entities"]}
    assert kinds(after).count("angle") == 1 and kinds(after).count("length") == 1  # the chamfer's own
    assert scad.inspect_sketch_rsketchresult(after, strict=False).status != "conflicting"
    face = scad.make_face_from_sketch_rface(after)
    assert face.get_area() == pytest.approx(60.0 - 2.0, rel=1e-6)
    with pytest.raises(ValueError) as caught:
        scad.chamfer_corner_rsketch(before, "l0", "l1", 6.0)
    assert "Operation: chamfer_corner_rsketch" in detail(caught) and "less than 6" in detail(caught)
    with pytest.raises(ValueError) as caught:
        scad.chamfer_corner_rsketch(before, "l0", "l2", 1.0)
    assert "do not share an end point" in detail(caught)


# ---- project ---------------------------------------------------------------------------------------------------------------


def front_view():
    sketch = scad.make_sketch_rsketch("front", plane="XZ", sketch_id="front")
    for pid, p in {"a": (0, 0), "b": (10, 0), "c": (10, 6), "o": (5, 3)}.items():
        sketch = scad.add_point_rsketch(sketch, pid, *p)
    sketch = scad.add_line_rsketch(sketch, "l", "a", "b")
    sketch = scad.add_line_rsketch(sketch, "m", "b", "c")
    return scad.add_circle_rsketch(sketch, "k", "o", 2.0)


def plan_sketch():
    return scad.make_sketch_rsketch("plan", sketch_id="plan")


def test_project_a_front_view_onto_the_plan_through_both_frames():
    out = scad.project_rsketch(plan_sketch(), front_view())
    line = entity(out, "proj_front_3")
    assert line["kind"] == "line" and line["construction"] is True
    assert xy(out, line["start"]) == pytest.approx((0.0, 0.0)) and xy(out, line["end"]) == pytest.approx((10.0, 0.0))
    # the circle of the front view is seen edge on: a line from x = 7 to x = 3
    edge_on = entity(out, "proj_front_6")
    assert edge_on["kind"] == "line"
    assert {xy(out, edge_on["start"]), xy(out, edge_on["end"])} == {(7.0, 0.0), (3.0, 0.0)} or (
        xy(out, edge_on["start"]) == pytest.approx((7.0, 0.0)) and xy(out, edge_on["end"]) == pytest.approx((3.0, 0.0))
    )
    fixed = [c["targets"][0]["entity_id"] for c in out.to_dict()["constraints"] if c["kind"] == "fix"]
    assert fixed == ["proj_front_3", "proj_front_6"]
    assert scad.inspect_sketch_rsketchresult(out, strict=False).dof == 0
    projections = out.get_metadata("projections")
    assert projections[0] == {"source": "front", "entity": "l", "projected": "proj_front_3"}
    assert [p["entity"] for p in projections] == ["l", "m", "k"]


def test_a_sketch_can_be_constrained_to_projected_geometry():
    out = scad.project_rsketch(plan_sketch(), front_view(), entities=["l"])
    out = scad.add_point_rsketch(out, "mine", 4.0, 3.0)
    out = scad.add_point_rsketch(out, "tail", 1.0, 1.0)
    out = scad.add_line_rsketch(out, "mine_line", "tail", "mine")
    out = scad.constrain_point_on_rsketch(out, "tail", "proj_front_3")
    result = scad.inspect_sketch_rsketchresult(out, strict=False)
    assert result.status != "conflicting"
    solved = {k: v for k, v in result.solved_points.items()}
    assert solved["tail"][1] == pytest.approx(0.0, abs=1e-9)  # it sits on the projected line y = 0


def test_project_parallel_planes_copy_circles_and_arcs_and_a_flipped_plane_keeps_the_shape():
    up = scad.make_sketch_rsketch("up", sketch_id="up")
    for pid, p in {"o": (1, 2), "s": (3, 2), "e": (1, 4)}.items():
        up = scad.add_point_rsketch(up, pid, *p)
    up = scad.add_arc_rsketch(up, "arc", "s", "e", "o")
    up = scad.add_circle_rsketch(up, "k", "o", 0.5)
    flipped = scad.make_sketch_rsketch(
        "down",
        sketch_id="down",
        plane={"origin": (0, 0, 5), "x_axis": (1, 0, 0), "y_axis": (0, -1, 0)},
    )
    for pid, p in {"o": (1, -2), "s": (3, -2), "e": (1, -4)}.items():
        flipped = scad.add_point_rsketch(flipped, pid, *p)
    flipped = scad.add_arc_rsketch(flipped, "arc", "s", "e", "o")
    target = plan_sketch()
    same = scad.project_rsketch(target, up, entities=["arc", "k"])
    arc = entity(same, "proj_up_4")
    assert arc["kind"] == "arc" and xy(same, arc["start"]) == pytest.approx((3.0, 2.0))
    circle = entity(same, "proj_up_5")
    assert circle["kind"] == "circle" and circle["radius"] == pytest.approx(0.5)
    reversed_ = scad.project_rsketch(target, flipped, entities=["arc"])
    copy = entity(reversed_, "proj_down_4")
    # seen from +z the flipped sketch runs clockwise: the same arc has its ends swapped
    assert xy(reversed_, copy["start"]) == pytest.approx((1.0, 4.0)) and xy(reversed_, copy["end"]) == pytest.approx((3.0, 2.0))


def test_an_oblique_circle_becomes_an_ellipse_and_an_oblique_arc_is_refused():
    c, s = math.cos(math.pi / 3), math.sin(math.pi / 3)
    tilted = scad.make_sketch_rsketch(
        "tilt", sketch_id="tilt", plane={"origin": (0, 0, 0), "x_axis": (1, 0, 0), "y_axis": (0, c, s)}
    )
    for pid, p in {"o": (0, 0), "p": (2, 0), "q": (0, 2)}.items():
        tilted = scad.add_point_rsketch(tilted, pid, *p)
    tilted = scad.add_circle_rsketch(tilted, "k", "o", 2.0)
    tilted = scad.add_arc_rsketch(tilted, "arc", "p", "q", "o")
    out = scad.project_rsketch(plan_sketch(), tilted, entities=["k"])
    ellipse = entity(out, "proj_tilt_4")
    assert ellipse["kind"] == "ellipse"
    assert xy(out, ellipse["major"]) == pytest.approx((2.0, 0.0), abs=1e-9)
    assert xy(out, ellipse["minor"]) == pytest.approx((0.0, 2.0 * c), abs=1e-9)
    with pytest.raises(ValueError) as caught:
        scad.project_rsketch(plan_sketch(), tilted, entities=["arc"])
    assert "'arc' is an arc in a plane oblique" in detail(caught)


def test_project_the_edges_of_a_solid_or_a_ql_selection():
    box = scad.make_box_rsolid(4.0, 3.0, 2.0)
    out = scad.project_rsketch(plan_sketch(), box)
    lines = [e for e in out.to_dict()["entities"] if e["kind"] == "line"]
    assert len(lines) == 4  # top and bottom coincide; the vertical edges are points
    xs = sorted({xy(out, l["start"])[0] for l in lines} | {xy(out, l["end"])[0] for l in lines})
    assert xs == pytest.approx([-2.0, 2.0])
    cylinder = scad.make_cylinder_rsolid(2.0, 5.0)
    circles = scad.project_rsketch(plan_sketch(), scad.ql.edges().resolve(cylinder))
    assert [e["kind"] for e in circles.to_dict()["entities"] if e["kind"] == "circle"] == ["circle"]
    assert all(e["id"].startswith("proj_shape_") for e in circles.to_dict()["entities"])
    top_edges = scad.ql.edges().where(scad.ql.curve_type("LINE")).resolve(box)
    assert top_edges and scad.project_rsketch(plan_sketch(), top_edges)


def test_project_ids_never_collide_and_a_repeat_reuses_the_projected_entities():
    target = scad.add_point_rsketch(plan_sketch(), "proj_front_1", 99.0, 99.0)
    out = scad.project_rsketch(target, front_view(), entities=["l"])
    assert xy(out, "proj_front_1") == (99.0, 99.0)
    assert "proj_front_2" in {e["id"] for e in out.to_dict()["entities"]}
    once = scad.project_rsketch(plan_sketch(), front_view())
    twice = scad.project_rsketch(once, front_view())
    assert twice.to_dict()["entities"] == once.to_dict()["entities"]
    assert twice.to_dict()["constraints"] == once.to_dict()["constraints"]
    assert twice.get_metadata("projections") == once.get_metadata("projections")


def test_project_refusals_name_the_entity_and_the_argument():
    cases = [
        (dict(source=front_view(), entities=["zz"]), "'zz'"),
        (dict(source=front_view(), entities=[]), "entities is empty"),
        (dict(source=front_view(), entities=["o"], construction=True), None),
        (dict(source=42), "source must be a Sketch"),
        (dict(source=[1, 2]), "source lists must hold shapes"),
        (dict(source=scad.make_box_rsolid(1, 1, 1), entities=["l"]), "entities selects entities of a source sketch"),
    ]
    for kwargs, expected in cases:
        if expected is None:
            scad.project_rsketch(plan_sketch(), **kwargs)  # a point is fine
            continue
        with pytest.raises(ValueError) as caught:
            scad.project_rsketch(plan_sketch(), **kwargs)
        assert "Operation: project_rsketch" in detail(caught) and expected in detail(caught), detail(caught)
    with pytest.raises(ValueError) as caught:
        scad.project_rsketch(front_view(), front_view())
    assert "cannot be projected onto itself" in detail(caught)
    spline = scad.make_sketch_rsketch("spl", sketch_id="spl")
    for pid, p in {"s": (0, 0), "e": (4, 0), "m1": (0, 1), "m2": (1, 2), "m3": (3, 2), "m4": (4, 1)}.items():
        spline = scad.add_point_rsketch(spline, pid, *p)
    spline = scad.add_bspline_rsketch(spline, "bs", "s", "e", ["s", "m2", "m3", "e"], degree=3)
    spline = scad.add_line_rsketch(spline, "ln", "s", "e")
    out = scad.project_rsketch(plan_sketch(), spline)  # default: skipped and reported, not hidden
    assert any("skipped bs" in n for n in out.get_metadata("last_edit")["notes"])
    with pytest.raises(ValueError) as caught:
        scad.project_rsketch(plan_sketch(), spline, entities=["bs"])
    assert "only points, lines, circles and arcs" in detail(caught)


def test_construction_false_makes_real_geometry_still_fixed():
    out = scad.project_rsketch(plan_sketch(), front_view(), entities=["l"], construction=False)
    assert entity(out, "proj_front_3")["construction"] is False


# ---- recording and replay -------------------------------------------------------------------------------------------------


def test_fillet_chamfer_and_project_are_recorded_and_replayed_from_model_json():
    with scad.GraphSession() as session:
        sketch = rectangle()
        sketch = scad.fillet_corner_rsketch(sketch, "l0", "l1", 2.0)
        sketch = scad.chamfer_corner_rsketch(sketch, "l2", "l3", 1.0)
        plan = scad.project_rsketch(sketch, front_view(), entities=["l"])
        session.capture_result(value=scad.extrude_rsolid(scad.make_face_from_sketch_rface(plan), (0, 0, 1), 1))
    payload = json.loads(export_graph_json(session.graph))
    ops = [n["op"] for n in payload["nodes"]]
    assert {"fillet_corner_rsketch", "chamfer_corner_rsketch", "project_rsketch"} <= set(ops)
    fillet = next(n for n in payload["nodes"] if n["op"] == "fillet_corner_rsketch")
    assert fillet["params"]["a"] == "l0" and fillet["params"]["b"] == "l1" and fillet["params"]["radius"] == 2.0
    project = next(n for n in payload["nodes"] if n["op"] == "project_rsketch")
    assert project["params"]["source_kind"] == "sketch" and project["params"]["entities"] == ["l"]
    assert len(project["inputs"]) == 2  # the sketch and the source sketch
    rebuilt = replay_graph(import_graph_json(json.dumps(payload)))
    # 10 x 6, minus the quarter-circle corner (r = 2) and the chamfer (distance 1)
    assert rebuilt[0].get_volume() == pytest.approx(60.0 - 4.0 * (1 - math.pi / 4) - 0.5, rel=1e-6)


def test_project_from_shape_edges_is_recorded_and_replayed():
    with scad.GraphSession() as session:
        box = scad.make_box_rsolid(4.0, 3.0, 2.0)
        edges = scad.ql.edges().where(scad.ql.curve_type("LINE")).resolve(box)
        plan = scad.project_rsketch(scad.make_sketch_rsketch("plan"), edges)
        session.capture_result(value=plan)
    payload = json.loads(export_graph_json(session.graph))
    project = next(n for n in payload["nodes"] if n["op"] == "project_rsketch")
    assert project["params"]["source_kind"] == "shapes"
    rebuilt = replay_graph(import_graph_json(json.dumps(payload)))
    assert [e["id"] for e in rebuilt[0].to_dict()["entities"] if e["kind"] == "line"] == [
        e["id"] for e in plan.to_dict()["entities"] if e["kind"] == "line"
    ]


def test_a_failing_edit_leaves_no_node_behind():
    with scad.GraphSession() as session:
        with pytest.raises(ValueError):
            scad.fillet_corner_rsketch(rectangle(), "l0", "l1", 99.0)
        with pytest.raises(ValueError):
            scad.project_rsketch(plan_sketch(), front_view(), entities=["zz"])
    ops = [n["op"] for n in json.loads(export_graph_json(session.graph))["nodes"]]
    assert "fillet_corner_rsketch" not in ops and "project_rsketch" not in ops


def test_a_var_radius_keeps_the_parameter_in_the_graph():
    radius = scad.var("fillet_r", 2.0)
    with scad.GraphSession() as session:
        sketch = scad.fillet_corner_rsketch(rectangle(), "l0", "l1", radius)
        session.capture_result(value=scad.make_wire_from_sketch_rwire(sketch))
    node = next(n for n in json.loads(export_graph_json(session.graph))["nodes"] if n["op"] == "fillet_corner_rsketch")
    assert node["params"]["radius"] == 2.0

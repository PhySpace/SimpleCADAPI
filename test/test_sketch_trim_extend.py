"""trim_rsketch / extend_rsketch / diff_sketch_rsketchdiff: sketch edits that work on the solved geometry.

Sketches are built with the public add_* / constrain_* functions; results are read through ``Sketch.to_dict()``, the
diff report and ``inspect_sketch_rsketchresult``.
"""

from __future__ import annotations

import json
import math

import pytest

import simplecadapi as scad
from simplecadapi._cpp.occt.BRepGProp import BRepGProp
from simplecadapi._cpp.occt.GProp import GProp_GProps
from simplecadapi.recording.serializer import export_graph_json, import_graph_json, replay_graph


def build(points, entities, constraints=()):
    """A sketch from {id: (x, y)}, [(kind, id, ...)] and [(function, args, kwargs)]."""
    sketch = scad.make_sketch_rsketch("edit")
    for pid, (x, y) in points.items():
        sketch = scad.add_point_rsketch(sketch, pid, x, y)
    for kind, eid, *args in entities:
        if kind == "line":
            sketch = scad.add_line_rsketch(sketch, eid, *args)
        elif kind == "circle":
            sketch = scad.add_circle_rsketch(sketch, eid, *args)
        else:
            sketch = scad.add_arc_rsketch(sketch, eid, *args)
    for function, args, kwargs in constraints:
        sketch = function(sketch, *args, **kwargs)
    return sketch


def plus(with_horizontal=True):
    """A horizontal line crossed by a vertical one at (5, 0)."""
    constraints = [(scad.constrain_horizontal_rsketch, ("h",), {"constraint_id": "k1"})] if with_horizontal else []
    return build(
        {"a": (0, 0), "b": (10, 0), "c": (5, -5), "d": (5, 5)},
        [("line", "h", "a", "b"), ("line", "v", "c", "d")],
        constraints,
    )


def points_of(sketch):
    return {e["id"]: (e["x"], e["y"]) for e in sketch.to_dict()["entities"] if e["kind"] == "point"}


def entities_of(sketch, kind):
    return [e for e in sketch.to_dict()["entities"] if e["kind"] == kind]


def constraints_of(sketch, kind):
    return [c for c in sketch.to_dict()["constraints"] if c["kind"] == kind]


def x_spans(sketch):
    pts = points_of(sketch)
    return sorted(
        (round(min(pts[e["start"]][0], pts[e["end"]][0]), 6), round(max(pts[e["start"]][0], pts[e["end"]][0]), 6))
        for e in entities_of(sketch, "line")
    )


def line_at(sketch, x, y):
    """The id of the line that passes through (x, y)."""
    pts = points_of(sketch)
    for e in entities_of(sketch, "line"):
        (x1, y1), (x2, y2) = pts[e["start"]], pts[e["end"]]
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        inside = min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9
        if abs(cross) < 1e-9 and inside:
            return e["id"]
    raise AssertionError(f"no line through {(x, y)}")


def assert_solves(sketch):
    assert scad.inspect_sketch_rsketchresult(sketch, strict=False).status in ("solved", "underconstrained")


# ---- the eight behaviours of the editor prototype ---------------------------------------------------------------------


def test_trim_removes_the_piece_between_the_crossings_and_ties_the_cut_to_the_cutter():
    before = plus()
    after = scad.trim_rsketch(before, "h", (8.0, 0.0))
    diff = scad.diff_sketch_rsketchdiff(before, after)
    assert "h" in diff["removed"] and (0.0, 5.0) in x_spans(after)
    assert any(e["id"] == "v" for e in entities_of(after, "line")), "the cutter stays"
    cut = constraints_of(after, "point_on")[0]
    assert cut["targets"][1]["entity_id"] == "v" and cut["targets"][0]["entity_id"] in diff["created"]
    # the piece keeps the horizontal constraint of the line it came from; the old one is reported removed
    assert constraints_of(after, "horizontal") and "k1" in diff["removed_constraints"]
    assert_solves(after)


def test_trim_the_middle_of_a_line_leaves_two_pieces():
    sketch = build(
        {"a": (0, 0), "b": (10, 0), "c": (3, -5), "d": (3, 5), "e": (7, -5), "f": (7, 5)},
        [("line", "h", "a", "b"), ("line", "v1", "c", "d"), ("line", "v2", "e", "f")],
    )
    after = scad.trim_rsketch(sketch, "h", at=(5.0, 0.0))
    pts = points_of(after)
    pieces = sorted(
        (round(min(pts[e["start"]][0], pts[e["end"]][0]), 6), round(max(pts[e["start"]][0], pts[e["end"]][0]), 6))
        for e in entities_of(after, "line")
        if pts[e["start"]][1] == pytest.approx(0.0) and pts[e["end"]][1] == pytest.approx(0.0)
    )
    assert pieces == [(0.0, 3.0), (7.0, 10.0)]
    diff = scad.diff_sketch_rsketchdiff(sketch, after)
    assert len(diff["created"]) == 4 and len(diff["created_constraints"]) == 2
    assert_solves(after)


def test_trim_a_line_with_nothing_crossing_it_removes_it_whole_and_says_so():
    sketch = build({"a": (0, 0), "b": (10, 0)}, [("line", "h", "a", "b")])
    after = scad.trim_rsketch(sketch, "h", (5.0, 0.0))
    assert after.to_dict()["entities"] == []
    diff = scad.diff_sketch_rsketchdiff(sketch, after)
    assert diff["removed"] == ["a", "b", "h"] and not diff["created"]
    assert any("removed whole" in note for note in after.get_metadata("last_edit")["notes"])


def test_trim_a_circle_between_two_lines_leaves_an_arc():
    sketch = build({"o": (0, 0), "a": (-5, 2), "b": (5, 2)}, [("circle", "c", "o", 4.0), ("line", "l", "a", "b")])
    after = scad.trim_rsketch(sketch, "c", (0.0, 4.0))  # the cap above the line goes
    arcs = entities_of(after, "arc")
    assert len(arcs) == 1 and not entities_of(after, "circle")
    pts = points_of(after)
    sx, sy = pts[arcs[0]["start"]]
    ex, ey = pts[arcs[0]["end"]]
    # the long arc underneath: counter-clockwise from the left crossing, round the bottom, to the right one
    assert sx < 0 < ex and sy == pytest.approx(2.0) and ey == pytest.approx(2.0)
    assert arcs[0]["center"] == "o"
    # promoted to a wire, the arc is the long one: 240 degrees of a radius-4 circle
    wire = scad.make_wire_from_sketch_rwire(after, profile=0, strict=False)
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(wire.wrapped, props)
    assert props.Mass() == pytest.approx(4.0 * 4.0 * math.pi / 3.0, rel=1e-9)


def test_trim_an_arc_at_a_crossing_keeps_the_far_side():
    sketch = build(
        {"o": (0, 0), "s": (4, 0), "e": (-4, 0), "p": (0, 1), "q": (0, 6)},
        [("arc", "a", "s", "e", "o"), ("line", "l", "p", "q")],
    )
    after = scad.trim_rsketch(sketch, "a", (-2.0, 3.4))  # on the left half of the arc
    arcs = entities_of(after, "arc")
    assert len(arcs) == 1
    pts = points_of(after)
    assert pts[arcs[0]["start"]] == pytest.approx((4.0, 0.0), abs=1e-6)
    assert pts[arcs[0]["end"]] == pytest.approx((0.0, 4.0), abs=1e-6)
    assert_solves(after)


def test_extend_moves_the_end_onto_the_next_entity():
    sketch = build(
        {"a": (0, 0), "b": (3, 0), "c": (8, -4), "d": (8, 4)},
        [("line", "h", "a", "b"), ("line", "wall", "c", "d")],
        [(scad.constrain_length_rsketch, ("h", 3.0), {"constraint_id": "k1"})],
    )
    after = scad.extend_rsketch(sketch, "h", "end")
    assert points_of(after)["b"] == pytest.approx((8.0, 0.0))
    (tie,) = constraints_of(after, "point_on")
    assert [t["entity_id"] for t in tie["targets"]] == ["b", "wall"]
    diff = scad.diff_sketch_rsketchdiff(sketch, after)
    assert diff["removed_constraints"] == ["k1"] and diff["changed"] == ["b"]
    assert_solves(after)


def test_operations_refuse_what_they_cannot_do_and_name_the_ids():
    with pytest.raises(ValueError, match="there is no entity 'zz'"):
        scad.trim_rsketch(plus(), "zz", (0.0, 0.0))
    with pytest.raises(ValueError, match="nothing is ahead of the end of 'h'"):
        scad.extend_rsketch(plus(), "h", "end")
    with pytest.raises(TypeError, match="at is a point"):
        scad.trim_rsketch(plus(), "h", [1, 2, 3])
    with pytest.raises(ValueError, match="there is no point 'middle'"):
        scad.trim_rsketch(plus(), "h", "middle")


def test_the_same_call_on_the_same_sketch_gives_the_same_sketch():
    sketch = plus()
    first = scad.trim_rsketch(sketch, entity="h", at=(8.0, 0.0))
    second = scad.trim_rsketch(sketch, entity="h", at=(8.0, 0.0))
    assert first.to_dict() == second.to_dict()
    assert scad.diff_sketch_rsketchdiff(sketch, first) == scad.diff_sketch_rsketchdiff(sketch, second)


# ---- more of the semantics ----------------------------------------------------------------------------------------------


def test_new_ids_are_the_lowest_free_numbers_and_never_reuse_removed_ones():
    sketch = build(
        {"a": (0, 0), "b": (10, 0), "c": (5, -5), "d": (5, 5), "p1": (20, 20)},
        [("line", "h", "a", "b"), ("line", "v", "c", "d"), ("line", "l1", "a", "c")],
        [(scad.constrain_horizontal_rsketch, ("h",), {})],
    )
    after = scad.trim_rsketch(sketch, "h", (8.0, 0.0))
    diff = scad.diff_sketch_rsketchdiff(sketch, after)
    assert diff["created"] == ["p2", "l2"]  # p1 and l1 were taken
    assert diff["created_constraints"] == ["c_horizontal_1", "c_point_on_0"]  # c_horizontal_0 was removed, not reused


def test_at_can_be_a_point_id_and_against_limits_the_cutters():
    sketch = build(
        {"a": (0, 0), "b": (10, 0), "c": (3, -5), "d": (3, 5), "e": (7, -5), "f": (7, 5), "m": (8, 0)},
        [("line", "h", "a", "b"), ("line", "v1", "c", "d"), ("line", "v2", "e", "f")],
    )
    only_v1 = scad.trim_rsketch(sketch, "h", "m", against=["v1"])
    assert (0.0, 3.0) in x_spans(only_v1) and (3.0, 10.0) not in x_spans(only_v1)
    with pytest.raises(ValueError, match="against names 'nope'"):
        scad.trim_rsketch(sketch, "h", (1.0, 0.0), against=["nope"])
    with pytest.raises(ValueError, match="against names 'h', the entity being cut"):
        scad.trim_rsketch(sketch, "h", (1.0, 0.0), against=["h"])


def test_construction_entities_do_not_cut_unless_named():
    sketch = build(
        {"a": (0, 0), "b": (10, 0), "c": (5, -5), "d": (5, 5)},
        [("line", "h", "a", "b")],
    )
    sketch = scad.add_line_rsketch(sketch, "guide", "c", "d", construction=True)
    assert [e["id"] for e in entities_of(scad.trim_rsketch(sketch, "h", (8.0, 0.0)), "line")] == ["guide"]
    after = scad.trim_rsketch(sketch, "h", (8.0, 0.0), against=["guide"])
    assert (0.0, 5.0) in x_spans(after)


def test_constraints_on_endpoints_stay_and_constraints_on_the_removed_line_go():
    sketch = build(
        {"a": (0, 0), "b": (10, 0), "c": (5, -5), "d": (5, 5)},
        [("line", "h", "a", "b"), ("line", "v", "c", "d")],
        [
            (scad.constrain_fix_rsketch, ("h.start",), {"constraint_id": "fixed"}),
            (scad.constrain_length_rsketch, ("h", 10.0), {"constraint_id": "len"}),
            (scad.constrain_perpendicular_rsketch, ("h", "v"), {"constraint_id": "perp"}),
        ],
    )
    after = scad.trim_rsketch(sketch, "h", (2.0, 0.0))  # the piece 0..5 goes, so h.start loses its line
    diff = scad.diff_sketch_rsketchdiff(sketch, after)
    assert sorted(diff["removed_constraints"]) == ["len", "perp"]
    fixed = next(c for c in after.to_dict()["constraints"] if c["id"] == "fixed")
    assert fixed["targets"][0]["entity_id"] == "a" and fixed["targets"][0]["subentity"] == "geometry"
    assert "a" in points_of(after), "a point that a constraint still names is kept"


def test_a_circle_crossed_once_is_an_error_and_a_circle_crossed_twice_keeps_the_rest():
    once = build({"o": (0, 0), "a": (0, 4), "b": (0, 9)}, [("circle", "c", "o", 4.0), ("line", "l", "a", "b")])
    with pytest.raises(ValueError, match="'c' is crossed once"):
        scad.trim_rsketch(once, "c", (4.0, 0.0))
    free = build({"o": (0, 0)}, [("circle", "c", "o", 4.0)])
    assert not scad.trim_rsketch(free, "c", (4.0, 0.0)).to_dict()["entities"]


def test_circle_with_three_cuts_keeps_the_two_arcs_not_under_the_click():
    sketch = build(
        {"o": (0, 0), "a": (-5, 0), "b": (5, 0), "c": (0, 0.5), "d": (0, 5)},
        [("circle", "c1", "o", 4.0), ("line", "h", "a", "b"), ("line", "v", "c", "d")],
    )
    after = scad.trim_rsketch(sketch, "c1", (0.0, 4.0))  # between the crossing at (-4, 0) and (0, 4) .. (4, 0)
    assert len(entities_of(after, "arc")) == 2
    assert_solves(after)


def test_a_crossing_at_the_end_of_the_line_is_not_a_cut_and_a_close_point_is_reused():
    sketch = build(
        {"a": (0, 0), "b": (10, 0), "c": (10, -5), "d": (10, 5), "e": (4, -5), "f": (4, 5), "near": (4.0, 5e-8)},
        [("line", "h", "a", "b"), ("line", "touch", "c", "d"), ("line", "cut", "e", "f")],
    )
    after = scad.trim_rsketch(sketch, "h", (8.0, 0.0))
    diff = scad.diff_sketch_rsketchdiff(sketch, after)
    assert "near" not in diff["removed"] and not any(c.startswith("p") for c in diff["created"])  # reused, not created
    lines = {e["id"]: e for e in entities_of(after, "line")}
    assert any(e["end"] == "near" for e in lines.values())
    assert (0.0, 4.0) in x_spans(after)


def test_trim_works_on_the_solved_geometry_not_on_the_seeds():
    # the seed of b is far off; a distance and a horizontal constraint put it at (10, 0)
    sketch = build(
        {"a": (0, 0), "b": (9, 3), "c": (5, -5), "d": (5, 5)},
        [("line", "h", "a", "b"), ("line", "v", "c", "d")],
        [
            (scad.constrain_fix_rsketch, ("a",), {}),
            (scad.constrain_fix_rsketch, ("c",), {}),
            (scad.constrain_fix_rsketch, ("d",), {}),
            (scad.constrain_horizontal_rsketch, ("h",), {}),
            (scad.constrain_length_rsketch, ("h", 10.0), {}),
        ],
    )
    after = scad.trim_rsketch(sketch, "h", (8.0, 0.0))
    cut = constraints_of(after, "point_on")[0]["targets"][0]["entity_id"]
    assert points_of(after)[cut] == pytest.approx((5.0, 0.0))  # the seed of b would have given y = 1.67
    assert "b" not in points_of(after) and (0.0, 5.0) in x_spans(after)


def test_trim_arc_into_two_pieces_and_circle_tangent_cases():
    sketch = build(
        {"o": (0, 0), "s": (4, 0), "e": (-4, 0), "p": (-5, 2), "q": (5, 2), "r": (-5, 3), "t": (5, 3)},
        [("arc", "a", "s", "e", "o"), ("line", "l1", "p", "q"), ("line", "l2", "r", "t")],
    )
    after = scad.trim_rsketch(sketch, "a", (0.0, 4.0))  # the cap between the two lines... both cut near the top
    assert len(entities_of(after, "arc")) == 2
    assert_solves(after)


def test_circle_circle_crossings():
    sketch = build(
        {"o": (0, 0), "p": (6, 0)},
        [("circle", "c1", "o", 4.0), ("circle", "c2", "p", 4.0)],
    )
    after = scad.trim_rsketch(sketch, "c1", (4.0, 0.0))
    (arc,) = entities_of(after, "arc")
    pts = points_of(after)
    # the arc that stays runs through the far side (-4, 0); both ends are at x = 3 on the lens
    assert pts[arc["start"]][0] == pytest.approx(3.0) and pts[arc["end"]][0] == pytest.approx(3.0)
    assert sorted((pts[arc["start"]][1], pts[arc["end"]][1])) == pytest.approx([-math.sqrt(7), math.sqrt(7)])
    assert_solves(after)


def test_the_wrong_kind_and_bad_arguments_are_refused():
    sketch = plus()
    with pytest.raises(ValueError, match="'a' is a point: only lines, circles and arcs can be trimmed"):
        scad.trim_rsketch(sketch, "a", (0.0, 0.0))
    with pytest.raises(ValueError, match="end must be 'start' or 'end', got 'middle'"):
        scad.extend_rsketch(sketch, "h", "middle")
    with pytest.raises(ValueError, match="'a' is a point: only lines, circles and arcs can be extended"):
        scad.extend_rsketch(sketch, "a", "end")
    with pytest.raises(ValueError, match="there is no entity 'nope' to extend to"):
        scad.extend_rsketch(sketch, "h", "end", to="nope")
    with pytest.raises(TypeError):
        scad.trim_rsketch(sketch, "h", (True, 0.0))
    with pytest.raises(TypeError):
        scad.trim_rsketch(sketch, "h", ("1", "2"))
    with pytest.raises(ValueError, match="finite point"):
        scad.trim_rsketch(sketch, "h", (float("nan"), 0.0))
    with pytest.raises(TypeError):
        scad.trim_rsketch(sketch, "h")  # at is required


def test_error_messages_are_structured_for_an_agent():
    with pytest.raises(ValueError) as caught:
        scad.trim_rsketch(plus(), "zz", (0.0, 0.0))
    text = str(caught.value)
    assert "Operation: trim_rsketch" in text and "What happened:" in text and "Possible causes:" in text and "How to fix:" in text


def test_extend_a_line_onto_a_circle_and_backwards_from_the_start():
    sketch = build(
        {"o": (10, 0), "a": (0, 0), "b": (3, 0)},
        [("circle", "c", "o", 2.0), ("line", "h", "a", "b")],
    )
    after = scad.extend_rsketch(sketch, "h", "end")
    assert points_of(after)["b"] == pytest.approx((8.0, 0.0))
    tie = constraints_of(after, "point_on")[0]
    assert tie["targets"][1]["entity_id"] == "c"
    wall = build({"a": (3, 0), "b": (6, 0), "c": (-4, -4), "d": (-4, 4)}, [("line", "h", "a", "b"), ("line", "w", "c", "d")])
    moved = scad.extend_rsketch(wall, "h", "start")
    assert points_of(moved)["a"] == pytest.approx((-4.0, 0.0))
    assert points_of(moved)["b"] == pytest.approx((6.0, 0.0))
    assert_solves(moved)


def test_extend_refuses_a_shared_end_point_and_names_the_ids():
    sketch = build(
        {"a": (0, 0), "b": (3, 0), "c": (3, 4), "w1": (8, -4), "w2": (8, 4)},
        [("line", "h", "a", "b"), ("line", "up", "b", "c"), ("line", "wall", "w1", "w2")],
    )
    with pytest.raises(ValueError, match=r"point 'b'.*shared with 'up'"):
        scad.extend_rsketch(sketch, "h", "end")


def test_extend_to_names_the_target_and_drops_dimensions_on_the_moved_point():
    sketch = build(
        {"a": (0, 0), "b": (3, 0), "w1": (8, -4), "w2": (8, 4), "x1": (6, -4), "x2": (6, 4)},
        [("line", "h", "a", "b"), ("line", "far", "w1", "w2"), ("line", "near", "x1", "x2")],
        [
            (scad.constrain_distance_rsketch, ("a", "b", 3.0), {"constraint_id": "span"}),
            (scad.constrain_fix_rsketch, ("a",), {"constraint_id": "anchor"}),
        ],
    )
    default = scad.extend_rsketch(sketch, "h", "end")
    assert points_of(default)["b"][0] == pytest.approx(6.0)  # the nearest one
    far = scad.extend_rsketch(sketch, "h", "end", to="far")
    assert points_of(far)["b"][0] == pytest.approx(8.0)
    diff = scad.diff_sketch_rsketchdiff(sketch, far)
    assert diff["removed_constraints"] == ["span"]  # anchor is on a, not on the moved end


def test_the_input_sketch_is_never_changed():
    sketch = plus()
    snapshot = json.dumps(sketch.to_dict(), sort_keys=True)
    scad.trim_rsketch(sketch, "h", (8.0, 0.0))
    scad.extend_rsketch(build({"a": (0, 0), "b": (3, 0), "c": (8, -4), "d": (8, 4)}, [("line", "h", "a", "b"), ("line", "w", "c", "d")]), "h", "end")
    assert json.dumps(sketch.to_dict(), sort_keys=True) == snapshot


def test_diff_reports_created_removed_and_changed():
    before = plus()
    assert scad.diff_sketch_rsketchdiff(before, before) == {
        "created": [],
        "removed": [],
        "changed": [],
        "created_constraints": [],
        "removed_constraints": [],
        "changed_constraints": [],
    }
    after = scad.add_point_rsketch(before, "z", 1, 1)
    assert scad.diff_sketch_rsketchdiff(before, after)["created"] == ["z"]
    assert scad.diff_sketch_rsketchdiff(after, before)["removed"] == ["z"]


# ---- recording and replay -------------------------------------------------------------------------------------------------


def test_trim_and_extend_are_recorded_and_replayed_from_model_json():
    with scad.GraphSession() as session:
        sketch = scad.make_sketch_rsketch(name="hash")
        for pid, xy in {
            "a1": (-2, 0), "a2": (12, 0), "b1": (-2, 10), "b2": (12, 10),
            "c1": (0, -2), "c2": (0, 12), "d1": (10, -2), "d2": (10, 12),
        }.items():
            sketch = scad.add_point_rsketch(sketch, pid, *xy)
        for lid, a, b in [("h1", "a1", "a2"), ("h2", "b1", "b2"), ("v1", "c1", "c2"), ("v2", "d1", "d2")]:
            sketch = scad.add_line_rsketch(sketch, lid, a, b)
        for click in [(-1.0, 0.0), (11.0, 0.0), (-1.0, 10.0), (11.0, 10.0), (0.0, -1.0), (0.0, 11.0), (10.0, -1.0), (10.0, 11.0)]:
            sketch = scad.trim_rsketch(sketch, line_at(sketch, *click), click)
        # one more edit that goes through extend: lengthen a free line onto the square's right side
        sketch = scad.add_point_rsketch(sketch, "s1", 12, 5)
        sketch = scad.add_point_rsketch(sketch, "s2", 14, 5)
        sketch = scad.add_line_rsketch(sketch, "spur", "s2", "s1")
        sketch = scad.extend_rsketch(sketch, "spur", "end")
        face = scad.make_face_from_sketch_rface(sketch)
        session.capture_result(value=scad.extrude_rsolid(face, (0, 0, 1), 1))
    payload = json.loads(export_graph_json(session.graph))
    recorded = [node["op"] for node in payload["nodes"]]
    assert recorded.count("trim_rsketch") == 8 and recorded.count("extend_rsketch") == 1, recorded
    trim_node = next(n for n in payload["nodes"] if n["op"] == "trim_rsketch")
    assert trim_node["params"]["entity"] == "h1" and trim_node["params"]["at"] == [-1.0, 0.0]
    assert trim_node["params"]["against"] is None
    graph = import_graph_json(json.dumps(payload))
    rebuilt = replay_graph(graph)
    # the loop is a 10 x 10 square after the trims, so the part is 100 mm^3
    assert rebuilt[0].get_volume() == pytest.approx(100.0, rel=1e-6)


def test_an_edit_that_cannot_be_done_leaves_no_node_behind():
    with scad.GraphSession() as session:
        sketch = scad.make_sketch_rsketch(name="x")
        sketch = scad.add_point_rsketch(sketch, "a", 0, 0)
        sketch = scad.add_point_rsketch(sketch, "b", 1, 0)
        sketch = scad.add_line_rsketch(sketch, "h", "a", "b")
        with pytest.raises(ValueError):
            scad.extend_rsketch(sketch, "h", "end")
    payload = json.loads(export_graph_json(session.graph))
    assert [n["op"] for n in payload["nodes"]].count("extend_rsketch") == 0


def test_point_id_at_against_and_to_survive_model_json_replay():
    with scad.GraphSession() as session:
        sketch = scad.make_sketch_rsketch(name="args")
        for pid, xy in {"a": (0, 0), "b": (10, 0), "c": (3, -5), "d": (3, 5), "m": (8, 0), "s1": (5, 8), "s2": (5, 9),
                        "w1": (-5, 12), "w2": (15, 12)}.items():
            sketch = scad.add_point_rsketch(sketch, pid, *xy)
        sketch = scad.add_line_rsketch(sketch, "h", "a", "b")
        sketch = scad.add_line_rsketch(sketch, "v", "c", "d")
        sketch = scad.add_line_rsketch(sketch, "spur", "s1", "s2")
        sketch = scad.add_line_rsketch(sketch, "roof", "w1", "w2")
        sketch = scad.trim_rsketch(sketch, "h", "m", against=["v"])
        sketch = scad.extend_rsketch(sketch, "spur", "end", to="roof")
        session.capture_result(value=scad.make_wire_from_sketch_rwire(sketch, profile=0))
    nodes = json.loads(export_graph_json(session.graph))["nodes"]
    trim = next(n for n in nodes if n["op"] == "trim_rsketch")
    extend = next(n for n in nodes if n["op"] == "extend_rsketch")
    assert trim["params"]["at"] == "m" and trim["params"]["against"] == ["v"]
    assert extend["params"] == {"sketch_id": extend["params"]["sketch_id"], "entity": "spur", "end": "end", "to": "roof"}
    assert replay_graph(import_graph_json(export_graph_json(session.graph)))


def test_a_sketch_with_scad_var_parameters_can_be_edited_and_keeps_its_parameters():
    radius = scad.var("r", 4.0)
    sketch = build({"o": (0, 0), "a": (-5, 2), "b": (5, 2)}, [("line", "l", "a", "b")])
    sketch = scad.add_circle_rsketch(sketch, "c", "o", radius)
    kept = scad.add_circle_rsketch(sketch, "keep", "o", radius)
    after = scad.trim_rsketch(kept, "c", (0.0, 4.0))
    assert [e["id"] for e in entities_of(after, "circle")] == ["keep"]
    assert entities_of(after, "circle")[0]["radius"] == pytest.approx(4.0)


def test_crossings_are_where_trim_would_cut_and_never_an_existing_point():
    crossing = scad.inspect_sketch_rsketchcrossings(plus())
    assert len(crossing) == 1 and sorted(crossing[0]["entities"]) == ["h", "v"]
    assert crossing[0]["at"] == pytest.approx([5.0, 0.0], abs=1e-6)
    # a line through a circle: two crossings; a line that ends on the circle at a shared point: none there
    ring = build({"c": (0, 0), "a": (-10, 0), "b": (10, 0)}, [("circle", "r", "c", 5.0), ("line", "l", "a", "b")])
    assert sorted(round(item["at"][0], 6) for item in scad.inspect_sketch_rsketchcrossings(ring)) == [-5.0, 5.0]
    ends = build({"c": (0, 0), "a": (-10, 0), "e": (5, 0), "q": (0, 9)}, [("arc", "k", "c", "e", "q"), ("line", "l", "a", "e")])
    assert scad.inspect_sketch_rsketchcrossings(ends) == []
    # construction geometry does not cross
    guide = build({"a": (0, 0), "b": (10, 0)}, [("line", "h", "a", "b")])
    guide = scad.add_point_rsketch(scad.add_point_rsketch(guide, "c", 5, -5), "d", 5, 5)
    guide = scad.add_line_rsketch(guide, "v", "c", "d", construction=True)
    assert scad.inspect_sketch_rsketchcrossings(guide) == []


# ---- B-splines ------------------------------------------------------------------------------------------------------------


def arch(points=None, entities=(), constraints=()):
    """A cubic Bezier arch a (0, 0) -> d (6, 0) over b (2, 2), c (4, 2): x = 6t, y = 6t(1 - t), top (3, 1.5)."""
    sketch = build({"a": (0, 0), "b": (2, 2), "c": (4, 2), "d": (6, 0), **(points or {})}, [])
    sketch = scad.add_bspline_rsketch(sketch, "sp", "a", "d", control_points=["a", "b", "c", "d"], degree=3)
    for kind, eid, *args in entities:
        sketch = getattr(scad, f"add_{kind}_rsketch")(sketch, eid, *args)
    for function, args, kwargs in constraints:
        sketch = function(sketch, *args, **kwargs)
    return sketch


def spline_of(sketch, eid):
    return next(e for e in entities_of(sketch, "bspline") if e["id"] == eid)


def poles_of(sketch, eid):
    return [c["point_id"] for c in spline_of(sketch, eid)["control_points"]]


def on_curve(sketch, eid, xy, tol=1e-6):
    """True when (x, y) lies on the solved B-spline *eid* (its kernel edge)."""
    solved = scad.inspect_sketch_rsketchresult(sketch, strict=False).to_dict()["solved_entities"][eid]
    edge = scad.make_spline_redge(
        control_points=[(x, y, 0.0) for x, y in solved["control_points"]],
        degree=solved["degree"],
        knots=solved["knots"],
        multiplicities=solved["multiplicities"],
        weights=solved["weights"],
    )
    vertex = scad.make_point_rvertex(xy[0], xy[1], 0.0)
    from simplecadapi._cpp.occt.BRepExtrema import BRepExtrema_DistShapeShape

    return BRepExtrema_DistShapeShape(edge.wrapped, vertex.wrapped).Value() < tol


def test_a_bspline_crossed_by_a_line_keeps_the_far_piece_as_a_new_bspline():
    sketch = arch({"v1": (4, -5), "v2": (4, 5)}, [("line", "v", "v1", "v2")])
    after = scad.trim_rsketch(sketch, "sp", (5.0, 1.0))
    diff = scad.diff_sketch_rsketchdiff(sketch, after)
    assert diff["removed"] == ["b", "c", "d", "sp"] and diff["created"] == ["p1", "p2", "p3", "s1"]
    assert poles_of(after, "s1") == ["a", "p2", "p3", "p1"]
    piece = spline_of(after, "s1")
    assert piece["start"] == "a" and piece["end"] == "p1" and piece["degree"] == 3
    assert points_of(after)["p1"] == pytest.approx((4.0, 4.0 / 3.0))
    tie = constraints_of(after, "point_on")
    assert [(t["entity_id"], t["kind"]) for t in tie[0]["targets"]] == [("p1", "point"), ("v", "line")]
    # the piece is the arch from t = 0 to t = 2/3: its middle is the arch's point at t = 1/3
    assert on_curve(after, "s1", (2.0, 6 * (1 / 3) * (2 / 3)))
    assert_solves(after)


def test_a_line_crossed_by_a_bspline_is_cut_there_and_tied_to_it():
    sketch = arch({"h1": (-1, 1), "h2": (7, 1)}, [("line", "h", "h1", "h2")])
    crossings = scad.inspect_sketch_rsketchcrossings(sketch)
    expected = sorted(6 * (1 + s * math.sqrt(1 / 3)) / 2 for s in (-1, 1))  # 6t(1 - t) = 1
    assert sorted(c["at"][0] for c in crossings) == pytest.approx(expected)
    assert all(c["entities"] == ["sp", "h"] for c in crossings)
    after = scad.trim_rsketch(sketch, "h", (3.0, 1.0))  # the middle goes
    assert x_spans(after) == [(-1.0, round(expected[0], 6)), (round(expected[1], 6), 7.0)]
    ties = constraints_of(after, "point_on")
    assert {t["targets"][1]["entity_id"] for t in ties} == {"sp"} and len(ties) == 2
    solved = scad.inspect_sketch_rsketchresult(after, strict=False)
    assert solved.status == "underconstrained"
    for tie in ties:
        assert on_curve(after, "sp", solved.solved_points[tie["targets"][0]["entity_id"]])


def test_a_bspline_cut_by_a_circle_and_by_another_bspline():
    sketch = arch({"o": (6, 0)}, [("circle", "ring", "o", 2.0)])
    by_circle = scad.trim_rsketch(sketch, "sp", (5.5, 0.5))
    end = points_of(by_circle)[spline_of(by_circle, "s1")["end"]]
    assert math.hypot(end[0] - 6.0, end[1]) == pytest.approx(2.0)
    assert [e["id"] for e in entities_of(by_circle, "circle")] == ["ring"]
    # a circle is cut by the arch too: the arch enters it once and ends inside, so trim needs two cuts
    with pytest.raises(ValueError, match="'ring' is crossed once"):
        scad.trim_rsketch(sketch, "ring", (8.0, 0.0))
    twin = arch({"e": (0, 3), "f": (3, -2), "g": (5, -2), "h": (8, 3)})
    twin = scad.add_bspline_rsketch(twin, "low", "e", "h", control_points=["e", "f", "g", "h"], degree=3)
    crossings = scad.inspect_sketch_rsketchcrossings(twin)
    assert len(crossings) == 2 and all(c["entities"] == ["sp", "low"] for c in crossings)
    after = scad.trim_rsketch(twin, "sp", (3.0, 1.5))
    assert [e["id"] for e in entities_of(after, "bspline")] == ["s1", "s2", "low"]
    assert spline_of(after, "s1")["start"] == "a" and spline_of(after, "s2")["end"] == "d"
    assert {t["targets"][1]["entity_id"] for t in constraints_of(after, "point_on")} == {"low"}
    assert_solves(after)


def test_a_tangent_touch_is_one_cut():
    sketch = arch({"h1": (-1, 1.5), "h2": (7, 1.5)}, [("line", "h", "h1", "h2")])
    assert [c["at"] for c in scad.inspect_sketch_rsketchcrossings(sketch)] == [pytest.approx([3.0, 1.5])]
    after = scad.trim_rsketch(sketch, "h", (5.0, 1.5))
    assert x_spans(after) == [(-1.0, 3.0)]


def closed_loop(periodic=False, line_to=15):
    sketch = build({"q0": (0, 0), "q1": (10, 0), "q2": (10, 10), "q3": (0, 10), "v1": (5, -5), "v2": (5, line_to)}, [("line", "v", "v1", "v2")])
    poles = ["q0", "q1", "q2", "q3"] + ([] if periodic else ["q0"])
    return scad.add_bspline_rsketch(sketch, "loop", "q0", "q0", control_points=poles, degree=3, periodic=periodic)


def test_a_closed_bspline_needs_two_cuts_and_keeps_the_rest_as_one_piece():
    sketch = closed_loop()
    with pytest.raises(ValueError, match="'loop' is crossed once: a closed B-spline needs two cuts"):
        scad.trim_rsketch(closed_loop(line_to=5), "loop", (9.0, 9.0))
    right = scad.trim_rsketch(sketch, "loop", (1.0, 1.0))  # the left half (the one over the seam q0) goes
    assert [e["id"] for e in entities_of(right, "bspline")] == ["s1"]
    assert "q0" not in points_of(right) and "q1" not in points_of(right)
    ends = sorted(points_of(right)[spline_of(right, "s1")[k]][1] for k in ("start", "end"))
    assert all(points_of(right)[spline_of(right, "s1")[k]][0] == pytest.approx(5.0) for k in ("start", "end"))
    left = scad.trim_rsketch(sketch, "loop", (9.0, 9.0))  # the right half goes; the seam is inside the piece kept
    assert "q0" in poles_of(left, "s1")[1:-1]
    assert sorted(points_of(left)[spline_of(left, "s1")[k]][1] for k in ("start", "end")) == pytest.approx(ends)
    assert len(constraints_of(left, "point_on")) == 2
    assert_solves(left)
    # a periodic one is cut the same way; its pieces are clamped
    periodic = scad.trim_rsketch(closed_loop(periodic=True), "loop", (8.0, 5.0))
    assert spline_of(periodic, "s1")["periodic"] is False
    assert_solves(periodic)


def test_constraints_on_the_bspline_ends_stay_with_the_piece_that_keeps_the_end():
    sketch = arch(
        {"z": (-4, -4), "v1": (4, -5), "v2": (4, 5)},
        [("line", "lead", "z", "a"), ("line", "v", "v1", "v2")],
        [
            (scad.constrain_tangent_rsketch, ("lead", "sp"), {"at_a": "end", "at_b": "start", "constraint_id": "tan"}),
            (scad.constrain_fix_rsketch, ("c",), {"constraint_id": "fixc"}),
            (scad.constrain_fix_rsketch, ("sp.start",), {"constraint_id": "fixa"}),
            (scad.constrain_length_rsketch, ("sp", 9.0), {"constraint_id": "long", "driving": False}),
        ],
    )
    after = scad.trim_rsketch(sketch, "sp", (5.0, 1.0))
    diff = scad.diff_sketch_rsketchdiff(sketch, after)
    assert diff["changed_constraints"] == ["tan", "fixa"]
    assert diff["removed_constraints"] == ["fixc", "long"]  # c is no control point any more; the length was the whole curve's
    tangent = constraints_of(after, "tangent")[0]
    assert [t["entity_id"] for t in tangent["targets"]] == ["lead", "s1"] and tangent["metadata"]["at_b"] == "start"
    assert constraints_of(after, "fix")[0]["targets"][0]["entity_id"] == "a"
    assert_solves(after)


def test_a_bspline_end_extends_to_the_line_ahead():
    sketch = arch({"w1": (9, -10), "w2": (9, 10)}, [("line", "w", "w1", "w2")])
    after = scad.extend_rsketch(sketch, "sp", "end")
    assert points_of(after)["d"][0] == pytest.approx(9.0)
    poles = poles_of(after, "sp")
    assert poles[:2] == ["a", "b"] and poles[-1] == "d"
    assert spline_of(after, "sp")["multiplicities"][1:-1] == [3]  # still a cubic Bezier chain
    assert on_curve(after, "sp", (3.0, 1.5))  # the old part of the curve is unchanged
    assert constraints_of(after, "point_on")[0]["targets"][1]["entity_id"] == "w"
    assert_solves(after)
    with pytest.raises(ValueError, match="nothing is ahead of the start of 'sp'"):
        scad.extend_rsketch(sketch, "sp", "start")
    with pytest.raises(ValueError, match="'loop' is a closed B-spline"):
        scad.extend_rsketch(closed_loop(), "loop", "end")


def test_a_line_extends_to_a_bspline():
    sketch = arch({"l1": (3, -3), "l2": (3, -1)}, [("line", "l", "l1", "l2")])
    after = scad.extend_rsketch(sketch, "l", "end", to="sp")
    assert points_of(after)["l2"] == pytest.approx((3.0, 1.5))
    assert constraints_of(after, "point_on")[0]["targets"][1]["kind"] == "bspline"
    assert_solves(after)


def test_bspline_trim_and_extend_are_replayed_from_model_json():
    with scad.GraphSession() as session:
        sketch = scad.make_sketch_rsketch(name="wave")
        for pid, xy in {"a": (0, 0), "b": (2, 2), "c": (4, 2), "d": (6, 0), "v1": (4, -5), "v2": (4, 5), "w1": (-2, 1), "w2": (-2, -6)}.items():
            sketch = scad.add_point_rsketch(sketch, pid, *xy)
        sketch = scad.add_bspline_rsketch(sketch, "sp", "a", "d", control_points=["a", "b", "c", "d"], degree=3)
        sketch = scad.add_line_rsketch(sketch, "v", "v1", "v2")
        sketch = scad.add_line_rsketch(sketch, "w", "w1", "w2")
        sketch = scad.trim_rsketch(sketch, "sp", (5.0, 1.0))  # the arch now ends on v at (4, 4/3)
        sketch = scad.trim_rsketch(sketch, "v", (4.0, 3.0))  # v now ends on the arch
        sketch = scad.extend_rsketch(sketch, "s1", "start", to="w")
        wire = scad.make_wire_from_sketch_rwire(sketch, profile=0)
        session.capture_result(value=wire)
    payload = json.loads(export_graph_json(session.graph))
    ops = [node["op"] for node in payload["nodes"]]
    assert ops.count("trim_rsketch") == 2 and ops.count("extend_rsketch") == 1
    rebuilt = replay_graph(import_graph_json(json.dumps(payload)))

    def length(shape):
        props = GProp_GProps()
        BRepGProp.LinearProperties_s(shape.wrapped, props)
        return props.Mass()

    assert len(scad.ql.edges().resolve(rebuilt[0])) == len(scad.ql.edges().resolve(wire)) == 2  # the extended arch and what is left of v
    assert length(rebuilt[0]) == pytest.approx(length(wire), rel=1e-9)


def test_the_editor_document_round_trips_a_bspline_trim_and_extend():
    from simplecadapi.editor import sketch_doc as S

    doc = {
        "plane": "XY",
        "points": [{"id": f"p{i}", "x": x, "y": y} for i, (x, y) in enumerate([(0, 0), (10, 10), (20, -10), (30, 0), (15, -10), (15, 10), (40, -20), (40, 20)])],
        "entities": [
            {"id": "s1", "kind": "bspline", "start": "p0", "end": "p3", "control_points": ["p0", "p1", "p2", "p3"], "degree": 3},
            {"id": "l1", "kind": "line", "start": "p4", "end": "p5"},
            {"id": "w", "kind": "line", "start": "p6", "end": "p7"},
        ],
        "constraints": [],
    }
    trimmed = S.apply_edit(doc, "trim", {"entity": "s1", "at": [25, -1], "against": ["l1"]})
    piece = next(e for e in trimmed["sketch"]["entities"] if e["kind"] == "bspline")
    assert piece["start"] == "p0" and "knots" not in piece  # one Bezier span: the uniform knots
    assert trimmed["removed"] == ["p1", "p2", "p3", "s1"]
    assert S.solve(S.validate(trimmed["sketch"]))["status"] == "underconstrained"
    extended = S.apply_edit(trimmed["sketch"], "extend", {"entity": piece["id"], "end": "end", "to": "w"})
    grown = next(e for e in extended["sketch"]["entities"] if e["kind"] == "bspline")
    assert grown["knots"][0] == 0.0 and grown["knots"][-1] == 1.0 and sum(grown["multiplicities"]) == len(grown["control_points"]) + 4
    clean = S.validate(extended["sketch"])
    assert S.from_sketch(S.to_sketch(clean), clean)["entities"] == clean["entities"]
    solved = S.solve(clean)
    assert solved["status"] == "underconstrained"
    end = next(p for p in clean["points"] if p["id"] == grown["end"])
    assert end["x"] == pytest.approx(40.0)
    with pytest.raises(S.SketchError, match="must add up"):
        S.validate({**clean, "entities": [{**grown, "multiplicities": [*grown["multiplicities"][:-1], 3]}, *clean["entities"][1:]]})

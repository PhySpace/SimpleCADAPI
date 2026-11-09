"""B-splines in anchor form (anchors on the curve, a handle on each side) and the sketch output a wire.

insert_spline_anchor_rsketch / remove_spline_anchor_rsketch / convert_spline_to_anchors_rsketch edit the structure of a cubic
B-spline of Bezier spans; the editor's sketch document carries them (``apply_edit``) and its pen tool draws in that form.  A
sketch document with ``"output": "wire"`` becomes ``make_wire_from_sketch_rwire`` (a closed loop or an open chain), so sweeps
and lofts can take sketches.
"""

from __future__ import annotations

import json

import pytest

import simplecadapi as scad
from simplecadapi.editor import features as F
from simplecadapi.editor import sketch_doc as D
from simplecadapi.recording.serializer import export_graph_json, import_graph_json, replay_graph


def one_span(name="pen"):
    sketch = scad.make_sketch_rsketch(name)
    for pid, xy in {"a0": (0, 0), "h0": (10, 10), "h1": (20, 10), "a1": (30, 0)}.items():
        sketch = scad.add_point_rsketch(sketch, pid, *xy)
    return scad.add_bspline_rsketch(sketch, "s1", "a0", "a1", ["a0", "h0", "h1", "a1"], 3)


def spline(sketch, entity_id="s1"):
    return next(e for e in sketch.to_dict()["entities"] if e["id"] == entity_id)


def poles(sketch, entity_id="s1"):
    return [c["point_id"] for c in spline(sketch, entity_id)["control_points"]]


def samples(sketch, entity_id="s1", count=60):
    solved = scad.inspect_sketch_rsketchresult(sketch).to_dict()["solved_entities"][entity_id]
    edge = scad.make_spline_redge(
        control_points=[(x, y, 0.0) for x, y in solved["control_points"]],
        degree=solved["degree"],
        knots=solved.get("knots"),
        multiplicities=solved.get("multiplicities"),
    )
    return scad.sample_curve_rcurvature(edge=edge, count=count)["points"]


def gap(a, b):
    return max(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(a, b))


def xy(sketch, point_id):
    item = next(e for e in sketch.to_dict()["entities"] if e["id"] == point_id)
    return (item["x"], item["y"])


# ---- the SDK operations -------------------------------------------------------------------------------------------------------


def test_inserting_an_anchor_keeps_the_curve_and_the_ids_of_the_spans_handles():
    before = one_span()
    after = scad.insert_spline_anchor_rsketch(before, "s1", (12.0, 8.0))
    assert poles(after) == ["a0", "h0", "p1", "p2", "p3", "h1", "a1"]
    assert spline(after)["multiplicities"] == [4, 3, 4]
    assert gap(samples(before), samples(after)) < 1e-9
    assert "anchor 'p2'" in after.get_metadata("last_edit")["notes"][0]
    diff = scad.diff_sketch_rsketchdiff(before=before, after=after)
    assert diff["created"] == ["p1", "p2", "p3"] and set(diff["changed"]) == {"h0", "h1", "s1"}


def test_removing_an_anchor_keeps_the_ends_and_the_outer_handles():
    before = one_span()
    split = scad.insert_spline_anchor_rsketch(before, "s1", (22.0, 6.0))
    split = scad.insert_spline_anchor_rsketch(split, "s1", (5.0, 4.0))
    middle = poles(split)[6]  # the anchor inserted first is now the third
    merged = scad.remove_spline_anchor_rsketch(split, "s1", middle)
    ids = poles(merged)
    assert ids[0] == "a0" and ids[-1] == "a1" and len(ids) == 7
    # the outer handles keep their ids and their directions
    assert ids[5] == "h1"
    a1, h1_before, h1_after = xy(split, "a1"), xy(split, "h1"), xy(merged, "h1")
    cross = (h1_before[0] - a1[0]) * (h1_after[1] - a1[1]) - (h1_before[1] - a1[1]) * (h1_after[0] - a1[0])
    assert abs(cross) < 1e-9
    # removing both inserted anchors gives back the curve they split
    back = scad.remove_spline_anchor_rsketch(merged, "s1", ids[3])
    assert poles(back) == ["a0", "h0", "h1", "a1"]
    assert gap(samples(before), samples(back)) < 1e-7


def test_converting_a_control_point_bspline_keeps_its_shape_and_its_end_points():
    sketch = scad.make_sketch_rsketch("old")
    for i, (x, y) in enumerate([(0, 0), (5, 10), (10, -5), (15, 8), (20, 0), (25, 6)]):
        sketch = scad.add_point_rsketch(sketch, f"q{i}", x, y)
    sketch = scad.add_bspline_rsketch(sketch, "s1", "q0", "q5", [f"q{i}" for i in range(6)], 3)
    after = scad.convert_spline_to_anchors_rsketch(sketch, "s1")
    data = spline(after)
    assert data["degree"] == 3 and data["multiplicities"] == [4, 3, 3, 4]
    assert poles(after)[0] == "q0" and poles(after)[-1] == "q5"
    assert gap(samples(sketch), samples(after)) < 1e-9
    again = scad.convert_spline_to_anchors_rsketch(after, "s1")
    assert poles(again) == poles(after) and "already in anchor form" in again.get_metadata("last_edit")["notes"][0]
    # a degree-5 spline has no exact anchor form: it is approximated, and the notes say so
    five = scad.add_bspline_rsketch(sketch, "s5", "q0", "q5", [f"q{i}" for i in range(6)], 5)
    approx = scad.convert_spline_to_anchors_rsketch(five, "s5")
    assert spline(approx, "s5")["degree"] == 3 and "approximated" in approx.get_metadata("last_edit")["notes"][0]


def test_refusals_name_the_ids():
    split = scad.insert_spline_anchor_rsketch(one_span(), "s1", (15.0, 8.0))
    cases = [
        (lambda: scad.remove_spline_anchor_rsketch(split, "s1", "a0"), "is an end of 's1'"),
        (lambda: scad.remove_spline_anchor_rsketch(split, "s1", "p1"), "is a handle of 's1'"),
        (lambda: scad.insert_spline_anchor_rsketch(split, "s1", "p2"), "already has an anchor there"),
        (lambda: scad.insert_spline_anchor_rsketch(split, "zz", (1, 1)), "no entity 'zz'"),
        (lambda: scad.insert_spline_anchor_rsketch(scad.add_point_rsketch(split, "k", 0, 0), "k", (1, 1)), "not a B-spline"),
    ]
    for call, expected in cases:
        with pytest.raises(ValueError) as caught:
            call()
        assert expected in str(caught.value), (expected, str(caught.value))


def test_trim_keeps_the_anchor_form():
    sketch = scad.insert_spline_anchor_rsketch(one_span(), "s1", (15.0, 8.0))
    for pid, point in {"t0": (25, -5), "t1": (25, 20)}.items():
        sketch = scad.add_point_rsketch(sketch, pid, *point)
    sketch = scad.add_line_rsketch(sketch, "cut", "t0", "t1")
    after = scad.trim_rsketch(sketch, "s1", (29.0, 1.0))
    piece = next(e for e in after.to_dict()["entities"] if e["kind"] == "bspline")
    assert piece["degree"] == 3 and piece["multiplicities"] == [4, 3, 4]


def test_anchor_edits_are_recorded_and_replayed():
    with scad.GraphSession() as session:
        sketch = scad.insert_spline_anchor_rsketch(one_span(), "s1", (12.0, 8.0))
        sketch = scad.insert_spline_anchor_rsketch(sketch, "s1", (25.0, 4.0))
        sketch = scad.remove_spline_anchor_rsketch(sketch, "s1", "p2")
        session.capture_result(value=scad.make_wire_from_sketch_rwire(sketch))
    payload = json.loads(export_graph_json(session.graph))
    insert = next(n for n in payload["nodes"] if n["op"] == "insert_spline_anchor_rsketch")
    assert insert["params"]["spline"] == "s1" and insert["params"]["at"] == [12.0, 8.0]
    assert any(n["op"] == "remove_spline_anchor_rsketch" and n["params"]["anchor"] == "p2" for n in payload["nodes"])
    rebuilt = replay_graph(import_graph_json(json.dumps(payload)))
    length = lambda wire: sum(edge.get_length() for edge in scad.ql.edges().resolve(wire))  # noqa: E731
    assert length(rebuilt[0]) == pytest.approx(length(scad.make_wire_from_sketch_rwire(sketch)), rel=1e-9)


# ---- the editor's document ------------------------------------------------------------------------------------------------------


def pen_doc():
    """A pen path of two spans as the editor draws it: knots 0..2, inner multiplicity 3."""
    return {
        "plane": "XY",
        "points": [{"id": i, "x": x, "y": y} for i, x, y in [("a", 0, 0), ("b", 4, 6), ("c", 8, 10), ("d", 12, 10), ("e", 16, 10), ("f", 20, 6), ("g", 24, 0)]],
        "entities": [{"id": "s1", "kind": "bspline", "start": "a", "end": "g", "control_points": list("abcdefg"), "degree": 3, "knots": [0, 1, 2], "multiplicities": [4, 3, 4]}],
        "constraints": [],
        "profile": 0,
        "inner": [],
        "fully_constrained": False,
    }


def test_the_document_carries_anchor_edits_through_the_sdk():
    doc = D.validate(pen_doc())
    assert doc["entities"][0]["multiplicities"] == [4, 3, 4]
    inserted = D.apply_edit(doc, "insert_spline_anchor", {"spline": "s1", "at": [3, 4]})
    entity = inserted["sketch"]["entities"][0]
    assert entity["multiplicities"] == [4, 3, 3, 4] and len(entity["control_points"]) == 10
    assert inserted["created"] == ["p1", "p2", "p3"]
    removed = D.apply_edit(inserted["sketch"], "remove_spline_anchor", {"spline": "s1", "anchor": "d"})
    assert removed["sketch"]["entities"][0]["control_points"][3] == "p2" and "d" in removed["removed"]
    with pytest.raises(D.SketchError, match="is an end of 's1'"):
        D.apply_edit(doc, "remove_spline_anchor", {"spline": "s1", "anchor": "a"})
    # the code the cell gets builds the same spline
    params, lines = D.render("pen", removed["sketch"])
    assert any("multiplicities=[4, 3, 4]" in line for line in lines)


# ---- a sketch that makes a wire ------------------------------------------------------------------------------------------------

PATH = {
    "plane": "XZ",
    "points": [{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 0, "y": 20}, {"id": "c", "x": 10, "y": 30}],
    "entities": [{"id": "l0", "kind": "line", "start": "a", "end": "b"}, {"id": "l1", "kind": "line", "start": "b", "end": "c"}],
    "constraints": [],
    "profile": 0,
    "inner": [],
    "fully_constrained": False,
    "output": "wire",
}
DISC = {
    "plane": "XY",
    "points": [{"id": "o", "x": 0, "y": 0}],
    "entities": [{"id": "k", "kind": "circle", "center": "o", "radius": 2.0}],
    "constraints": [],
    "profile": 0,
    "inner": [],
    "fully_constrained": False,
}


def square(z, half, output="wire"):
    corners = [(-half, -half), (half, -half), (half, half), (-half, half)]
    return {
        "plane": {"origin": [0, 0, z], "x_axis": [1, 0, 0], "y_axis": [0, 1, 0]},
        "points": [{"id": f"p{i}", "x": x, "y": y} for i, (x, y) in enumerate(corners)],
        "entities": [{"id": f"l{i}", "kind": "line", "start": f"p{i}", "end": f"p{(i + 1) % 4}"} for i in range(4)],
        "constraints": [],
        "profile": 0,
        "inner": [],
        "fully_constrained": False,
        "output": output,
    }


def test_the_output_is_a_face_unless_the_document_says_wire():
    assert "output" not in D.validate(DISC) and D.output_of(D.validate(DISC)) == "face"
    assert D.validate(PATH)["output"] == "wire"
    with pytest.raises(D.SketchError, match="face or a wire"):
        D.validate({**DISC, "output": "solid"})
    _, lines = D.render("path", D.validate(PATH))
    assert lines[-1] == "path = scad.make_wire_from_sketch_rwire(sketch=_sketch, profile=0, require_fully_constrained=False)"
    # the SDK lists the open chain as a profile, and an edit keeps the output
    assert D.solve(PATH)["profiles"][0]["closed"] is False
    assert D.from_sketch(D.to_sketch(PATH), D.validate(PATH))["output"] == "wire"


def _builder():
    scope: dict = {"scad": scad}
    bodies: dict[str, str] = {}

    def add(spec_id, slug, values):
        rendered = F.render_feature(spec_id, slug, values, bodies=bodies)
        if rendered.params:
            exec("\n".join(rendered.params), scope)  # noqa: S102 - the code under test is ours
        exec(rendered.feature, scope)  # noqa: S102
        # what the notebook says the feature makes: a sketch makes what its document says (gui_features.snapshot)
        bodies[slug] = D.output_of(values["sketch"]) if spec_id == "sketch" else rendered.produces
        return rendered

    return scope, add


def test_an_open_chain_sketch_is_the_path_a_sketch_face_is_swept_along():
    with scad.GraphSession(graph_id="sketch-wire-sweep"):
        scope, add = _builder()
        add("sketch", "path", {"sketch": PATH})
        assert isinstance(scope["path"], scad.Wire) and not scope["path"].is_closed()
        add("sketch", "disc", {"sketch": DISC})
        add("op.sweep_rsolid", "swept", {"profile": "disc", "path": "path"})
        assert scope["swept"].get_volume() > 300


def test_closed_sketches_made_wires_are_lofted():
    with scad.GraphSession(graph_id="sketch-wire-loft"):
        scope, add = _builder()
        add("sketch", "low", {"sketch": square(0, 10)})
        add("sketch", "high", {"sketch": square(20, 5)})
        assert scope["low"].is_closed() and isinstance(scope["high"], scad.Wire)
        add("op.loft_rsolid", "frustum", {"profiles": ["low", "high"]})
        # a square frustum: h / 3 * (A1 + A2 + sqrt(A1 * A2))
        assert scope["frustum"].get_volume() == pytest.approx(20 / 3 * (400 + 100 + 200), rel=1e-6)


def test_the_notebook_says_a_wire_sketch_makes_a_wire_and_offers_only_face_sketches_as_profiles(tmp_path):
    import asyncio
    import threading
    import time

    import uvicorn

    from simplecadapi.editor.server import WorkspaceState, create_app
    from simplecadapi.editor.templates import create_notebook

    path = create_notebook(tmp_path, "wires", "blank")
    state = WorkspaceState(tmp_path)
    state.port = 17763
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(asyncio.new_event_loop())

    def wait_idle(timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not {c.get("status") for c in state.cells} <= {"idle", "stale", "exception", "error", None}:
            time.sleep(0.3)

    try:
        state.start_kernel(path)
        service = state.features
        service.add({"spec": "sketch", "name": "path", "values": {"sketch": PATH}})
        service.add({"spec": "sketch", "name": "disc", "values": {"sketch": DISC}})
        wait_idle()
        snap = service.snapshot()
        assert {b["name"]: b["produces"] for b in snap["bodies"]} == {"path": "wire", "disc": "face"}
        assert [p["name"] for p in snap["profiles"]] == ["disc"]
        service.add({"spec": "op.sweep_rsolid", "name": "swept", "values": {"profile": "disc", "path": "path"}})
        wait_idle()
        snap = service.snapshot()
        assert all(not f["errors"] for f in snap["features"]), snap["features"]
        assert snap["tip"] == "swept"
        assert "path = scad.make_wire_from_sketch_rwire(" in path.read_text()
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True

"""Workplanes as values: the recorded constructors, ``with wp:`` and ``plane=wp``, replay, pickling and the cell cache."""

from __future__ import annotations

import copy
import json
import pickle
import textwrap
import typing
from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi import catalog
from simplecadapi.runtime import run_notebook

ql = scad.ql


def _close(actual, expected, tol: float = 1e-9) -> bool:
    return all(abs(float(a) - float(b)) <= tol for a, b in zip(actual, expected))


def _face(shape, tag: str):
    return ql.faces().where(ql.tag(tag)).exactly(1).resolve(shape)[0]


def _centre(shape) -> tuple[float, float, float]:
    """The centre of the bounding box (``get_center`` of a round shape is not its axis)."""
    x0, y0, z0, x1, y1, z1 = shape._bounds()
    return ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)


# ---------------------------------------------------------------------------
# The constructors
# ---------------------------------------------------------------------------


def test_a_workplane_on_a_face_sits_at_its_centre_along_its_outward_normal():
    box = scad.make_box_rsolid(10, 20, 5, tag_prefix="base")
    top = _face(box, "base.face.top")
    wp = scad.make_workplane_from_face_rworkplane(top)
    assert isinstance(wp, scad.Workplane)
    assert _close(wp.origin, (0, 0, 5)) and _close(wp.normal, (0, 0, 1))
    assert _close(scad.make_workplane_from_face_rworkplane(top, offset=3).origin, (0, 0, 8))
    assert _close(scad.make_workplane_from_face_rworkplane(top, origin=(2, 3, 40)).origin, (2, 3, 5))
    bottom = _face(box, "base.face.bottom")
    assert _close(scad.make_workplane_from_face_rworkplane(bottom).normal, (0, 0, -1))
    assert _close(scad.make_workplane_from_face_rworkplane(bottom, flip=True).normal, (0, 0, 1))
    edge = scad.make_line_redge((0, 0, 5), (0, 1, 5))
    along = scad.make_workplane_from_face_rworkplane(top, x_edge=edge)
    assert _close(along.x_dir, (0, 1, 0)) and _close(along.y_dir, (-1, 0, 0))
    assert _close(scad.make_workplane_from_face_rworkplane(top, x_dir=(0, -1, 0)).x_dir, (0, -1, 0))
    with pytest.raises(scad.SimpleCADError):
        scad.make_workplane_from_face_rworkplane(top, x_edge=edge, x_dir=(1, 0, 0))
    side = ql.faces().where(ql.prop("geom.type", "==", "CYLINDER")).exactly(1).resolve(scad.make_cylinder_rsolid(2, 4))[0]
    with pytest.raises(scad.SimpleCADError, match="planar"):
        scad.make_workplane_from_face_rworkplane(side)


def test_three_points_an_axis_a_midplane_and_a_curve():
    wp = scad.make_workplane_from_points_rworkplane((1, 1, 1), (2, 1, 1), (1, 1, 3))
    assert _close(wp.origin, (1, 1, 1)) and _close(wp.normal, (0, -1, 0))
    corner = scad.make_point_rvertex(0, 0, 7)
    assert _close(scad.make_workplane_from_points_rworkplane(corner, (1, 0, 7), (0, 1, 7)).origin, (0, 0, 7))
    with pytest.raises(scad.SimpleCADError, match="one line"):
        scad.make_workplane_from_points_rworkplane((0, 0, 0), (1, 0, 0), (3, 0, 0))

    axis = scad.make_line_redge((0, 0, 0), (10, 0, 0))
    assert _close(scad.make_workplane_from_axis_rworkplane(axis).normal, (0, 0, 1))
    tilted = scad.make_workplane_from_axis_rworkplane(axis, 90)
    assert _close(tilted.normal, (0, -1, 0)) and _close(tilted.x_dir, (1, 0, 0))
    box = scad.make_box_rsolid(10, 20, 5, tag_prefix="base")
    long_edge = ql.edges().where(
        ql.and_(ql.prop("geom.length", ">", 19), ql.prop("geom.center.z", ">", 4), ql.prop("geom.center.x", ">", 4))
    ).exactly(1).resolve(box)[0]
    hinged = scad.make_workplane_from_axis_rworkplane(long_edge, 0, face=_face(box, "base.face.top"))
    assert _close(hinged.normal, (0, 0, 1))  # at angle 0: the plane of the face
    ring = scad.make_circle_redge((0, 0, 3), 2)
    assert _close(scad.make_workplane_from_axis_rworkplane(ring).origin, (0, 0, 3))

    mid = scad.make_workplane_midplane_rworkplane(_face(box, "base.face.left"), _face(box, "base.face.right"))
    assert _close(mid.origin, (0, 0, 2.5))
    assert _close(mid.normal, scad.make_workplane_from_face_rworkplane(_face(box, "base.face.left")).normal)
    with pytest.raises(scad.SimpleCADError, match="parallel"):
        scad.make_workplane_midplane_rworkplane(_face(box, "base.face.left"), _face(box, "base.face.top"))

    path = scad.make_polyline_rwire([(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    start = scad.make_workplane_normal_to_curve_rworkplane(path, 0)
    assert _close(start.origin, (0, 0, 0)) and _close(start.normal, (1, 0, 0))
    end = scad.make_workplane_normal_to_curve_rworkplane(path, 1)
    assert _close(end.origin, (10, 10, 0)) and _close(end.normal, (0, 1, 0))
    assert _close(scad.make_workplane_normal_to_curve_rworkplane(path, 0.25).origin, (5, 0, 0))
    with pytest.raises(scad.SimpleCADError):
        scad.make_workplane_normal_to_curve_rworkplane(path, 2)


def test_the_plain_constructor_reads_the_current_system():
    outer = scad.make_workplane_rworkplane((0, 0, 10))
    with outer:
        inner = scad.make_workplane_rworkplane((1, 0, 0), (0, 1, 0))
    assert _close(inner.origin, (1, 0, 10)) and _close(inner.normal, (0, 1, 0))
    assert _close(scad.SimpleWorkplane((0, 0, 4)).origin, (0, 0, 4))


# ---------------------------------------------------------------------------
# A value
# ---------------------------------------------------------------------------


def test_a_workplane_is_a_value_entered_again_copied_and_pickled():
    wp = scad.make_workplane_rworkplane((0, 0, 5), (1, 0, 0), (0, 1, 0))
    for _ in range(2):  # `with wp:` in one cell, then again in a later one
        with wp:
            assert _close(scad.get_current_cs().origin, (0, 0, 5))
        assert _close(scad.get_current_cs().origin, (0, 0, 0))
    for twin in (pickle.loads(pickle.dumps(wp)), copy.copy(wp), copy.deepcopy(wp)):
        assert _close(twin.origin, wp.origin) and _close(twin.normal, wp.normal) and _close(twin.x_dir, wp.x_dir)
        with twin:
            assert _close(scad.get_current_cs().z_axis, (1, 0, 0))
    with scad.GraphSession(graph_id="pickled") as session:
        recorded = scad.make_workplane_rworkplane((0, 0, 5))
    restored = pickle.loads(pickle.dumps(recorded))
    assert restored._get_runtime("graph.node_id") == recorded._get_runtime("graph.node_id")
    assert session.graph.get_node(restored._get_runtime("graph.node_id")).op == "make_workplane_rworkplane"
    assert set(wp.plane) == {"origin", "x_axis", "y_axis"}


def test_a_sketch_on_a_workplane_uses_its_frame_wherever_it_is_made():
    wp = scad.make_workplane_rworkplane((0, 0, 4), (1, 0, 0), (0, 1, 0))
    with scad.SimpleWorkplane((100, 0, 0)):
        sketch = scad.make_sketch_rsketch("rib", plane=wp)  # not moved by the entered workplane
    sketch = scad.add_point_rsketch(sketch, "c", 0, 0)
    sketch = scad.add_circle_rsketch(sketch, "circle", "c", 1)
    face = scad.make_face_from_sketch_rface(sketch)
    assert _close(_centre(face), (0, 0, 4), 1e-6)
    assert scad.SimpleWorkplane in typing.get_args(typing.get_args(scad.types.Plane)[0])


def test_the_constructors_are_typed_operations_in_the_catalog():
    names = {
        "make_workplane_rworkplane",
        "make_workplane_from_face_rworkplane",
        "make_workplane_from_points_rworkplane",
        "make_workplane_from_axis_rworkplane",
        "make_workplane_midplane_rworkplane",
        "make_workplane_normal_to_curve_rworkplane",
    }
    for name in names:
        op = catalog.operation(name)
        assert op.returns == "workplane", (name, op.returns)
        assert all(p.kind != "unknown" for p in op.params), (name, op.params)
    face = {p.name: p.kind for p in catalog.operation("make_workplane_from_face_rworkplane").params}
    assert face == {"face": "face", "origin": "point3", "x_edge": "edge", "x_dir": "direction3", "offset": "length", "flip": "bool"}
    assert catalog.operation("make_workplane_from_axis_rworkplane").params[1].kind == "angle"
    plane = next(p for p in catalog.operation("make_sketch_rsketch").params if p.name == "plane")
    assert plane.kind == "plane"


# ---------------------------------------------------------------------------
# Recording and replay
# ---------------------------------------------------------------------------


def _recorded_model():
    with scad.GraphSession(graph_id="wp_replay") as session:
        top = scad.make_rectangle_rface(10, 20, center=(0, 0, 5))
        wp = scad.make_workplane_from_face_rworkplane(top, offset=1)
        sketch = scad.make_sketch_rsketch("disc", plane=wp)
        sketch = scad.add_point_rsketch(sketch, "c", 0, 0)
        sketch = scad.add_circle_rsketch(sketch, "circle", "c", 2)
        disc = scad.make_face_from_sketch_rface(sketch)
        with wp:
            pin = scad.make_box_rsolid(1, 1, 1)
    return session, wp, disc, pin


def test_the_graph_records_the_workplane_op_its_inputs_and_who_uses_it():
    session, wp, _disc, pin = _recorded_model()
    node = session.graph.get_node(wp._get_runtime("graph.node_id"))
    assert node.op == "make_workplane_from_face_rworkplane"
    assert len(node.params["input_refs"]) == 1 and node.params["offset"] == 1
    sketch_node = next(n for n in session.graph.nodes if n.op == "make_sketch_rsketch")
    assert sketch_node.params["plane"]["workplane"] is True
    assert [n.node_id for n in sketch_node.inputs] == [node.node_id]
    pin_node = session.graph.get_node(pin._get_runtime("graph.node_id"))
    assert pin_node.context["workplane"]["node_id"] == node.node_id


def test_replay_rebuilds_the_frame_from_the_recorded_op_so_it_follows_the_face():
    session, _wp, disc, pin = _recorded_model()
    payload = scad.export_model_json(session)
    replayed = scad.replay_model_json(payload)
    centres = sorted((type(item).__name__, _centre(item)) for item in replayed if hasattr(item, "_bounds"))
    assert _close(dict(centres)["Face"], _centre(disc), 1e-6) and _close(dict(centres)["Solid"], _centre(pin), 1e-6)

    data = json.loads(payload)
    for node in data["graph"]["nodes"]:  # move the face: the sides of the rectangle from z = 5 to z = 12
        if node["op"] == "make_line_redge":
            node["params"]["start"][2] = 12
            node["params"]["end"][2] = 12
    moved = {type(item).__name__: _centre(item) for item in scad.replay_model_json(json.dumps(data)) if hasattr(item, "_bounds")}
    assert _close(moved["Face"], (0, 0, 13), 1e-6)  # the sketch on the workplane: face + offset 1
    assert _close(moved["Solid"], (0, 0, 13.5), 1e-6)  # the box made inside `with wp:`


def test_a_workplane_from_a_vertex_replays_from_its_input():
    with scad.GraphSession(graph_id="wp_points") as session:
        corner = scad.make_point_rvertex(0, 0, 7)
        wp = scad.make_workplane_from_points_rworkplane(corner, (1, 0, 7), (0, 1, 7))
    node = session.graph.get_node(wp._get_runtime("graph.node_id"))
    assert node.params["a"] == {"input": 0} and list(node.params["b"]) == [1, 0, 7]
    data = json.loads(scad.export_model_json(session))
    for item in data["graph"]["nodes"]:
        if item["op"] == "make_point_rvertex":
            item["params"]["z"] = 9
    (replayed,) = [v for v in scad.replay_model_json(json.dumps(data)) if isinstance(v, scad.Workplane)]
    assert _close(replayed.origin, (0, 0, 9))
    assert abs(replayed.normal[2]) < 1  # the plane through (0,0,9), (1,0,7), (0,1,7) tilts


# ---------------------------------------------------------------------------
# The notebook: cell cache and a parameter change
# ---------------------------------------------------------------------------


def _notebook(tmp_path: Path) -> Path:
    def cell(body: str, reads: str, returns: str) -> str:
        code = textwrap.indent(textwrap.dedent(body).strip(), "    ")
        return f"@app.cell\ndef _({reads}):\n{code}\n    return ({returns},)\n"

    cells = [
        cell("height = 5.0", "", "height"),
        cell('base = scad.make_box_rsolid(10.0, 20.0, height, tag_prefix="base")', "height", "base"),
        cell(
            """
            _top = scad.ql.faces().where(scad.ql.tag("base.face.top")).exactly(1).resolve(base)[0]
            wp_top = scad.make_workplane_from_face_rworkplane(_top)
            """,
            "base",
            "wp_top",
        ),
        cell(
            """
            _sketch = scad.make_sketch_rsketch("boss", plane=wp_top)
            _sketch = scad.add_point_rsketch(_sketch, "c", 0, 0)
            _sketch = scad.add_circle_rsketch(_sketch, "circle", "c", 2)
            boss = scad.extrude_rsolid(scad.make_face_from_sketch_rface(_sketch), (0, 0, 1), 3)
            with wp_top:
                peg = scad.make_cylinder_rsolid(0.5, 2)
            part = scad.Part(part_id="plate", body=scad.union_rsolid(base, boss))
            """,
            "wp_top",
            "boss, peg, part",
        ),
    ]
    text = (
        '# /// script\n# [tool.simplecadapi]\n# id = "plate"\n# ///\nimport marimo\n\napp = marimo.App()\n\n'
        "with app.setup:\n    import simplecadapi as scad\n\n\n" + "\n\n".join(cells) + '\n\nif __name__ == "__main__":\n    app.run()\n'
    )
    path = tmp_path / "plate.py"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_workplane_cell_is_cached_and_a_sketch_on_it_follows_a_parameter_change(tmp_path):
    path = _notebook(tmp_path)
    first = run_notebook(path)
    second = run_notebook(path)
    assert [c.status for c in second.cells] == ["ran", "cached", "cached", "cached", "cached"]
    for run in (first, second):
        assert isinstance(run.values["wp_top"], scad.Workplane)
        assert _close(run.values["wp_top"].origin, (0, 0, 5))
        assert _close(_centre(run.values["boss"]), (0, 0, 6.5), 1e-6)
    with second.values["wp_top"]:  # the restored value is a context manager again
        assert _close(scad.get_current_cs().origin, (0, 0, 5))

    taller = run_notebook(path, overrides={"height": 9.0})
    assert _close(taller.values["wp_top"].origin, (0, 0, 9))
    assert _close(_centre(taller.values["boss"]), (0, 0, 10.5), 1e-6)
    assert _close(_centre(taller.values["peg"]), (0, 0, 10), 1e-6)


def test_a_workplane_on_a_body_leaves_it_the_open_body_of_a_part_notebook(tmp_path):
    """A datum reads the body without building on it: the implicit Part of a ``kind = "part"`` notebook is still the body."""
    text = (
        '# /// script\n# [tool.simplecadapi]\n# kind = "part"\n# id = "plate"\n# ///\nimport marimo\n\napp = marimo.App()\n\n'
        "with app.setup:\n    import simplecadapi as scad\n\n\n"
        '@app.cell\ndef _():\n    base = scad.make_box_rsolid(10.0, 20.0, 5.0, tag_prefix="base")\n    return (base,)\n\n\n'
        "@app.cell\ndef _(base):\n"
        '    _top = scad.ql.faces().where(scad.ql.tag("base.face.top")).exactly(1).resolve(base)[0]\n'
        "    wp = scad.make_workplane_from_face_rworkplane(_top)\n    return (wp,)\n\n\n"
        'if __name__ == "__main__":\n    app.run()\n'
    )
    path = tmp_path / "plate.py"
    path.write_text(text, encoding="utf-8")
    run = run_notebook(path)
    assert isinstance(run.values["wp"], scad.Workplane)
    assert abs(run.product.bodies[0].solid.get_volume() - 1000.0) < 1e-6

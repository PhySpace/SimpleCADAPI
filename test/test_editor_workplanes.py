"""The editor's workplanes: the feature cell a selection writes, a sketch on a workplane variable, the frames the kernel reports."""

from __future__ import annotations

import pytest

import simplecadapi as scad
from simplecadapi.editor import features as F
from simplecadapi.editor import sketch_doc as S
from simplecadapi.editor.kernel import MarimoKernel
from simplecadapi.runtime.live import workplane_frames
from test_editor_features import RECT_SKETCH, _entity, _run

ql = scad.ql
BODIES = {"base": "solid"}


def _base():
    return scad.make_box_rsolid(10.0, 20.0, 5.0, tag_prefix="base")


def _face(base, tag):
    return ql.faces().where(ql.tag(tag)).exactly(1).resolve(base)[0]


def _picked_face(base, tag):
    face = _face(base, tag)
    return _entity("face", face, area=face.get_area(), tags=[tag])


def _picked_edge(edge):
    return _entity("edge", edge, length=edge.get_length())


def _picked_vertex(vertex):
    x, y, z = vertex.get_coordinates()
    return {"kind": "vertex", "properties": {"position": [x, y, z]}, "geometry": {"type": "point"}, "tags": []}


def _close(actual, expected, tol=1e-6):
    return all(abs(float(a) - float(b)) <= tol for a, b in zip(actual, expected))


def _make(method, selections, **values):
    rendered = F.render_feature(
        "workplane", "wp", {"body": "base", "method": method, **values}, bodies=BODIES, selections=selections, known_slugs={"base"}
    )
    scope = {"scad": scad}
    with scad.GraphSession(graph_id=f"wp_{method}"):
        scope["base"] = _base()
        _run(rendered, scope)
    return rendered, scope["wp"]


def test_a_picked_face_writes_a_workplane_cell_with_an_offset_and_a_flip_in_the_params():
    base = _base()
    rendered, wp = _make("face", {"face": [_picked_face(base, "base.face.top")]}, offset=2.0)
    assert "scad.make_workplane_from_face_rworkplane(_face, offset=WP_OFFSET, flip=WP_FLIP)" in rendered.feature
    assert rendered.feature.startswith("# ---- feature: wp (datum) ----") and rendered.produces == "workplane"
    assert any(line.startswith("WP_OFFSET = scad.var(") for line in rendered.params)
    assert isinstance(wp, scad.Workplane) and _close(wp.origin, (0, 0, 7)) and _close(wp.normal, (0, 0, 1))
    assert F.parse_gui(rendered.feature)["spec"] == "workplane"
    assert F.default_slug("workplane", {"wp"}) == "wp_2"


def test_a_face_and_an_edge_two_faces_three_vertices_and_an_edge_alone():
    base = _base()
    top = _face(base, "base.face.top")
    edge = ql.edges().where(ql.and_(ql.prop("geom.length", ">", 19), ql.prop("geom.center.z", ">", 4), ql.prop("geom.center.x", ">", 4))).exactly(1).resolve(base)[0]
    rendered, wp = _make("face_edge", {"face": [_picked_face(base, "base.face.top")], "edge": [_picked_edge(edge)]})
    assert "x_edge=_edge" in rendered.feature and abs(abs(wp.x_dir[1]) - 1) < 1e-9 and _close(wp.normal, (0, 0, 1))

    rendered, wp = _make("midplane", {"face": [_picked_face(base, "base.face.left")], "face_b": [_picked_face(base, "base.face.right")]})
    assert "make_workplane_midplane_rworkplane(_face, _face_b)" in rendered.feature and _close(wp.origin, (0, 0, 2.5))

    corners = ql.vertices().where(ql.prop("geom.center.z", ">", 4)).resolve(base)
    a, b, c = corners[0], corners[1], corners[2]
    rendered, wp = _make("points", {"point_a": [_picked_vertex(a)], "point_b": [_picked_vertex(b)], "point_c": [_picked_vertex(c)]})
    assert "make_workplane_from_points_rworkplane(_point_a, _point_b, _point_c)" in rendered.feature
    assert _close(wp.origin, a.get_coordinates()) and abs(abs(wp.normal[2]) - 1) < 1e-9

    rendered, wp = _make("axis", {"edge": [_picked_edge(edge)]}, angle=90.0)
    assert "make_workplane_from_axis_rworkplane(_edge, WP_ANGLE)" in rendered.feature
    assert abs(abs(wp.x_dir[1]) - 1) < 1e-9 and abs(wp.normal[2]) < 1e-9  # x along the edge; turned 90 degrees off the top
    assert top is not None


def test_a_method_without_its_picks_is_refused():
    with pytest.raises(F.FeatureError, match="pick"):
        F.render_feature("workplane", "wp", {"body": "base", "method": "midplane"}, bodies=BODIES,
                         selections={"face": [_picked_face(_base(), "base.face.top")]}, known_slugs={"base"})


def test_an_edit_keeps_each_picked_recipe_of_a_cell_with_several():
    base = _base()
    edge = ql.edges().where(ql.prop("geom.length", ">", 19)).resolve(base)[0]
    rendered, _ = _make("face_edge", {"face": [_picked_face(base, "base.face.top")], "edge": [_picked_edge(edge)]})
    face_recipe = F.extract_recipe(rendered.feature, "face")
    edge_recipe = F.extract_recipe(rendered.feature, "edge")
    assert face_recipe[-1].startswith("_face = ") and not any(line.startswith("_edge") for line in face_recipe)
    assert edge_recipe[0].startswith("# edge") and not any(line.startswith("_face") for line in edge_recipe)
    again = F.render_feature("workplane", "wp", {"body": "base", "method": "face_edge", "offset": 5.0}, bodies=BODIES,
                             keep_recipes={"face": face_recipe, "edge": edge_recipe}, known_slugs={"base"})
    scope = {"scad": scad, "base": _base()}
    _run(again, scope)
    assert _close(scope["wp"].origin, (0, 0, 10))


def test_a_sketch_on_a_workplane_variable_writes_plane_equals_the_variable():
    frame = {"origin": [0.0, 0.0, 5.0], "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0]}
    doc = {**RECT_SKETCH, "plane": {"workplane": "wp_top", **frame}}
    clean = S.validate(doc)
    assert clean["plane"]["workplane"] == "wp_top" and S.plane_workplane(clean["plane"]) == "wp_top"
    assert S.plane_normal(clean["plane"]) == [0.0, 0.0, 1.0]
    assert S.solve(doc)["status"]  # solving uses the kernel's frame the document carries
    rendered = F.render_feature("sketch", "boss", {"sketch": doc}, bodies={})
    assert "plane=wp_top)" in rendered.feature and "wp_top" in rendered.reads

    # the cell runs on the notebook's workplane, wherever it is now (not the frame in the document)
    scope = {"scad": scad, "wp_top": scad.make_workplane_rworkplane((0, 0, 12))}
    _run(rendered, scope)
    x0, y0, z0, x1, y1, z1 = scope["boss"]._bounds()
    assert abs(z0 - 12) < 1e-6 and abs(z1 - 12) < 1e-6
    for bad in ("not a name", "class", 3):
        with pytest.raises(S.SketchError):
            S.validate_plane({"workplane": bad, **frame})


def test_the_kernel_reports_the_frames_of_the_workplane_variables():
    values = {"wp_top": scad.make_workplane_rworkplane((0, 0, 5), (0, 1, 0)), "base": _base(), "n": 3}
    (frame,) = workplane_frames(values)
    assert frame["name"] == "wp_top" and _close(frame["origin"], (0, 0, 5)) and _close(frame["normal"], (0, 1, 0))
    assert set(frame) == {"name", "origin", "x_axis", "y_axis", "normal"}
    log = "SCA-PREVIEWED 1 1 10 1 1 1\nSCA-WORKPLANES " + '[{"name": "wp", "origin": [0, 0, 1]}]\n'
    result = MarimoKernel._preview_result({"log": log})
    assert result["ok"] and result["workplanes"] == [{"name": "wp", "origin": [0, 0, 1]}]
    assert "workplanes" not in MarimoKernel._preview_result({"log": "SCA-PREVIEW-ERROR x: y"})
    assert MarimoKernel._preview_result({"log": "SCA-PREVIEW-ERROR x: y\nSCA-WORKPLANES []"})["workplanes"] == []


def test_the_server_sends_the_workplanes_when_they_change(tmp_path):
    from simplecadapi.editor.server import WorkspaceState

    state = WorkspaceState(tmp_path)
    sent: list[dict] = []
    state.hub.broadcast = sent.append
    frames = [{"name": "wp", "origin": [0, 0, 1], "x_axis": [1, 0, 0], "y_axis": [0, 1, 0], "normal": [0, 0, 1]}]
    state._push_workplanes(frames)
    state._push_workplanes(frames)  # unchanged: not sent again
    state._push_workplanes(None)  # the kernel said nothing: nothing to send
    assert [m for m in sent if m["type"] == "workplanes"] == [{"type": "workplanes", "workplanes": frames}]
    assert state.latest["workplanes"]["workplanes"] == frames  # replayed to a page that connects later

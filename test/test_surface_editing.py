"""Editing existing curves and surfaces as recorded operations (src/cpp/src/surface/editing).

Every edit returns a new Edge / Face, is a node of the graph with its TopoDelta (the face and its edges continue), and
replays from model JSON; tags and stable references follow the edited entities.  The read and sampling operations are
diagnostic and record nothing.
"""

from __future__ import annotations

import json

import pytest

import simplecadapi as scad
from simplecadapi import catalog, ql
from simplecadapi.recording.serializer import export_graph_json, import_graph_json, replay_graph
from simplecadapi.topology import element_ref as er

GRID = [[(x, y, 1.0 if (x, y) == (1, 1) else 0.0) for y in range(3)] for x in range(3)]
CURVE = [(0, 0, 0), (1, 2, 0), (2, 0, 0), (3, 2, 0)]


def _ops(session) -> list[str]:
    return [node["op"] for node in json.loads(export_graph_json(session.graph))["nodes"]]


def _points(edge, count=9):
    return scad.sample_curve_rcurvature(edge, count)["points"]


def _close(a, b, tol=1e-7):
    return all(abs(x - y) <= tol for p, q in zip(a, b) for x, y in zip(p, q))


def test_inspect_reports_poles_knots_and_whether_the_geometry_is_editable():
    face = scad.make_bezier_surface_rface(GRID)
    data = scad.inspect_surface_rsurfacedata(face)
    assert (data["type"], data["editable"], data["u_degree"], data["v_degree"]) == ("bezier", True, 2, 2)
    assert data["poles"][1][1] == [1.0, 1.0, 1.0] and data["trimmed"] is False
    assert data["u_knots"] == [0.0, 1.0] and data["u_multiplicities"] == [3, 3]

    line = scad.make_line_redge((0, 0, 0), (5, 0, 0))
    curve = scad.inspect_curve_rcurvedata(line)
    assert (curve["type"], curve["editable"], curve["conversion"]) == ("line", False, "convert_to_bspline_redge")
    assert curve["degree"] == 1 and curve["poles"][-1] == pytest.approx([5, 0, 0])

    top = ql.faces().where(ql.prop("geom.center.z", ">=", 9.99)).exactly(1).resolve(scad.make_box_rsolid(10, 10, 10))[0]
    assert scad.inspect_surface_rsurfacedata(top)["conversion"] == "convert_to_bspline_rface"


def test_surface_edits_keep_the_input_and_the_shape_keeping_edits_keep_the_shape():
    face = scad.make_bezier_surface_rface(GRID)
    moved = scad.move_surface_poles_rface(face, {(1, 1): (1, 1, 3)})
    assert scad.inspect_surface_rsurfacedata(face)["poles"][1][1] == [1.0, 1.0, 1.0]  # input untouched
    assert scad.inspect_surface_rsurfacedata(moved)["poles"][1][1] == [1.0, 1.0, 3.0]
    knotted = scad.insert_surface_knot_rface(moved, "V", 0.25)
    elevated = scad.elevate_surface_degree_rface(knotted, u_degree=3, v_degree=3)
    data = scad.inspect_surface_rsurfacedata(elevated)
    assert (len(data["poles"]), len(data["poles"][0]), data["u_degree"]) == (4, 6, 3)  # 4 + one pole per V span (2)
    for out in (knotted, elevated):
        assert out.get_area() == pytest.approx(moved.get_area(), rel=1e-6)
    weights = [[1.0] * 3 for _ in range(3)]
    weights[1][1] = 3.0
    weighted = scad.set_surface_weights_rface(moved, weights)
    assert scad.inspect_surface_rsurfacedata(weighted)["rational"] is True
    assert weighted.get_area() > moved.get_area()


def test_curve_edits_and_the_explicit_conversion_of_an_analytic_edge():
    edge = scad.make_spline_redge(control_points=CURVE)
    poles = scad.inspect_curve_rcurvedata(edge)["poles"]
    poles[-1] = [4.0, 4.0, 0.0]
    assert scad.inspect_curve_rcurvedata(scad.set_curve_poles_redge(edge, poles))["poles"][-1] == [4.0, 4.0, 0.0]
    moved = scad.move_curve_poles_redge(edge, {1: (1, 5, 0)})
    knotted = scad.insert_curve_knot_redge(moved, 0.5)
    elevated = scad.elevate_curve_degree_redge(knotted, 4)
    assert _close(_points(knotted), _points(moved)) and _close(_points(elevated), _points(moved))
    assert len(scad.inspect_curve_rcurvedata(elevated)["poles"]) == 7  # 5 + one per span (2)
    assert scad.inspect_curve_rcurvedata(scad.set_curve_weights_redge(edge, [1, 4, 1, 1]))["rational"]

    line = scad.make_line_redge((0, 0, 0), (5, 0, 0))
    with pytest.raises(Exception, match="convert_to_bspline_redge"):
        scad.move_curve_poles_redge(line, {0: (0, 1, 0)})
    bent = scad.move_curve_poles_redge(scad.elevate_curve_degree_redge(scad.convert_to_bspline_redge(line), 2),
                                       {1: (2.5, 2, 0)})
    assert max(p[1] for p in _points(bent)) == pytest.approx(1.0)


def test_every_edit_is_recorded_and_replays_from_model_json():
    with scad.GraphSession() as session:
        face = scad.make_bezier_surface_rface(GRID)
        face = scad.move_surface_poles_rface(face, {(1, 1): (1, 1, 2)}, tag_prefix="skin")
        face = scad.insert_surface_knot_rface(face, "U", 0.5, 2)
        face = scad.elevate_surface_degree_rface(face, v_degree=3)
        rows = scad.inspect_surface_rsurfacedata(face)
        weights = [[1.0] * len(rows["poles"][0]) for _ in rows["poles"]]
        weights[2][2] = 2.0
        face = scad.set_surface_weights_rface(face, weights)
        poles = scad.inspect_surface_rsurfacedata(face)["poles"]
        poles[0][0] = [0.0, 0.0, -0.5]
        face = scad.set_surface_poles_rface(face, poles)
        face = scad.rebuild_surface_rface(face, 3, 3, 6, 6)
        edge = scad.make_spline_redge(control_points=CURVE)
        edge = scad.move_curve_poles_redge(edge, {2: (2, -1, 0)})
        edge = scad.insert_curve_knot_redge(edge, 0.3)
        edge = scad.elevate_curve_degree_redge(edge, 4)
        edge = scad.set_curve_weights_redge(edge, [1.0, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0])
        edge = scad.rebuild_curve_redge(edge, 3, tolerance=1e-4)
        line = scad.convert_to_bspline_redge(scad.make_line_redge((0, 0, 0), (0, 0, 5)))
        line = scad.set_curve_poles_redge(line, [(0, 0, 0), (1, 0, 5)])
        plane = scad.convert_to_bspline_rface(scad.make_rectangle_rface(4, 2))
        session.capture_result(value=face)
        session.capture_result(value=edge)
        session.capture_result(value=line)
        session.capture_result(value=plane)
    ops = _ops(session)
    for op in ("move_surface_poles_rface", "insert_surface_knot_rface", "elevate_surface_degree_rface",
               "set_surface_weights_rface", "set_surface_poles_rface", "rebuild_surface_rface", "move_curve_poles_redge",
               "insert_curve_knot_redge", "elevate_curve_degree_redge", "set_curve_weights_redge", "rebuild_curve_redge",
               "convert_to_bspline_redge", "set_curve_poles_redge", "convert_to_bspline_rface"):
        assert ops.count(op) == 1, (op, ops)
    assert "inspect_surface_rsurfacedata" not in ops  # diagnostic
    payload = json.loads(export_graph_json(session.graph))
    node = next(n for n in payload["nodes"] if n["op"] == "move_surface_poles_rface")
    assert node["params"]["moves"] == [[1, 1, [1.0, 1.0, 2.0]]] and node["params"]["tag_prefix"] == "skin"
    assert {e["event"] for e in node["topo_delta"]["entries"]} == {"MODIFIED"} and len(node["topo_delta"]["entries"]) == 5

    rebuilt = replay_graph(import_graph_json(json.dumps(payload)))
    by_kind = {type(v).__name__: [] for v in rebuilt}
    for value in rebuilt:
        by_kind[type(value).__name__].append(value)
    assert len(by_kind["Face"]) == 2
    face_out = min(by_kind["Face"], key=lambda f: abs(f.get_area() - face.get_area()))
    assert face_out.get_area() == pytest.approx(face.get_area(), rel=1e-9)
    assert sorted(f.get_area() for f in by_kind["Face"])[-1] == pytest.approx(8.0)  # the converted rectangle
    replayed = scad.inspect_surface_rsurfacedata(face_out)
    original = scad.inspect_surface_rsurfacedata(face)["poles"]
    assert all(_close(a, b, 1e-9) for a, b in zip(replayed["poles"], original))
    edges = {round(e.get_length(), 9): e for e in by_kind["Edge"]}
    assert round(edge.get_length(), 9) in edges and round(line.get_length(), 9) in edges


def test_tags_and_references_follow_a_face_and_its_edges_through_edits():
    with scad.GraphSession():
        face = scad.make_bezier_surface_rface(GRID)
        face = scad.apply_tag_rselection(face, [face], "user.skin")
        (rim,) = ql.edges().where(ql.prop("geom.center.x", "<=", 1e-6)).resolve(face)
        face = scad.apply_tag_rselection(face, [rim], "user.rim")
        anchor = er.anchor_of(face)
        edited = scad.move_surface_poles_rface(face, {(1, 1): (1, 1, 4)})
        edited = scad.insert_surface_knot_rface(edited, "U", 0.5)
        edited = scad.elevate_surface_degree_rface(edited, u_degree=3)

        assert len(ql.faces().where(ql.tag("user.skin")).resolve(edited)) == 1
        (tagged_rim,) = ql.edges().where(ql.tag("user.rim")).resolve(edited)
        assert tagged_rim.get_center().x == pytest.approx(0.0)
        resolved = er.resolve(anchor, edited)
        assert resolved.status == "ok"
        assert [hop["op"] for hop in resolved.hops][-1] == "elevate_surface_degree_rface"

        curve = scad.make_spline_redge(control_points=CURVE)
        curve = scad.apply_tag_rselection(curve, [curve], "user.curve")
        curve = scad.elevate_curve_degree_redge(scad.move_curve_poles_redge(curve, {1: (1, 3, 0)}), 5)
        assert len(ql.edges().where(ql.tag("user.curve")).resolve(curve)) == 1


def test_a_face_picked_from_a_solid_is_converted_edited_and_replayed():
    with scad.GraphSession() as session:
        box = scad.make_box_rsolid(10, 10, 10)
        (top,) = ql.faces().where(ql.prop("geom.center.z", ">=", 9.99)).resolve(box)
        nurbs = scad.convert_to_bspline_rface(top)
        data = scad.inspect_surface_rsurfacedata(nurbs)
        assert data["type"] == "bspline" and data["editable"]
        nurbs = scad.elevate_surface_degree_rface(nurbs, 2, 2)
        domed = scad.move_surface_poles_rface(nurbs, {(1, 1): (5, 5, 14)})
        session.capture_result(value=domed)
    (out,) = replay_graph(import_graph_json(export_graph_json(session.graph)))
    assert out.get_area() == pytest.approx(domed.get_area(), rel=1e-9)
    assert out.get_area() > 100.0


def test_bad_arguments_name_what_fits():
    face = scad.make_bezier_surface_rface(GRID)
    with pytest.raises(Exception, match="3 x 3 grid"):
        scad.set_surface_poles_rface(face, [[(0, 0, 0)]])
    with pytest.raises(Exception, match="out of range"):
        scad.move_surface_poles_rface(face, {(5, 0): (0, 0, 0)})
    with pytest.raises(Exception, match="strictly inside"):
        scad.insert_surface_knot_rface(face, "U", 1.5)
    with pytest.raises(Exception, match="'U' or 'V'"):
        scad.insert_surface_knot_rface(face, "W", 0.5)
    with pytest.raises(Exception, match="cannot be lowered"):
        scad.elevate_surface_degree_rface(face, u_degree=1)
    with pytest.raises(Exception, match="both"):
        scad.rebuild_surface_rface(face, u_pole_count=5)


def test_sampling_for_an_editor():
    edge = scad.make_spline_redge(control_points=CURVE)
    comb = scad.sample_curve_rcurvature(edge, 16)
    assert len(comb["points"]) == len(comb["curvatures"]) == len(comb["normals"]) == 16
    assert comb["max_curvature"] == pytest.approx(max(comb["curvatures"]))
    carrier = scad.make_bezier_surface_rface([[(0, 0, 0), (0, 4, 0)], [(4, 0, 0), (4, 4, 0)]])
    window = scad.trim_surface_rface(carrier, scad.make_rectangle_rwire(2, 2, center=(2, 2, 0)))
    iso = scad.sample_surface_risocurves(window, u_count=3, v_count=1, samples=40)
    assert [len(line["segments"]) for line in iso["u"]] == [1, 1, 1]
    xs = [p[0] for line in iso["v"] for segment in line["segments"] for p in segment]
    assert min(xs) >= 1.0 - 1e-6 and max(xs) <= 3.0 + 1e-6


def test_the_catalog_types_every_parameter():
    kinds = {p.name: p.kind for p in catalog.operation("move_surface_poles_rface").params}
    assert kinds == {"face": "face", "moves": "point3_map", "tag_prefix": "text"}
    knot = {p.name: (p.kind, p.choices) for p in catalog.operation("insert_surface_knot_rface").params}
    assert knot["direction"] == ("enum", ("U", "V")) and knot["multiplicity"][0] == "count"
    assert catalog.operation("set_surface_poles_rface").params[1].kind == "grid"
    assert catalog.operation("set_curve_poles_redge").params[1].kind == "points"
    assert catalog.operation("elevate_curve_degree_redge").returns == "edge"

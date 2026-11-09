"""An edge is taken wherever a wire is: the wire of that one edge, made by the recorded make_wire_from_edges_rwire (a
curve drawn in the editor is one edge; a sweep path, a loft section or a face boundary asks for a wire)."""

import pytest

import simplecadapi as s
from simplecadapi.recording.graph import GraphSession


def _ring():
    return s.make_face_from_wire_rface(s.make_circle_rwire(center=(0, 0, 0), radius=2, normal=(1, 0, 0)), normal=(1, 0, 0))


def test_an_edge_is_a_sweep_path_a_loft_section_and_a_face_boundary():
    path = s.make_interpolated_spline_redge(points=[(0, 0, 0), (30, 10, 10), (60, 0, 25)])
    swept = s.sweep_rsolid(_ring(), path, False)
    assert swept.get_volume() == pytest.approx(s.sweep_rsolid(_ring(), s.Wire(path), False).get_volume())
    loop = s.make_interpolated_spline_redge(points=[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 0, 0)])
    top = s.make_interpolated_spline_redge(points=[(0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10), (0, 0, 10)])
    assert s.loft_rsolid([loop, top]).get_volume() > 1000
    assert s.make_face_from_wire_rface(loop, normal=(0, 0, 1)).get_area() > 100
    with pytest.raises(s.SimpleCADError, match="must be a Wire"):
        s.make_face_from_wire_rface(s.make_box_rsolid(1, 1, 1), normal=(0, 0, 1))


def test_a_surface_between_two_open_curves_and_the_wrap_is_recorded():
    with GraphSession() as session:
        a = s.make_segment_redge((0, 0, 0), (10, 0, 0))
        b = s.make_interpolated_spline_redge(points=[(0, 0, 10), (5, 4, 12), (10, 0, 15)])
        skin = s.loft_rshell([a, b])
        session.capture_result(value=skin)
    assert len(s.ql.faces().resolve(skin)) == 1
    ops = [node.op for node in session.graph.nodes]
    assert ops.count("make_wire_from_edges_rwire") == 2 and ops[-1] == "make_loft_rshell"
    replayed = s.replay_model_json(s.export_model_json(session))[0]
    assert replayed.get_area() == pytest.approx(skin.get_area())
    with pytest.raises(s.SimpleCADError, match="closed Wire start section"):
        s.loft_rshell([a, b], start_wire_tag="lip")


def test_edges_given_in_any_order_make_one_wire_and_a_stray_one_is_an_error():
    a = s.make_segment_redge((0, 0, 0), (10, 0, 0))
    b = s.make_segment_redge((10, 0, 0), (10, 10, 0))
    c = s.make_segment_redge((10, 10, 0), (0, 10, 5))
    for order in ([a, b, c], [c, a, b], [a, c, b]):
        assert len(s.ql.edges().resolve(s.make_wire_from_edges_rwire(order))) == 3
    with pytest.raises(s.SimpleCADError, match="do not connect into one wire"):
        s.make_wire_from_edges_rwire([a, b, s.make_segment_redge((50, 50, 0), (60, 50, 0))])

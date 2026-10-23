"""Points, lines, segments, polylines, arcs, helices and wire assembly against the reference."""

import math

import pytest

import simplecadapi._cpp as scad
from ops_geometry_support import parity


def test_point_line_and_segments():
    parity("lines", """
        result = {
            "point": describe(scad.make_point_rvertex(1, 2, 3)),
            "line": describe(scad.make_line_redge((0, 0, 0), (3, 4, 0))),
            "line_prefixed": describe(scad.make_line_redge((0, 0, 0), (0, 0, 2), tag_prefix="axis")),
            "segment_edge": describe(scad.make_segment_redge((0, 0, 0), (1, 0, 0))),
            "segment_wire": describe(scad.make_segment_rwire((0, 0, 0), (0, 5, 0))),
            "aliases": [describe(scad.create_point(0, 0, 1)), describe(scad.create_line((0, 0, 0), (1, 1, 1))),
                        describe(scad.create_segment((0, 0, 0), (2, 0, 0))), describe(scad.create_segment_wire((0, 0, 0), (2, 0, 0)))],
        }
    """)


def test_lines_follow_the_workplane():
    parity("lines_workplane", """
        with scad.SimpleWorkplane(origin=(1, 2, 3), normal=(0, 0, 1), x_dir=(0, 1, 0)):
            result = {
                "point": describe(scad.make_point_rvertex(1, 0, 0)),
                "line": describe(scad.make_line_redge((0, 0, 0), (2, 0, 0))),
                "polyline": describe(scad.make_polyline_rwire([(0, 0, 0), (1, 0, 0), (1, 1, 0)])),
            }
    """)


def test_polylines():
    parity("polyline", """
        points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        result = {
            "open": describe(scad.make_polyline_rwire(points)),
            "closed": describe(scad.make_polyline_rwire(points, closed=True)),
            "two_points_closed": describe(scad.make_polyline_rwire(points[:2], closed=True)),
            "alias": describe(scad.create_polyline_wire(points)),
        }
    """)


def test_line_and_polyline_failures():
    parity("lines_failures", """
        result = {
            "one_point": failure(lambda: scad.make_polyline_rwire([(0, 0, 0)])),
            "coincident": failure(lambda: scad.make_line_redge((1, 1, 1), (1, 1, 1))),
            "segment_coincident": failure(lambda: scad.make_segment_rwire((0, 0, 0), (0, 0, 0))),
        }
    """)


def test_three_point_arcs():
    parity("arcs_three_point", """
        result = {
            "edge": describe(scad.make_three_point_arc_redge((0, 0, 0), (1, 1, 0), (2, 0, 0))),
            "wire": describe(scad.make_three_point_arc_rwire((0, 0, 0), (1, 1, 0), (2, 0, 0))),
            "alias": describe(scad.create_arc((1, 0, 0), (0, 1, 0), (-1, 0, 0))),
            "alias_wire": describe(scad.create_arc_wire((1, 0, 0), (0, 1, 0), (-1, 0, 0))),
            "collinear": failure(lambda: scad.make_three_point_arc_redge((0, 0, 0), (1, 0, 0), (2, 0, 0))),
            "collinear_wire": failure(lambda: scad.make_three_point_arc_rwire((0, 0, 0), (1, 0, 0), (2, 0, 0))),
        }
    """)


def test_angle_arcs():
    parity("arcs_angle", """
        import math
        result = {
            "quarter": describe(scad.make_angle_arc_redge((0, 0, 0), 1.0, 0, math.pi / 2)),
            "tilted": describe(scad.make_angle_arc_redge((1, 2, 3), 2.0, 0.5, 2.5, normal=(1, 1, 1))),
            "wire": describe(scad.make_angle_arc_rwire((0, 0, 0), 1.0, 0, math.pi / 2)),
            "alias": describe(scad.create_angle_arc((0, 0, 0), 3.0, 0, 1.0)),
            "alias_wire": describe(scad.create_angle_arc_wire((0, 0, 0), 3.0, 0, 1.0)),
            "negative_radius": failure(lambda: scad.make_angle_arc_redge((0, 0, 0), -1.0, 0, math.pi / 2)),
            "same_angles": failure(lambda: scad.make_angle_arc_redge((0, 0, 0), 1.0, 0, 0)),
            "wire_negative_radius": failure(lambda: scad.make_angle_arc_rwire((0, 0, 0), -1.0, 0, 1)),
        }
    """)


def test_helices():
    parity("helix", """
        result = {
            "right": describe(scad.make_helix_redge(pitch=2.0, height=10.0, radius=3.0)),
            "left": describe(scad.make_helix_redge(pitch=2.0, height=10.0, radius=3.0, handedness="Left")),
            "tilted": describe(scad.make_helix_redge(1.0, 3.0, 0.5, center=(1, 2, 3), dir=(1, 0, 0))),
            "wire": describe(scad.make_helix_rwire(pitch=1.0, height=3.0, radius=0.5)),
            "alias": describe(scad.create_helix(1.0, 2.0, 0.5)),
            "alias_wire": describe(scad.create_helix_wire(1.0, 2.0, 0.5)),
            "negative_pitch": failure(lambda: scad.make_helix_redge(-1.0, 3.0, 0.5)),
            "zero_height": failure(lambda: scad.make_helix_redge(1.0, 0, 0.5)),
            "negative_radius": failure(lambda: scad.make_helix_redge(1.0, 3.0, -0.5)),
            "handedness": failure(lambda: scad.make_helix_redge(2.0, 10.0, 3.0, handedness="wrong")),
        }
    """, rel=1e-4)


def _winding(edge):
    """Signed turns about +Z along a helix, from its vertices' sampled spiral: the edge is split by length."""
    wire_turns = 0.0
    previous = None
    points = scad._native._geometry_testing.sample(edge, 400)
    for x, y, _ in points:
        theta = math.atan2(y, x)
        if previous is not None:
            delta = theta - previous
            while delta > math.pi:
                delta -= 2 * math.pi
            while delta < -math.pi:
                delta += 2 * math.pi
            wire_turns += delta
        previous = theta
    return wire_turns / (2 * math.pi), points[-1][2] - points[0][2]


def test_helix_handedness_matches_the_reference_tests():
    # test_helix_handedness.py: right-handed turns counter-clockwise ascending, left-handed clockwise.
    turns, rise = _winding(scad.make_helix_redge(pitch=2.0, height=10.0, radius=3.0))
    assert turns == pytest.approx(5.0, abs=1e-3) and rise == pytest.approx(10.0)
    turns, rise = _winding(scad.make_helix_redge(pitch=2.0, height=10.0, radius=3.0, handedness="Left"))
    assert turns == pytest.approx(-5.0, abs=1e-3) and rise == pytest.approx(10.0)
    right = scad.make_helix_redge(pitch=2.0, height=10.0, radius=3.0)
    left = scad.make_helix_redge(pitch=2.0, height=10.0, radius=3.0, handedness="Left")
    assert right.get_length() == pytest.approx(left.get_length())


def test_helix_wire_honours_handedness():
    # The reference drops `handedness` when it is not recording and always builds a right-handed
    # wire; this port does not (see make_helix_rwire in helix.hpp).
    wire = scad.make_helix_rwire(pitch=2.0, height=10.0, radius=3.0, handedness="Left")
    turns, _ = _winding(wire.edges()[0])
    assert turns == pytest.approx(-5.0, abs=1e-3)


def test_wire_from_edges():
    parity("wire_from_edges", """
        e1 = scad.make_line_redge((0, 0, 0), (1, 0, 0))
        e2 = scad.make_line_redge((1, 0, 0), (1, 1, 0))
        e3 = scad.make_line_redge((1, 1, 0), (0, 0, 0))
        chain = scad.make_wire_from_edges_rwire([e1, e2, e3])
        labelled = [scad.make_line_redge((0, 0, 0), (2, 0, 0), tag_prefix="a"), scad.make_line_redge((2, 0, 0), (2, 2, 0), tag_prefix="b")]
        result = {
            "triangle": describe(chain),
            "prefixed": describe(scad.make_wire_from_edges_rwire([e1, e2], tag_prefix="path")),
            "identity_tags": describe(scad.make_wire_from_edges_rwire(labelled)),
            "alias": describe(scad.create_wire_from_edges([e1])),
            "empty": failure(lambda: scad.make_wire_from_edges_rwire([])),
            "gap": failure(lambda: scad.make_wire_from_edges_rwire([e1, scad.make_line_redge((5, 5, 0), (6, 5, 0))])),
        }
    """)

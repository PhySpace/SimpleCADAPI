"""cut_rsolid_list: a cut that splits the body keeps every piece; cut_rsolid refuses to drop any.

The old SDK returned the first piece of a split silently (a slot through a bar lost half the bar), so there is no golden
to compare with: the expected volumes are worked out here.
"""

from __future__ import annotations

import math

import pytest

import simplecadapi as scad
from simplecadapi.recording.serializer import replay_graph

BAR = (100.0, 20.0, 10.0)


def bar():
    return scad.make_box_rsolid(*BAR, bottom_face_center=(0, 0, 0))


def slot(x):
    return scad.make_box_rsolid(10, 40, 30, bottom_face_center=(x, 0, -10))


def plate():
    return scad.make_box_rsolid(100, 100, 10, bottom_face_center=(0, 0, 0))


def cylinder(radius):
    return scad.make_cylinder_rsolid(radius, 30, bottom_face_center=(0, 0, -10))


def volumes(pieces):
    return sorted(round(p.get_volume(), 3) for p in pieces)


def test_a_slot_through_a_bar_gives_both_halves():
    assert volumes(scad.cut_rsolid_list(bar(), slot(0))) == [9000.0, 9000.0]


def test_several_tools_split_every_piece_they_meet():
    pieces = scad.cut_rsolid_list(bar(), [slot(-20), slot(20)])
    assert volumes(pieces) == [5000.0, 5000.0, 6000.0]
    assert math.isclose(sum(p.get_volume() for p in pieces), 16000.0)


def test_a_tool_cutting_a_piece_made_by_an_earlier_tool():
    # the second tool lies in the part the first one cut off
    pieces = scad.cut_rsolid_list(bar(), slot(0), slot(30))
    assert math.isclose(sum(p.get_volume() for p in pieces), 100 * 20 * 10 - 2 * 10 * 20 * 10)
    assert len(pieces) == 3


def test_the_four_corners_left_by_a_big_cylinder_are_all_kept():
    pieces = scad.cut_rsolid_list(plate(), cylinder(70))
    assert len(pieces) == 4
    assert all(math.isclose(p.get_volume(), 5.068, abs_tol=1e-3) for p in pieces)


def test_a_tool_that_encloses_the_body_leaves_nothing():
    assert scad.cut_rsolid_list(plate(), cylinder(75)) == []


def test_one_piece_result_and_a_missing_tool():
    (single,) = scad.cut_rsolid_list(plate(), cylinder(40))
    assert math.isclose(single.get_volume(), 100 * 100 * 10 - math.pi * 40**2 * 10, rel_tol=1e-4)
    far = scad.make_box_rsolid(5, 5, 5, bottom_face_center=(0, 100, 0))
    assert volumes(scad.cut_rsolid_list(bar(), far)) == [20000.0]
    with pytest.raises(scad.SimpleCADError, match="does not intersect"):
        scad.cut_rsolid_list(bar(), far, skip_non_intersecting=False)


def test_cut_rsolid_refuses_a_split_instead_of_dropping_pieces():
    with pytest.raises(scad.SimpleCADError) as error:
        scad.cut_rsolid(bar(), slot(0))
    text = str(error.value)
    assert "returned 2 solids" in text and "cut_rsolid_list" in text
    with pytest.raises(scad.SimpleCADError, match="no valid solid"):
        scad.cut_rsolid(plate(), cylinder(75))


def test_the_pieces_carry_the_cut_tags_and_one_graph_node():
    with scad.GraphSession() as session:
        body = bar()
        pieces = scad.cut_rsolid_list(body, [slot(-20), slot(20)])
    assert all(p.get_metadata("track")["op"] == "make_cut_rsolid_list" for p in pieces)
    nodes = [n for n in session.graph.to_dict()["nodes"] if n["op"] == "make_cut_rsolid_list"]
    assert len(nodes) == 1
    replayed = [x for r in replay_graph(session.graph) for x in (r if isinstance(r, (list, tuple)) else [r])]
    assert volumes(replayed) == volumes(pieces)

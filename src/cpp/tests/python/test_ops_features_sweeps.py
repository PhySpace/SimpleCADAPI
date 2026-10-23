"""extrude_rsolid and revolve_rsolid against the reference SDK."""

import pytest
from ops_features_support import compare, parameter_names

import simplecadapi._cpp as scad


def test_extrude_face_with_tags():
    compare("extrude_face_tags", """
        face = scad.make_rectangle_rface(2.0, 1.0)
        solid = scad.extrude_rsolid(face, (0, 0, 1), 3.0, tag_prefix="part", result_tag="role.body",
                                    start_face_tag="role.start", end_face_tag="role.end", side_faces_tag="role.sides")
        result = describe(solid)
    """)


def test_extrude_wire_and_direction_in_workplane():
    compare("extrude_wire_workplane", """
        wire = scad.make_rectangle_rwire(4.0, 2.0)
        with scad.SimpleWorkplane(origin=(1, 2, 3), normal=(1, 0, 0)):
            solid = scad.extrude_rsolid(wire, (0, 0, 1), 5.0)
        result = describe(solid)
    """)


def test_extrude_keeps_profile_tags_on_the_side_faces():
    compare("extrude_profile_tags", """
        face = scad.make_rectangle_rface(2.0, 3.0, tag_prefix="pad")
        solid = scad.extrude_rsolid(face, (0, 0, 1), 1.5)
        result = describe(solid)
    """)


def test_extrude_errors():
    compare("extrude_errors", """
        face = scad.make_rectangle_rface(2.0, 1.0)
        open_u = scad.make_wire_from_edges_rwire([
            scad.make_line_redge((0, 0, 0), (10, 0, 0)), scad.make_line_redge((10, 0, 0), (10, 6, 0)),
            scad.make_line_redge((10, 6, 0), (0, 6, 0)), scad.make_line_redge((0, 6, 0), (0, 0.8, 0))])
        result = {
            "distance": failure(lambda: scad.extrude_rsolid(face, (0, 0, 1), 0)),
            "direction": failure(lambda: scad.extrude_rsolid(face, (0, 0, 0), 2)),
            "open": failure(lambda: scad.extrude_rsolid(open_u, (0, 0, 1), 2)),
            "bad_tag": failure(lambda: scad.extrude_rsolid(face, (0, 0, 1), 2, result_tag="Not A Tag")),
            "wrong_kind": failure(lambda: scad.extrude_rsolid(scad.make_box_rsolid(1, 1, 1), (0, 0, 1), 2)),
        }
    """)


def test_revolve_partial_and_full():
    compare("revolve", """
        face = scad.make_rectangle_rface(1.0, 2.0, center=(2, 0, 0))
        half = scad.revolve_rsolid(face, (0, 1, 0), 180, (0, 0, 0), tag_prefix="arm", start_face_tag="role.s")
        full = scad.revolve_rsolid(face, (0, 1, 0), 360)
        result = {"half": describe(half), "full": describe(full)}
    """)


def test_revolve_errors():
    compare("revolve_errors", """
        face = scad.make_rectangle_rface(1.0, 2.0, center=(2, 0, 0))
        open_u = scad.make_wire_from_edges_rwire([
            scad.make_line_redge((0, 0, 0), (1, 0, 0)), scad.make_line_redge((1, 0, 0), (1, 1, 0))])
        result = {
            "angle": failure(lambda: scad.revolve_rsolid(face, (0, 1, 0), -5)),
            "open": failure(lambda: scad.revolve_rsolid(open_u, (0, 1, 0), 90)),
        }
    """)


def test_signatures_match_python():
    for name, params in {
        "extrude_rsolid": ["profile", "direction", "distance", "tag_prefix", "result_tag", "start_face_tag", "end_face_tag", "side_faces_tag"],
        "revolve_rsolid": ["profile", "axis", "angle", "origin", "tag_prefix", "result_tag", "start_face_tag", "end_face_tag", "side_faces_tag"],
    }.items():
        assert parameter_names(getattr(scad, name)) == params

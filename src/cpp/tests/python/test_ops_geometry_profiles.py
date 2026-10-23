"""Circles, ellipses, rectangles and faces from wires against the reference."""

import pytest

import simplecadapi._cpp as scad
from ops_geometry_support import parity


def test_circles():
    parity("circles", """
        c = (1.0, 2.0, 3.0)
        result = {
            "edge": describe(scad.make_circle_redge((0, 0, 0), 1.0)),
            "edge_prefixed": describe(scad.make_circle_redge(c, 2.0, (1, 1, 0), tag_prefix="rim")),
            "wire": describe(scad.make_circle_rwire(c, 2.0)),
            "wire_tagged": describe(scad.make_circle_rwire(c, 2.0, tag_prefix="hole", edge_tag="outer")),
            "wire_edge_tag_only": describe(scad.make_circle_rwire(c, 2.0, edge_tag="outer")),
            "face": describe(scad.make_circle_rface((0, 0, 0), 1.0)),
            "face_tagged": describe(scad.make_circle_rface(c, 2.0, (0, 1, 0), tag_prefix="disc", edge_tag="rim")),
            "aliases": [describe(scad.create_circle_edge((0, 0, 0), 1)), describe(scad.create_circle_wire((0, 0, 0), 1)),
                        describe(scad.create_circle_face((0, 0, 0), 1))],
        }
    """)


def test_circle_failures():
    parity("circles_failures", """
        result = {
            "edge": failure(lambda: scad.make_circle_redge((0, 0, 0), -1.0)),
            "wire": failure(lambda: scad.make_circle_rwire((0, 0, 0), 0)),
            "face": failure(lambda: scad.make_circle_rface((0, 0, 0), -2)),
            "bad_prefix": failure(lambda: scad.make_circle_redge((0, 0, 0), 1, tag_prefix="Bad Prefix")),
        }
    """)


def test_ellipses():
    parity("ellipses", """
        result = {
            "edge": describe(scad.make_ellipse_redge((0, 0, 0), 3.0, 1.0)),
            "edge_direction": describe(scad.make_ellipse_redge((1, 1, 1), 3.0, 2.0, (0, 0, 1), major_direction=(0, 1, 0), tag_prefix="e")),
            "wire": describe(scad.make_ellipse_rwire((0, 0, 0), 3.0, 1.0)),
            "wire_tagged": describe(scad.make_ellipse_rwire((0, 0, 0), 3.0, 1.0, tag_prefix="slot", edge_tag="outline")),
            "face": describe(scad.make_ellipse_rface((0, 0, 0), 3.0, 1.0, (0, 0, 1), major_direction=(1, 1, 0))),
            "face_tagged": describe(scad.make_ellipse_rface((0, 0, 0), 2.0, 1.0, tag_prefix="lens")),
        }
    """)


def test_ellipse_failures():
    parity("ellipses_failures", """
        result = {
            "negative": failure(lambda: scad.make_ellipse_redge((0, 0, 0), -3.0, 1.0)),
            "minor_larger": failure(lambda: scad.make_ellipse_redge((0, 0, 0), 1.0, 3.0)),
            "wire": failure(lambda: scad.make_ellipse_rwire((0, 0, 0), 1.0, 3.0)),
            "face": failure(lambda: scad.make_ellipse_rface((0, 0, 0), 0, 3.0)),
        }
    """)


def test_rectangles():
    parity("rectangles", """
        result = {
            "wire": describe(scad.make_rectangle_rwire(30.0, 10.0)),
            "wire_centered": describe(scad.make_rectangle_rwire(2, 3, center=(1, 2, 3))),
            "wire_x_normal": describe(scad.make_rectangle_rwire(2, 3, (0, 0, 0), (1, 0, 0))),
            "wire_tilted": describe(scad.make_rectangle_rwire(2, 3, (0, 0, 0), (0.3, -0.4, 0.86))),
            "wire_tagged": describe(scad.make_rectangle_rwire(2, 1, tag_prefix="frame", edge_tags=("a", "b", "c", "d"))),
            "wire_edge_tags_only": describe(scad.make_rectangle_rwire(2, 1, edge_tags=("a", "b", "c", "d"))),
            "wire_prefix_only": describe(scad.make_rectangle_rwire(2, 1, tag_prefix="frame")),
            "face": describe(scad.make_rectangle_rface(2.0, 1.0)),
            "face_tagged": describe(scad.make_rectangle_rface(2, 1, (1, 0, 0), (0, 1, 0), tag_prefix="plate", edge_tags=("a", "b", "c", "d"))),
            "aliases": [describe(scad.create_rectangle_wire(1, 2)), describe(scad.create_rectangle_face(1, 2))],
        }
    """)


def test_rectangle_failures():
    parity("rectangles_failures", """
        result = {
            "width": failure(lambda: scad.make_rectangle_rwire(0, 1)),
            "height": failure(lambda: scad.make_rectangle_rwire(1, -1)),
            "zero_normal": failure(lambda: scad.make_rectangle_rwire(1, 1, (0, 0, 0), (0, 0, 0))),
            "face": failure(lambda: scad.make_rectangle_rface(-1, 1)),
            "edge_tag_count": failure(lambda: scad.make_rectangle_rwire(1, 1, edge_tags=("a", "b"))),
        }
    """)


def test_profiles_follow_the_workplane():
    parity("profiles_workplane", """
        with scad.SimpleWorkplane(origin=(1, 2, 3), normal=(0, 1, 0), x_dir=(1, 0, 0)):
            result = {
                "circle": describe(scad.make_circle_rface((1, 1, 0), 2.0, tag_prefix="c")),
                "ellipse": describe(scad.make_ellipse_rface((0, 0, 0), 3.0, 1.0)),
                "rectangle": describe(scad.make_rectangle_rface(2, 3, (1, 0, 0), tag_prefix="r")),
            }
    """)


def test_width_spans_x_like_the_box():
    # test_plane_axes_convention.py::TestRectangleAxisConvention (legacy path).
    wire = scad.make_rectangle_rwire(30.0, 10.0, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    inventory = sorted((round(e.get_center().x, 3), round(e.get_center().y, 3) + 0.0, round(e.get_length(), 3)) for e in wire.edges())
    assert inventory == [(-15.0, 0.0, 10.0), (0.0, -5.0, 30.0), (0.0, 5.0, 30.0), (15.0, 0.0, 10.0)]


def test_face_from_wire():
    parity("face_from_wire", """
        rect = scad.make_rectangle_rwire(2, 1, tag_prefix="frame", edge_tags=("a", "b", "c", "d"))
        circle = scad.make_circle_rwire((0, 0, 0), 1.5, tag_prefix="c")
        plain = scad.make_polyline_rwire([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], closed=True)
        result = {
            "rectangle": describe(scad.make_face_from_wire_rface(rect)),
            "prefixed": describe(scad.make_face_from_wire_rface(rect, tag_prefix="plate")),
            "circle": describe(scad.make_face_from_wire_rface(circle, tag_prefix="disc")),
            "polyline": describe(scad.make_face_from_wire_rface(plain)),
            "alias": describe(scad.create_face_from_wire(plain)),
        }
    """)


def test_face_from_wire_failures():
    parity("face_from_wire_failures", """
        open_wire = scad.make_polyline_rwire([(0, 0, 0), (2, 0, 0), (2, 2, 0)])
        edge = scad.make_line_redge((0, 0, 0), (1, 0, 0))
        result = {"not_a_wire": failure(lambda: scad.make_face_from_wire_rface(edge))}
        error = failure(lambda: scad.make_face_from_wire_rface(open_wire))
        # The reference attaches a rendered evidence image to this error; the port states the
        # same facts as measurements only.
        result["open"] = {k: v for k, v in error.items()}
    """)


def test_open_wire_failure_measures_the_gap():
    wire = scad.make_polyline_rwire([(0, 0, 0), (2, 0, 0), (2, 2, 0)])
    with pytest.raises(scad.SimpleCADError) as info:
        scad.make_face_from_wire_rface(wire)
    error = info.value.to_dict()
    assert error["operation"] == "make_face_from_wire_rface"
    assert "measured gap 2.828 mm" in error["what_happened"]
    assert [m["name"] for m in error["measurements"]] == ["gap", "gap end P1", "gap end P2", "edge count"]
    assert error["measurements"][0]["value"] == pytest.approx(8 ** 0.5)
    assert any("add a segment (or arc) across the two ends" in line for line in error["repair"])


def test_face_from_wires():
    parity("face_from_wires", """
        outer = scad.make_circle_rwire((0, 0, 0), 2.0)
        inner = scad.make_circle_rwire((0, 0, 0), 1.0)
        square = scad.make_rectangle_rwire(10, 10)
        holes = [scad.make_circle_rwire((-2, 0, 0), 1.0), scad.make_circle_rwire((2, 0, 0), 1.0)]
        result = {
            "ring": describe(scad.make_face_from_wires_rface(outer, [inner])),
            "plate": describe(scad.make_face_from_wires_rface(square, holes)),
            "no_holes": describe(scad.make_face_from_wires_rface(outer, [])),
            "alias": describe(scad.create_face_from_wires(outer, [inner])),
            "outer_not_wire": failure(lambda: scad.make_face_from_wires_rface(scad.make_line_redge((0, 0, 0), (1, 0, 0)), [inner])),
            "outer_open": failure(lambda: scad.make_face_from_wires_rface(scad.make_polyline_rwire([(0, 0, 0), (1, 0, 0), (1, 1, 0)]), [])),
            "inner_not_wire": failure(lambda: scad.make_face_from_wires_rface(outer, [scad.make_line_redge((0, 0, 0), (1, 0, 0))])),
            "inner_open": failure(lambda: scad.make_face_from_wires_rface(outer, [scad.make_polyline_rwire([(0, 0, 0), (1, 0, 0), (1, 1, 0)])])),
            "zero_normal": failure(lambda: scad.make_face_from_wires_rface(outer, [inner], normal=(0, 0, 0))),
        }
    """)

"""make_box_rsolid, make_cylinder_rsolid, make_cone_rsolid, make_sphere_rsolid against the reference."""

import pytest

import simplecadapi._cpp as scad
from ops_geometry_support import parity


def test_box_default_and_offset():
    parity("box_basic", """
        result = {
            "plain": describe(scad.make_box_rsolid(10, 20, 30)),
            "offset": describe(scad.make_box_rsolid(2, 3, 4, bottom_face_center=(5, -1, 2))),
            "alias": describe(scad.create_box(1, 1, 1)),
        }
    """)


def test_box_role_tags_prefix_and_result_tag():
    parity("box_tags", """
        box = scad.make_box_rsolid(
            2.0, 3.0, 4.0, tag_prefix="housing", result_tag="part.housing",
            bottom_face_tag="anchor.base", right_face_tag="role.mounting_surface",
            top_face_tag="role.lid", front_face_tag="role.front", back_face_tag="role.back", left_face_tag="role.left",
        )
        result = describe(box)
    """)


def test_box_follows_the_workplane():
    parity("box_workplane", """
        with scad.SimpleWorkplane(origin=(1, 2, 3), normal=(0, 1, 0), x_dir=(1, 0, 0)):
            box = scad.make_box_rsolid(2, 3, 4, bottom_face_center=(1, 0, 1))
            cyl = scad.make_cylinder_rsolid(1, 5, bottom_face_center=(0, 1, 0))
        result = {"box": describe(box), "cylinder": describe(cyl)}
    """)


def test_box_failures():
    parity("box_failures", """
        result = {
            "zero_width": failure(lambda: scad.make_box_rsolid(0, 1, 1)),
            "negative_depth": failure(lambda: scad.make_box_rsolid(1, 1, -2)),
            "bad_tag": failure(lambda: scad.make_box_rsolid(1, 1, 1, bottom_face_tag="BAD TAG")),
            "bad_result_tag": failure(lambda: scad.make_box_rsolid(1, 1, 1, result_tag="Not Normal")),
        }
    """)


def test_box_rejects_non_finite_sizes_as_its_own_error():
    # The reference words the cause differently ("value must be finite"); the operation and
    # guidance are the same.
    with pytest.raises(scad.SimpleCADError) as info:
        scad.make_box_rsolid(float("nan"), 1, 1)
    assert info.value.operation == "make_box_rsolid"
    assert "must be a finite number" in info.value.to_dict()["technical_details"]


def test_box_rejects_unknown_keywords_like_python():
    with pytest.raises(TypeError):
        scad.make_box_rsolid(2.0, 3.0, 4.0, **{"name": "housing"})
    with pytest.raises(TypeError):
        scad.make_box_rsolid(2.0, 3.0, 4.0, **{"output_tags": {"box.top_front_edge": "role.edge"}})
    with pytest.raises(TypeError):
        scad.make_box_rsolid(2.0, 3.0, 4.0, (0, 0, 0), "positional_prefix")


def test_cylinder():
    parity("cylinder", """
        tagged = scad.make_cylinder_rsolid(
            2.0, 5.0, tag_prefix="shaft", result_tag="part.shaft", start_face_tag="role.base",
            end_face_tag="role.top", side_face_tag="role.skin", seam_edge_tag="role.seam",
            start_edge_tag="role.rim_a", end_edge_tag="role.rim_b",
        )
        result = {
            "plain": describe(scad.make_cylinder_rsolid(1.0, 2.0)),
            "sideways": describe(scad.make_cylinder_rsolid(1.5, 4.0, bottom_face_center=(1, 2, 3), axis=(1, 0, 0))),
            "tagged": describe(tagged),
            "alias": describe(scad.create_cylinder(0.5, 1.0)),
        }
    """)


def test_cone_and_frustum():
    parity("cone", """
        result = {
            "cone": describe(scad.make_cone_rsolid(2.0, 3.0)),
            "frustum": describe(scad.make_cone_rsolid(3.0, 4.0, 1.0)),
            "offset": describe(scad.make_cone_rsolid(1.5, 2.0, bottom_face_center=(2, 2, 0))),
            "horizontal": describe(scad.make_cone_rsolid(1.0, 3.0, axis=(1, 0, 0))),
            "tip": describe(scad.make_cone_rsolid(2.0, 4.0, tag_prefix="tip")),
            "adapter": describe(scad.make_cone_rsolid(
                2.0, 4.0, top_radius=1.0, tag_prefix="adapter", start_face_tag="anchor.base",
                end_face_tag="role.outlet", seam_edge_tag="role.seam", result_tag="part.adapter")),
        }
    """)


def test_cone_and_cylinder_failures():
    parity("axial_failures", """
        result = {
            "pointed_cone_end_tag": failure(lambda: scad.make_cone_rsolid(2.0, 4.0, end_face_tag="role.outlet")),
            "cone_height": failure(lambda: scad.make_cone_rsolid(2.0, 0.0)),
            "cylinder_radius": failure(lambda: scad.make_cylinder_rsolid(-1.0, 2.0)),
        }
    """)


def test_zero_axis_fails_as_the_operator():
    # The kernel's own complaint is worded differently from OCP's; the operation is not.
    with pytest.raises(scad.SimpleCADError) as info:
        scad.make_cylinder_rsolid(1.0, 2.0, axis=(0, 0, 0))
    assert info.value.operation == "make_cylinder_rsolid"


def test_sphere():
    parity("sphere", """
        result = {
            "unit": describe(scad.make_sphere_rsolid(1.0)),
            "offset": describe(scad.make_sphere_rsolid(2.5, center=(1, 2, 3))),
            "alias": describe(scad.create_sphere(0.5)),
            "zero": failure(lambda: scad.make_sphere_rsolid(0)),
        }
    """)

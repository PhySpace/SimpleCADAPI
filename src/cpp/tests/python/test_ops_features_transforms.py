"""translate / rotate / mirror / scale / transform and the patterns against the reference SDK."""

from ops_features_support import compare, parameter_names

import simplecadapi._cpp as scad

TAGGED_BOX = """
        box = scad.make_box_rsolid(2, 3, 4)
        top = ql.faces().where(ql.prop("geom.normal.z", ">", 0.9)).exactly(1).resolve(box)[0]
        top._apply_tag("role.top")
"""


def test_rigid_transforms_of_a_tagged_solid():
    compare("rigid_solid", TAGGED_BOX, """
        result = {
            "translate": describe(scad.translate_shape(box, (1, 2, 3))),
            "rotate": describe(scad.rotate_shape(box, 30, (0, 0, 1), (1, 0, 0))),
            "mirror": describe(scad.mirror_shape(box, (0, 0, 0), (1, 0, 0))),
            "rotate_zero_is_same": scad.rotate_shape(box, 0).same_topology(box),
        }
    """)


def test_transforms_of_other_shapes():
    compare("rigid_other", """
        face = scad.make_rectangle_rface(2, 1)
        wire = scad.make_rectangle_rwire(2, 1)
        def info(s):
            return {"kind": type(s).__name__, "center": centroid(s), "tags": tags_of(s)}
        result = {
            "translate_face": info(scad.translate_shape(face, (1, 2, 3))),
            "rotate_wire": info(scad.rotate_shape(wire, 90, (0, 0, 1))),
            "mirror_face": info(scad.mirror_shape(face, (0, 0, 1), (0, 0, 1))),
        }
    """)


def test_transforms_follow_the_workplane():
    compare("rigid_workplane", TAGGED_BOX, """
        with scad.SimpleWorkplane(origin=(5, 0, 0), normal=(1, 0, 0)):
            moved = scad.translate_shape(box, (0, 0, 1))
            turned = scad.rotate_shape(box, 90, (0, 0, 1))
        result = {"moved": describe(moved, detail=False), "turned": describe(turned, detail=False)}
    """)


def test_rigid_transform_errors():
    compare("rigid_errors", TAGGED_BOX, """
        result = {
            "mirror_zero": failure(lambda: scad.mirror_shape(box, (0, 0, 0), (0, 0, 0))),
            "translate": failure(lambda: scad.translate_shape(box, (float("inf"), 0, 0))),
            "rotate_axis": failure(lambda: scad.rotate_shape(box, 30, (0, 0, 0)), details=False),
        }
    """)


def test_scale_and_affine_transform():
    compare("affine", TAGGED_BOX, """
        original = scad.make_box_rsolid(width=10, height=12, depth=14)
        def raises(call):
            try:
                call()
            except Exception as e:
                return [type(e).__name__, str(e)]
        result = {
            "uniform": describe(scad.scale_rsolid(box, (2, 2, 2), (1, 1, 1)), detail=False),
            "nonuniform": describe(scad.scale_rsolid(original, (2, 3, 0.5), (5, 6, 7)), detail=False),
            "shear": describe(scad.transform_rsolid(original, [[1, 0.3, 0, 5], [0, 1, 0, 2], [0, 0, 1, 0], [0, 0, 0, 1]]), detail=False),
            "mirror_matrix": describe(scad.transform_rsolid(original, [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]), detail=False),
            "errors": [raises(lambda: scad.scale_rsolid(original, f)) for f in ((0, 1, 1), (float("nan"), 1, 1), (1, 2), (float("inf"), 1, 1))]
                      + [raises(lambda: scad.transform_rsolid(original, [[0] * 4 for _ in range(4)])),
                         raises(lambda: scad.transform_rsolid(original, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 1, 1]])),
                         raises(lambda: scad.transform_rsolid(original, [[1, 0, 0], [0, 1, 0], [0, 0, 1]]))],
        }
    """)


def test_patterns():
    compare("patterns", """
        small = scad.make_box_rsolid(0.5, 0.5, 0.5)
        arm = scad.make_box_rsolid(0.2, 0.2, 1.0, bottom_face_center=(2, 0, 0))
        linear = scad.linear_pattern_rsolidlist(small, (1, 0, 0), 5, 1.0)
        radial = scad.radial_pattern_rsolidlist(arm, (0, 0, 0), (0, 0, 1), 6, 360)
        def member(s):
            return {"center": centroid(s), "tags": tags_of(s), "geo": s.get_metadata("geo")["pattern"]}
        result = {"linear": [member(s) for s in linear], "radial": [member(s) for s in radial],
                  "errors": [failure(lambda: scad.linear_pattern_rsolidlist(small, (1, 0, 0), 0, 1.0)),
                             failure(lambda: scad.linear_pattern_rsolidlist(small, (1, 0, 0), 2, 0)),
                             failure(lambda: scad.linear_pattern_rsolidlist(small, (0, 0, 0), 2, 1)),
                             failure(lambda: scad.radial_pattern_rsolidlist(arm, (0, 0, 0), (0, 0, 1), 0, 90)),
                             failure(lambda: scad.radial_pattern_rsolidlist(arm, (0, 0, 0), (0, 0, 1), 3, 0))]}
    """)


def test_signatures_match_python():
    expected = {
        "translate_shape": ["shape", "vector"],
        "rotate_shape": ["shape", "angle", "axis", "origin"],
        "mirror_shape": ["shape", "plane_origin", "plane_normal"],
        "scale_rsolid": ["solid", "factors", "center"],
        "transform_rsolid": ["solid", "matrix"],
        "linear_pattern_rsolidlist": ["shape", "direction", "count", "spacing"],
        "radial_pattern_rsolidlist": ["shape", "center", "axis", "count", "total_rotation_angle"],
    }
    for name, params in expected.items():
        assert parameter_names(getattr(scad, name)) == params, name


def test_user_tags_follow_the_solid_through_operators():
    # A tag applied through apply_tag_rselection on a solid, then every operator that consumes it: the
    # per-face tags the operators write (kernel roles) must agree with the reference.
    compare("tag_projection", """
        box = scad.make_box_rsolid(10, 10, 10)
        box = scad.apply_tag_rselection(box, ql.faces().where(ql.prop("geom.normal.z", ">", 0.9)).exactly(1), "role.top")
        top_edges = [e for e in edges_of(box) if abs(e.get_center().z - 10) < 1e-6]
        result = {
            "translate": describe(scad.translate_shape(box, (1, 2, 3))),
            "rotate": describe(scad.rotate_shape(box, 30, (0, 0, 1))),
            "mirror": describe(scad.mirror_shape(box, (0, 0, 0), (1, 0, 0))),
            "fillet": describe(scad.fillet_rsolid(box, top_edges, 1.0)),
            "chamfer": describe(scad.chamfer_rsolid(box, top_edges, 1.0)),
            "shell": describe(scad.shell_rsolid(box, [faces_of(box)[0]], 1.0)),
            "cut": describe(scad.cut_rsolid(box, scad.make_cylinder_rsolid(2, 30, bottom_face_center=(0, 0, -5)))),
            "union": describe(scad.union_rsolid(box, scad.make_box_rsolid(2, 2, 2, bottom_face_center=(0, 0, 10)))),
        }
    """)

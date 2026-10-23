"""union / cut / intersect, the set boolean and the 2D booleans against the reference SDK."""

from ops_features_support import compare, parameter_names

import simplecadapi._cpp as scad


def test_union_overlap_keeps_tags_of_both_operands():
    compare("union_overlap", """
        a = scad.make_box_rsolid(2, 2, 2)
        b = scad.make_box_rsolid(1, 1, 3, bottom_face_center=(0.5, 0.5, 0))
        a._apply_tag("role.a")
        faces_of(a)[0]._apply_tag("role.a_face")
        result = {"nested": describe(scad.union_rsolid([a, b])), "variadic": describe(scad.union_rsolid(a, b), detail=False),
                  "graph": describe(scad.union_rsolid(a, b, tracking_policy="graph"), detail=False),
                  "single": describe(scad.union_rsolid(a), detail=False),
                  "single_unclean": scad.union_rsolid(a, clean=False).same_topology(a)}
    """)


def test_union_contact_tolerance_and_glue():
    compare("union_contact", """
        left = scad.make_box_rsolid(1, 1, 1)
        touching = scad.make_box_rsolid(1, 1, 1, bottom_face_center=(1.0, 0, 0))
        gap = scad.make_box_rsolid(1, 1, 1, bottom_face_center=(1.0001, 0, 0))
        spheres = [scad.make_sphere_rsolid(radius=5.0, center=(x, 0, 0)) for x in (0.0, 9.0)]
        result = {
            "touching": describe(scad.union_rsolid(left, touching)),
            "gap_fails": failure(lambda: scad.union_rsolid(left, gap, glue=False)),
            "gap_tol": describe(scad.union_rsolid(left, gap, glue=False, tol=0.0001), detail=False),
            "glue": describe(scad.union_rsolid(*spheres, glue=True), detail=False),
            "bad_tol": [failure(lambda: scad.union_rsolid(left, touching, tol=t)) for t in (-1.0, float("nan"), float("inf"))],
        }
    """)


def test_union_failures_are_diagnosed():
    compare("union_failures", """
        base = scad.make_box_rsolid(10, 4, 4)
        far = scad.make_box_rsolid(2, 4, 4, bottom_face_center=(20, 0, 0))
        box1 = scad.make_box_rsolid(2, 2, 2)
        box2 = scad.make_box_rsolid(2, 2, 2, bottom_face_center=(2, 2, 0))
        tiny = [scad.make_box_rsolid(1, 1, 1, bottom_face_center=p) for p in ((0, 0, 0), (5, 0, 0), (0, 5, 0))]
        b = scad.make_box_rsolid(10, 4, 4, bottom_face_center=(3, 0, 0))
        spheres = [scad.make_sphere_rsolid(radius=5.0, center=(x, 0, 0)) for x in (0.0, 10.0)]
        result = {
            "disjoint": failure(lambda: scad.union_rsolid(base, far)),
            "edge_contact": failure(lambda: scad.union_rsolid(box1, box2)),
            "nearest_pair": failure(lambda: scad.union_rsolid(*tiny)),
            "cluster": failure(lambda: scad.union_rsolid(base, b, far)),
            "tangent": failure(lambda: scad.union_rsolid(*spheres, glue=True, tol=0.1)),
            "not_solid": failure(lambda: scad.union_rsolid(base, 3)),
            "empty": failure(lambda: scad.union_rsolid()),
        }
    """)


def test_cut_and_intersect():
    compare("cut_intersect", """
        box = scad.make_box_rsolid(10, 20, 30)
        hole = scad.make_cylinder_rsolid(4, 40)
        small = scad.make_box_rsolid(2, 2, 2, bottom_face_center=(0, 0, 5))
        far = scad.make_box_rsolid(2, 4, 4, bottom_face_center=(50, 0, 0))
        faces_of(box)[0]._apply_tag("role.kept")
        result = {
            "cut": describe(scad.cut_rsolid(box, hole)),
            "cut_two": describe(scad.cut_rsolid(box, [hole, small]), detail=False),
            "graph": describe(scad.cut_rsolid(box, hole, tracking_policy="graph"), detail=False),
            "skip": describe(scad.cut_rsolid(box, far), detail=False),
            "single_is_same": scad.cut_rsolid(box).same_topology(box),
            "intersect": describe(scad.intersect_rsolid(box, hole)),
            "strict": failure(lambda: scad.cut_rsolid(box, far, skip_non_intersecting=False)),
            "intersect_disjoint": failure(lambda: scad.intersect_rsolid(box, far)),
            "cut_not_solid": failure(lambda: scad.cut_rsolid(box, "x")),
        }
    """)


def test_boolean_rsolidlist_keeps_every_piece():
    compare("boolean_list", """
        base = scad.make_box_rsolid(10, 2, 2)
        tool = scad.make_box_rsolid(2, 4, 4, bottom_face_center=(0, 0, -1))
        left = [scad.make_box_rsolid(2, 2, 2, bottom_face_center=(x, 0, 0)) for x in (-4, 4)]
        right = [scad.make_box_rsolid(1, 4, 4, bottom_face_center=(x, 0, -1)) for x in (-4, 4)]
        def volumes(items): return sorted(round(s.get_volume(), 6) for s in items)
        def raises(call):
            try:
                call()
            except Exception as e:
                return [type(e).__name__, str(e)]
        result = {
            "pieces": volumes(scad.boolean_rsolidlist(left=[base], right=[tool], operation="cut")),
            "cut": volumes(scad.boolean_rsolidlist(left=left, right=right, operation="cut")),
            "intersect": volumes(scad.boolean_rsolidlist(left=left, right=right, operation="intersect")),
            "union": volumes(scad.boolean_rsolidlist(left=left, right=right, operation="union")),
            "nothing": scad.boolean_rsolidlist(left=[base], right=[base], operation="cut"),
            "errors": [raises(lambda: scad.boolean_rsolidlist([base], [tool], "xor")),
                       raises(lambda: scad.boolean_rsolidlist([base, 1], [tool], "cut"))],
        }
    """)


def test_2d_booleans():
    compare("booleans_2d", """
        a = scad.make_rectangle_rface(4, 4)
        b = scad.make_rectangle_rface(2, 2, center=(1, 1, 0))
        inner = scad.make_rectangle_rface(1, 1)
        def info(face):
            return {"area": face.get_area(), "tags": tags_of(face), "wires": len(ql.wires().resolve(face))}
        result = {
            "cut": info(scad.make_2d_cut_rface(a, b)), "hole": info(scad.make_2d_cut_rface(a, inner)),
            "union": info(scad.make_2d_union_rface(a, b)), "intersect": info(scad.make_2d_intersect_rface(a, b)),
            "errors": [failure(lambda: scad.make_2d_cut_rface(a, 1)), failure(lambda: scad.make_2d_union_rface(1, a)),
                       failure(lambda: scad.make_2d_intersect_rface(a, scad.make_rectangle_rface(1, 1, center=(9, 9, 0))))],
        }
    """)


def test_signatures_match_python():
    assert parameter_names(scad.union_rsolid) == ["solids", "clean", "glue", "tol", "tracking_policy"]  # *solids
    assert parameter_names(scad.cut_rsolid) == ["solids", "skip_non_intersecting", "tracking_policy"]  # *solids
    assert parameter_names(scad.boolean_rsolidlist) == ["left", "right", "operation"]

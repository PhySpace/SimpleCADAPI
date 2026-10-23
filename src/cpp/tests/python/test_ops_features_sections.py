"""loft, sweep, twisted / helical / multi-section sweeps, taper and extrude-until against the reference SDK."""

import pytest
from ops_features_support import compare, parameter_names

import simplecadapi._cpp as scad


def test_loft_with_tags_and_policies():
    compare("loft", """
        r1 = scad.make_rectangle_rwire(4, 4)
        r2 = scad.make_rectangle_rwire(2, 2, center=(0, 0, 3))
        r3 = scad.make_rectangle_rwire(1, 1, center=(0, 0, 5))
        tip = scad.make_point_rvertex(0, 0, 6)
        result = {
            "plain": describe(scad.loft_rsolid([r1, r2])),
            "ruled3": describe(scad.loft_rsolid([r1, r2, r3], ruled=True), detail=False),
            "tags": describe(scad.loft_rsolid([r1, r2], tag_prefix="body", result_tag="role.loft", start_face_tag="role.s",
                                              end_face_tag="role.e", side_faces_tag="role.sides")),
            "graph": describe(scad.loft_rsolid([r1, r2, r3], tracking_policy="graph"), detail=False),
            "cone": describe(scad.loft_rsolid([r1, tip]), detail=False),
        }
    """)


def test_loft_errors_are_diagnosed():
    compare("loft_errors", """
        rect = scad.make_rectangle_rwire(4.0, 4.0)
        open_u = scad.make_wire_from_edges_rwire([
            scad.make_line_redge((0, 0, 0), (10, 0, 0)), scad.make_line_redge((10, 0, 0), (10, 6, 0)),
            scad.make_line_redge((10, 6, 0), (0, 6, 0)), scad.make_line_redge((0, 6, 0), (0, 0.8, 0))])
        tip = scad.make_point_rvertex(0, 0, 6)
        up = scad.make_rectangle_rwire(4.0, 4.0, center=(0, 0, 2))
        def raises(call):
            try:
                call()
            except Exception as e:
                return [type(e).__name__, str(e)]
        result = {
            "coincident": failure(lambda: scad.loft_rsolid([rect, scad.make_rectangle_rwire(4.0, 4.0)])),
            "open": failure(lambda: scad.loft_rsolid([rect, open_u])),
            "order": failure(lambda: scad.loft_rsolid([rect, scad.make_rectangle_rwire(4, 4, center=(0, 0, 4)), up])),
            "one": failure(lambda: scad.loft_rsolid([rect])),
            "vertex_tag": failure(lambda: scad.loft_rsolid([tip, rect], start_face_tag="role.s")),
            "graph_tag": failure(lambda: scad.loft_rsolid([rect, up], tracking_policy="graph", tag_prefix="x")),
            "bad_policy": failure(lambda: scad.loft_rsolid([rect, up], tracking_policy="bogus")),
        }
    """)


def test_sweep_and_twisted_sweep():
    compare("sweeps", """
        profile = scad.make_circle_rface((0, 0, 0), 1.0)
        path = scad.make_wire_from_edges_rwire([scad.make_line_redge((0, 0, 0), (0, 0, 5)),
                                                scad.make_line_redge((0, 0, 5), (3, 0, 8))])
        square = scad.make_rectangle_rface(2, 1)
        result = {
            "sweep": describe(scad.sweep_rsolid(profile, path, tag_prefix="pipe", start_face_tag="role.s", end_face_tag="role.e")),
            "frenet": describe(scad.sweep_rsolid(profile, path, is_frenet=True), detail=False),
            "twisted": describe(scad.twisted_sweep_rsolid(square, 4.0, 90.0, tag_prefix="twist", side_faces_tag="role.sides"), detail=False),
            "twisted_axis": describe(scad.twisted_sweep_rsolid(scad.make_rectangle_rface(2, 1, center=(0, 0, 1)), 3.0, -45.0, axis=(0, 0, 1), origin=(0, 0, 1), guide_radius=2.0), detail=False),
            "errors": [failure(lambda: scad.twisted_sweep_rsolid(square, 0, 10)), failure(lambda: scad.twisted_sweep_rsolid(square, 1, 10, axis=(0, 0, 0))),
                       failure(lambda: scad.twisted_sweep_rsolid(profile.get_outer_wire(), 1, 10))],
        }
    """)


def test_helical_sweep():
    compare("helical", """
        profile = scad.make_wire_from_edges_rwire([scad.make_circle_redge((3.4, 0.0, 0.0), 0.3)])
        right = scad.helical_sweep_rsolid(profile, pitch=2.0, height=6.0, radius=3.0, handedness="Right")
        left = scad.helical_sweep_rsolid(profile, pitch=2.0, height=6.0, radius=3.0, handedness="Left")
        result = {"right": describe(right, detail=False), "left_volume": left.get_volume(),
                  "errors": [failure(lambda: scad.helical_sweep_rsolid(profile, 0, 6.0, 3.0)),
                             failure(lambda: scad.helical_sweep_rsolid(profile, 2.0, -1, 3.0))]}
    """, rel=1e-5)


def test_taper_multisection_and_until():
    compare("sections_misc", """
        face = scad.make_rectangle_rface(4, 4)
        ring = scad.make_face_from_wires_rface(scad.make_rectangle_rwire(6, 6), [scad.make_rectangle_rwire(2, 2)])
        path = scad.make_segment_rwire((0, 0, 0), (0, 0, 6))
        wires = [scad.make_rectangle_rwire(4, 4), scad.make_rectangle_rwire(2, 2, center=(0, 0, 6))]
        ceiling = scad.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 5))
        upper = scad.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 10))
        sphere = scad.make_sphere_rsolid(5, center=(0, 0, 10))
        small = scad.make_rectangle_rface(2, 2)
        def raises(call):
            try:
                call()
            except Exception as e:
                return [type(e).__name__, str(e)]
        result = {
            "taper": [describe(scad.extrude_taper_rsolid(face, (0, 0, 3), a), detail=False) for a in (0, 10, -10)],
            "taper_ring": [describe(scad.extrude_taper_rsolid(ring, (0, 0, 2), 5, flip_inner=f), detail=False) for f in (True, False)],
            "taper_errors": [raises(lambda: scad.extrude_taper_rsolid(face, (0, 0, 0), 5)), raises(lambda: scad.extrude_taper_rsolid(face, (0, 0, 1), 90))],
            "multisection": describe(scad.sweep_multisection_rsolid(wires, path), detail=False),
            "multisection_binormal": describe(scad.sweep_multisection_rsolid(wires, path, binormal=(1, 0, 0)), detail=False),
            "multisection_errors": [raises(lambda: scad.sweep_multisection_rsolid(wires[:1], path))],
            "until": {mode: describe(scad.extrude_until_rsolid(small, ceiling, until=mode), detail=False) for mode in ("NEXT", "LAST")},
            "until_multi": [scad.extrude_until_rsolid(small, [upper, ceiling], until=m).get_volume() for m in ("NEXT", "LAST")],
            "until_curved": describe(scad.extrude_until_rsolid(small, sphere), detail=False),
            "until_reverse": [scad.extrude_until_rsolid(scad.make_rectangle_rface(2, 2, center=(0, 0, 10)), scad.make_box_rsolid(10, 10, 2), until=m).get_volume() for m in ("PREVIOUS", "FIRST")],
            "until_errors": [raises(lambda: scad.extrude_until_rsolid(small, scad.make_box_rsolid(2, 2, 2, bottom_face_center=(20, 0, 5)))),
                             raises(lambda: scad.extrude_until_rsolid(small, ceiling, direction=(0, 0, 0))),
                             raises(lambda: scad.extrude_until_rsolid(small, ceiling, until="UNKNOWN")),
                             raises(lambda: scad.extrude_until_rsolid(small, [])),
                             raises(lambda: scad.extrude_until_rsolid(scad.make_rectangle_rface(4, 4), scad.make_box_rsolid(2, 2, 2, bottom_face_center=(0, 0, 5))))],
        }
    """, rel=1e-5)


def test_signatures_match_python():
    expected = {
        "loft_rsolid": ["profiles", "ruled", "tracking_policy", "tag_prefix", "result_tag", "start_face_tag", "end_face_tag", "side_faces_tag"],
        "sweep_rsolid": ["profile", "path", "is_frenet", "tag_prefix", "result_tag", "start_face_tag", "end_face_tag", "side_faces_tag"],
        "twisted_sweep_rsolid": ["profile", "distance", "twist_angle", "axis", "origin", "guide_radius", "tag_prefix", "result_tag",
                                 "start_face_tag", "end_face_tag", "side_faces_tag"],
        "helical_sweep_rsolid": ["profile", "pitch", "height", "radius", "center", "dir", "handedness"],
        "extrude_taper_rsolid": ["profile", "vector", "taper", "flip_inner"],
        "sweep_multisection_rsolid": ["profiles", "path", "is_frenet", "binormal"],
        "extrude_until_rsolid": ["profile", "target", "direction", "until"],
    }
    for name, params in expected.items():
        assert parameter_names(getattr(scad, name)) == params, name


def test_tracking_policy_enum_and_scope():
    assert scad.TrackingPolicy.GRAPH == "graph"
    rect = scad.make_rectangle_rwire(4, 4)
    up = scad.make_rectangle_rwire(2, 2, center=(0, 0, 3))
    assert scad.loft_rsolid([rect, up], tracking_policy=scad.TrackingPolicy.GRAPH).get_volume() == pytest.approx(28.0)
    with scad.tracking_policy_scope(scad.TrackingPolicy.GRAPH):
        assert scad.current_tracking_policy() == "graph"
        # the surrounding scope wins over the argument
        assert scad.loft_rsolid([rect, up], tracking_policy="full").get_volume() == pytest.approx(28.0)
    assert scad.current_tracking_policy() == "full"


def test_failure_diagnoses_are_callable_from_python():
    box = scad.make_box_rsolid(10, 10, 10)
    edges = scad.ql.edges().resolve(box)
    diagnosis = scad.diagnose_blend_failure(box, [edges[0]], size_value=12.0, operation_kind="fillet")
    assert diagnosis.failure_kind == "size_exceeds_face"
    assert {m["name"] for m in diagnosis.measurements} >= {"radius", "available_face_room"}
    far = scad.make_box_rsolid(2, 4, 4, bottom_face_center=(20, 0, 0))
    gap = scad.diagnose_boolean_failure([box, far], effective_tol=1e-6)
    assert gap.failure_kind == "disjoint"
    with pytest.raises(scad.SimpleCADError):
        scad.raise_loft_failure_if_diagnosed([scad.make_rectangle_rwire(4, 4)] * 2, "loft_rsolid")
    scad.assert_blend_volume_monotonic(box, box, operation="fillet_rsolid", operation_kind="fillet", size_value=1.0, edges=[edges[0]])

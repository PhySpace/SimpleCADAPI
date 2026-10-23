"""fillet, chamfer, shell, offset and draft against the reference SDK (and its blend diagnoses)."""

import pytest
from ops_features_support import compare, parameter_names

import simplecadapi._cpp as scad

BOX = """
        box = scad.make_box_rsolid(10, 10, 10)
        top = ql.faces().where(ql.prop("geom.normal.z", ">", 0.9)).exactly(1).resolve(box)[0]
        top._apply_tag("role.top")
        top_edges = [e for e in edges_of(box) if abs(e.get_center().z - 10) < 1e-6]
"""


def test_fillet_projects_tags_and_names_patches():
    compare("fillet_tags", BOX, """
        out = scad.fillet_rsolid(box, top_edges, 1.0, result_tag="role.rounded", generated_faces_tag="role.patch")
        result = describe(out)
    """)


def test_fillet_with_a_selector():
    compare("fillet_selector", BOX, """
        out = scad.fillet_rsolid(box, ql.edges().where(ql.prop("geom.center.z", ">", 9.9)), 2.0)
        result = describe(out, detail=False)
    """)


def test_chamfer_symmetric_and_angled():
    compare("chamfer", BOX, """
        selector = ql.edges().where(ql.and_(ql.curve_type("LINE"), ql.prop("geom.center.z", ">", 9.999),
                                            ql.prop("geom.center.y", "<", -4.999))).exactly(1)
        plain = scad.chamfer_rsolid(box, selector, 1.0, generated_faces_tag="role.bevel")
        angled = [scad.chamfer_rsolid(box, selector, 1.0, angle=a, reference_direction=(0, 0, 1)) for a in (15.0, 30.0, 75.0)]
        result = {"plain": describe(plain), "angled": [describe(s, detail=False) for s in angled],
                  "bad_angle": [failure(lambda: scad.chamfer_rsolid(box, selector, 1.0, angle=a, reference_direction=(0, 0, 1)))
                                for a in (0.0, 90.0)],
                  "no_reference": failure(lambda: scad.chamfer_rsolid(box, selector, 1.0, angle=30.0))}
    """)


def test_shell_roles():
    compare("shell", BOX, """
        out = scad.shell_rsolid(box, [top], 1.0, result_tag="role.cup", offset_faces_tag="role.inner", closing_faces_tag="role.rim", wall_edges_tag="role.wall")
        result = describe(out)
    """)


def test_blend_failure_diagnoses():
    compare("blend_failures", """
        box = scad.make_box_rsolid(10, 10, 10)
        edges = edges_of(box)
        slot = scad.extrude_rsolid(scad.make_face_from_wire_rface(scad.make_wire_from_edges_rwire([
            scad.make_three_point_arc_redge((0, 5, 0), (-5, 0, 0), (0, -5, 0)),
            scad.make_segment_redge((0, -5, 0), (20, -5, 0)),
            scad.make_three_point_arc_redge((20, -5, 0), (25, 0, 0), (20, 5, 0)),
            scad.make_segment_redge((20, 5, 0), (0, 5, 0))])), (0, 0, 1), 8)
        junction = [e for e in edges_of(slot)
                    if abs((e.get_start_vertex().get_coordinates()[0] + e.get_end_vertex().get_coordinates()[0]) / 2) < 1e-6
                    and abs((e.get_start_vertex().get_coordinates()[1] + e.get_end_vertex().get_coordinates()[1]) / 2 - 5) < 1e-6][0]
        tube = scad.cut_rsolid(scad.make_cylinder_rsolid(10, 10), scad.make_cylinder_rsolid(4, 20, bottom_face_center=(0, 0, -5)))
        mouth = [e for e in edges_of(tube) if abs(e.get_start_vertex().get_coordinates()[2] - e.get_end_vertex().get_coordinates()[2]) < 1e-6
                 and e.get_start_vertex().get_coordinates()[2] > 9.0]
        result = {
            "chamfer_room": failure(lambda: scad.chamfer_rsolid(box, [edges[0]], 12)),
            "fillet_room": failure(lambda: scad.fillet_rsolid(box, [edges[0]], 12)),
            "tangent": failure(lambda: scad.fillet_rsolid(slot, [junction], 1.0)),
            "critical": failure(lambda: scad.fillet_rsolid(box, edges, 5)),
            "bore_mouth": failure(lambda: scad.fillet_rsolid(tube, mouth, 6)),
            "garbage": failure(lambda: scad.fillet_rsolid(box, edges, 6)),
            "radius": failure(lambda: scad.fillet_rsolid(box, edges, -1)),
            "no_edges": failure(lambda: scad.fillet_rsolid(box, [], 1)),
            "shell": failure(lambda: scad.shell_rsolid(box, [], 1)),
            "shell_role": failure(lambda: scad.shell_rsolid(box, [ql.faces().resolve(box)[0]], 1, body_faces_tag="role.body")),
        }
    """)


def test_offset_and_draft():
    compare("offset_draft", """
        box = scad.make_box_rsolid(10, 12, 14)
        up = ql.faces().where(ql.prop("geom.normal.z", ">", 0.9)).exactly(1)
        right = ql.faces().where(ql.prop("geom.normal.x", ">", 0.9)).exactly(1)
        result = {
            "grown": describe(scad.offset_rsolid(box, 1.0), detail=False),
            "open_in": describe(scad.offset_rsolid(box, -1.0, up), detail=False),
            "open_out": describe(scad.offset_rsolid(box, 1.0, up, kind="INTERSECTION"), detail=False),
            "drafts": [describe(scad.draft_rsolid(box, right, a), detail=False) for a in (10, -10, 0)],
            "draft_plane": describe(scad.draft_rsolid(box, right, 5, plane_origin=(0, 0, 7)), detail=False),
        }
        def raises(call):
            try:
                call()
            except Exception as e:
                return [type(e).__name__, str(e)]
        other = scad.make_box_rsolid(1, 1, 1, bottom_face_center=(20, 0, 0))
        result["errors"] = [
            raises(lambda: scad.offset_rsolid(box, 0)), raises(lambda: scad.offset_rsolid(box, 1, tolerance=0)),
            raises(lambda: scad.offset_rsolid(box, 1, kind="X")),
            raises(lambda: scad.draft_rsolid(box, [], 5)), raises(lambda: scad.draft_rsolid(box, right, 90)),
            raises(lambda: scad.draft_rsolid(box, right, 5, plane_normal=(0, 0, 0))),
            raises(lambda: scad.draft_rsolid(box, ql.faces().where(ql.prop("geom.normal.x", ">", 0.9)).resolve(other), 5)),
        ]
    """)


def test_signatures_match_python():
    expected = {
        "fillet_rsolid": ["solid", "edges", "radius", "result_tag", "generated_faces_tag"],
        "chamfer_rsolid": ["solid", "edges", "distance", "angle", "reference_direction", "result_tag", "generated_faces_tag"],
        "shell_rsolid": ["solid", "faces_to_remove", "thickness", "result_tag", "body_faces_tag", "offset_faces_tag",
                         "closing_faces_tag", "wall_edges_tag"],
        "offset_rsolid": ["solid", "amount", "openings", "tolerance", "kind"],
        "draft_rsolid": ["solid", "faces_to_draft", "angle", "plane_origin", "plane_normal"],
    }
    for name, params in expected.items():
        assert parameter_names(getattr(scad, name)) == params, name

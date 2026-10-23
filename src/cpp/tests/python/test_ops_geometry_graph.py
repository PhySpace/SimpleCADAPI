"""What the geometry operators record in a GraphSession, and that an edit reruns them."""

import pytest

import simplecadapi._cpp as scad
from ops_geometry_support import parity

FACTS = """
def graph_facts(session):
    # Tag assignments carry random binding ids and graph ids: only the tag they assign is compared.
    facts = []
    for n in session.graph.nodes:
        if n.op == "apply_tag_rselection":
            facts.append({"op": n.op, "tag": n.params["tag_binding"]["tag"]})
        else:
            facts.append({"op": n.op, "params": n.params, "param_exprs": n.param_exprs,
                          "inputs": [getattr(i, "node_id", i) for i in (n.inputs or ())]})
    return facts
"""


def test_profile_makers_record_their_parts():
    # test_original_api_integration.py: one user-level node per part (edge + wire for a circle).
    parity("graph_profiles", prelude=FACTS, source="""
        with scad.GraphSession() as session:
            circle = scad.make_circle_rwire((0, 0, 0), 2.0)
            rect = scad.make_rectangle_rface(2.0, 1.0)
            tri = scad.make_polyline_rwire([(0, 0, 0), (1, 0, 0), (1, 1, 0)], closed=True)
            arc = scad.make_three_point_arc_rwire((0, 0, 0), (1, 1, 0), (2, 0, 0))
            seg = scad.make_segment_rwire((0, 0, 0), (0, 0, 3))
            ring = scad.make_face_from_wires_rface(circle, [scad.make_circle_rwire((0, 0, 0), 1.0)])
        result = {"graph": graph_facts(session), "circle": describe(circle), "rect": describe(rect),
                  "tri": describe(tri), "ring": describe(ring), "seg": describe(seg), "arc": describe(arc)}
    """)


def test_primitives_and_curves_record_their_parameters():
    parity("graph_primitives", prelude=FACTS, source="""
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(2.0, 3.0, 4.0, tag_prefix="housing", bottom_face_tag="anchor.base", result_tag="part.housing")
            cyl = scad.make_cylinder_rsolid(2.0, 5.0, tag_prefix="shaft", seam_edge_tag="role.seam")
            cone = scad.make_cone_rsolid(2.0, 4.0, top_radius=1.0)
            ball = scad.make_sphere_rsolid(1.5, center=(1, 2, 3))
            point = scad.make_point_rvertex(1, 2, 3)
            ellipse = scad.make_ellipse_rwire((0, 0, 0), 3.0, 1.0, major_direction=(0, 1, 0), tag_prefix="e")
            helix = scad.make_helix_rwire(2.0, 6.0, 3.0, handedness="Left")
            spline = scad.make_spline_rwire(control_points=[(0, 0, 0), (1, 1, 0), (2, 1, 0), (3, 0, 0)], weights=[1, 2, 2, 1])
            loop = scad.make_periodic_spline_rwire(points=[(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)])
            arc = scad.make_angle_arc_rwire((0, 0, 0), 1.0, 0.0, 1.5)
        result = {"graph": graph_facts(session), "box": describe(box), "cyl": describe(cyl), "cone": describe(cone),
                  "ball": describe(ball), "point": describe(point), "ellipse": describe(ellipse), "helix": describe(helix),
                  "spline": describe(spline), "loop": describe(loop), "arc": describe(arc)}
    """, rel=1e-4)


def test_symbolic_arguments_are_recorded_as_expressions():
    # The rectangle's corners are expressions of its width and center, exactly the reference's.
    parity("graph_symbolic", prelude=FACTS, source="""
        w = scad.var("w", 10.0)
        h = scad.var("h", 4.0)
        with scad.GraphSession() as session:
            rect = scad.make_rectangle_rface(w, h, center=(1, w, 0))
            box = scad.make_box_rsolid(w, 2, h * 0.5, bottom_face_center=(0, 0, w))
            spline = scad.make_spline_rwire(control_points=[(0, 0, 0), (1, w, 0), (2, 1, 0), (3, 0, 0)], weights=[1, h, 1, 1])
            ball = scad.make_sphere_rsolid(w)
            arc = scad.make_angle_arc_redge((0, 0, 0), w, 0.0, h)
        result = {"graph": graph_facts(session), "rect": describe(rect), "box": describe(box), "ball": describe(ball)}
    """)


@pytest.fixture
def parametric_model():
    w = scad.var("w", 10.0)
    h = scad.var("h", 4.0)
    with scad.GraphSession() as session:
        box = scad.make_box_rsolid(w, 2.0, h)
        rect = scad.make_rectangle_rface(w, h, center=(0, 0, w))
        ring = scad.make_circle_rface((0, 0, 0), w)
        cyl = scad.make_cylinder_rsolid(h, w)
        cone = scad.make_cone_rsolid(w, h, top_radius=h / 2)
        ball = scad.make_sphere_rsolid(w, center=(w, 0, 0))
        spline = scad.make_interpolated_spline_rwire(points=[(0, 0, 0), (w, 1, 0), (2 * w, 0, 0)])
        helix = scad.make_helix_rwire(h, w * 2, h)
    return session, {"box": box, "rect": rect, "ring": ring, "cyl": cyl, "cone": cone, "ball": ball, "spline": spline, "helix": helix}


def test_a_parameter_edit_reruns_the_operators(parametric_model):
    session, shapes = parametric_model
    before = {name: shape for name, shape in shapes.items()}
    assert session.current(before["box"]).get_volume() == pytest.approx(10 * 2 * 4)

    session.set_var("w", 20.0)
    report = session.recompute()
    assert report.ok, report.failed
    assert session.current(before["box"]).get_volume() == pytest.approx(20 * 2 * 4)
    assert session.current(before["rect"]).get_area() == pytest.approx(20 * 4)
    assert session.current(before["ring"]).get_area() == pytest.approx(3.141592653589793 * 400)
    assert session.current(before["cyl"]).get_volume() == pytest.approx(3.141592653589793 * 16 * 20)
    assert session.current(before["ball"]).get_volume() == pytest.approx(4 / 3 * 3.141592653589793 * 8000)
    assert session.current(before["ball"]).get_center().x == pytest.approx(20.0)
    assert session.current(before["spline"]).edges()[0].get_length() > 40

    session.set_var("h", 2.0)
    assert session.recompute().ok
    assert session.current(before["box"]).get_volume() == pytest.approx(20 * 2 * 2)
    cone = session.current(before["cone"])
    assert cone.get_volume() == pytest.approx(3.141592653589793 * 2 / 3 * (400 + 20 * 1 + 1))


def test_an_edit_that_breaks_an_operator_fails_that_node_only(parametric_model):
    session, shapes = parametric_model
    session.set_var("h", -1.0)
    report = session.recompute()
    assert not report.ok
    failed = {failure.op for failure in report.failed}
    assert "make_box_rsolid" in failed and "make_cylinder_rsolid" in failed
    # What does not depend on `h` is untouched.
    assert session.current(shapes["ring"]).get_area() == pytest.approx(3.141592653589793 * 100)
    error = next(f for f in report.failed if f.op == "make_box_rsolid")
    assert "make_box_rsolid" in error.message


def test_non_session_calls_record_nothing():
    wire = scad.make_circle_rwire((0, 0, 0), 2.0)
    assert wire.get_metadata("track")["op"] == "make_circle_wire"
    with scad.GraphSession() as session:
        scad.make_circle_rwire((0, 0, 0), 2.0)
    assert [n.op for n in session.graph.nodes] == ["make_circle_redge", "make_wire_from_edges_rwire"]

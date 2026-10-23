"""The corpus: one function per scenario, each records a small model inside a GraphSession.

A scenario takes the `simplecadapi` module `s` and the `ql` module and builds geometry;
the harness (record.py) wraps it in a GraphSession and exports the model JSON.  Scenario
names are `<family>_<case>`; the family is the row of the per-operator table.
"""

from __future__ import annotations

SCENARIOS = {}


def scenario(fn):
    SCENARIOS[fn.__name__] = fn
    return fn


def _box(s, w=20, h=20, d=10):
    return s.make_box_rsolid(w, h, d)


def _top_face(s, ql):
    return ql.faces().where(ql.prop("geom.normal.z", ">", 0.9))


# ---- primitives / curves ---------------------------------------------------------------
@scenario
def prim_box(s, ql):
    _box(s)


@scenario
def prim_solids(s, ql):
    s.make_cylinder_rsolid(3, 10)
    s.make_cone_rsolid(4, 2, 8)
    s.make_sphere_rsolid(5)


@scenario
def prim_tagged_box(s, ql):
    s.make_box_rsolid(10, 10, 10, tag_prefix="blk")


@scenario
def curve_edges(s, ql):
    s.make_line_redge((0, 0, 0), (5, 0, 0))
    s.make_circle_redge((0, 0, 0), 3)
    s.make_three_point_arc_redge((0, 0, 0), (1, 1, 0), (2, 0, 0))
    s.make_angle_arc_redge((0, 0, 0), 3, 0, 90)
    s.make_spline_redge(control_points=[(0, 0, 0), (1, 2, 0), (3, 1, 0), (4, 0, 0)])
    s.make_ellipse_redge((0, 0, 0), 4, 2)


@scenario
def curve_wires_faces(s, ql):
    s.make_rectangle_rwire(4, 3)
    s.make_circle_rwire((0, 0, 0), 2)
    s.make_polyline_rwire([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], True)
    s.make_rectangle_rface(4, 3)
    s.make_circle_rface((0, 0, 0), 2)
    s.make_segment_rwire((0, 0, 0), (3, 0, 0))


@scenario
def curve_helix_vertex(s, ql):
    s.make_helix_redge(2.0, 10.0, 3.0)
    s.make_point_rvertex(1, 2, 3)


# ---- features with selections -----------------------------------------------------------
@scenario
def fillet_all_edges(s, ql):
    b = _box(s)
    s.fillet_rsolid(b, ql.edges(), 1.0)


@scenario
def fillet_explicit_edges(s, ql):
    b = _box(s)
    s.fillet_rsolid(b, [b.get_edges(0), b.get_edges(1)], 1.0)


@scenario
def fillet_tags(s, ql):
    b = _box(s)
    s.fillet_rsolid(b, ql.edges().take(4), 0.5, result_tag="rounded", generated_faces_tag="blend")


@scenario
def chamfer_selector(s, ql):
    b = _box(s)
    s.chamfer_rsolid(b, ql.edges().take(4), 1.0)


@scenario
def chamfer_angle(s, ql):
    b = _box(s)
    s.chamfer_rsolid(b, ql.edges().take(2), 1.0, angle=30.0, reference_direction=(0, 0, 1))


@scenario
def shell_top(s, ql):
    b = _box(s)
    s.shell_rsolid(b, _top_face(s, ql).exactly(1), 1.0)


@scenario
def shell_tags(s, ql):
    b = _box(s)
    s.shell_rsolid(b, _top_face(s, ql).exactly(1), 1.0, result_tag="hollow")


@scenario
def draft_faces(s, ql):
    b = _box(s)
    s.draft_rsolid(b, ql.faces().where(ql.prop("geom.normal.z", "<", 0.1)).where(ql.prop("geom.normal.z", ">", -0.1)), 3.0)


@scenario
def offset_openings(s, ql):
    b = _box(s)
    s.offset_rsolid(b, 1.0, _top_face(s, ql))


@scenario
def offset_plain(s, ql):
    s.offset_rsolid(_box(s), 1.0)


@scenario
def extrude_basic(s, ql):
    f = s.make_rectangle_rface(6, 4)
    s.extrude_rsolid(f, (0, 0, 1), 5)


@scenario
def extrude_tagged(s, ql):
    f = s.make_circle_rface((0, 0, 0), 3)
    s.extrude_rsolid(f, (0, 0, 1), 5, tag_prefix="pin", result_tag="body")


@scenario
def extrude_taper(s, ql):
    f = s.make_rectangle_rface(6, 4)
    s.extrude_taper_rsolid(f, (0, 0, 5), 5.0)


@scenario
def extrude_until(s, ql):
    target = s.translate_shape(_box(s, 20, 20, 10), (0, 0, 10))
    f = s.make_circle_rface((0, 0, 0), 2)
    s.extrude_until_rsolid(f, target, (0, 0, 1))


@scenario
def revolve_basic(s, ql):
    w = s.make_rectangle_rface(2, 3)
    s.revolve_rsolid(s.translate_shape(w, (5, 0, 0)), (0, 1, 0), 270)


@scenario
def sweep_basic(s, ql):
    prof = s.make_circle_rface((0, 0, 0), 1)
    path = s.make_polyline_rwire([(0, 0, 0), (0, 0, 5), (5, 0, 10)])
    s.sweep_rsolid(prof, path)


@scenario
def sweep_twisted(s, ql):
    s.twisted_sweep_rsolid(s.make_rectangle_rface(4, 2), 10, 45)


@scenario
def sweep_helical(s, ql):
    prof = s.translate_shape(s.make_rectangle_rwire(1, 1), (5, 0, 0))
    s.helical_sweep_rsolid(prof, 4.0, 12.0, 5.0)


@scenario
def loft_solid(s, ql):
    a = s.make_rectangle_rwire(6, 6)
    b = s.translate_shape(s.make_circle_rwire((0, 0, 0), 2), (0, 0, 8))
    s.loft_rsolid([a, b])


@scenario
def loft_shell(s, ql):
    a = s.make_rectangle_rwire(6, 6)
    b = s.translate_shape(s.make_rectangle_rwire(3, 3), (0, 0, 8))
    s.loft_rshell([a, b])


@scenario
def multisection(s, ql):
    p1 = s.make_circle_rface((0, 0, 0), 2)
    p2 = s.translate_shape(s.make_circle_rface((0, 0, 0), 3), (0, 0, 6))
    path = s.make_segment_rwire((0, 0, 0), (0, 0, 6))
    s.sweep_multisection_rsolid([p1, p2], path)


# ---- booleans ----------------------------------------------------------------------------
@scenario
def bool_cut(s, ql):
    s.cut_rsolid(_box(s), s.make_cylinder_rsolid(3, 30))


@scenario
def bool_cut_many(s, ql):
    b = _box(s)
    s.cut_rsolid(b, s.translate_shape(s.make_cylinder_rsolid(2, 30), (4, 4, -5)), s.translate_shape(s.make_cylinder_rsolid(2, 30), (-4, -4, -5)))


@scenario
def bool_union(s, ql):
    a = _box(s)
    b = s.translate_shape(_box(s, 5, 5, 20), (0, 0, 0))
    s.union_rsolid(a, b)


@scenario
def bool_intersect(s, ql):
    s.intersect_rsolid(_box(s), s.make_cylinder_rsolid(8, 30))


@scenario
def bool_union_list(s, ql):
    parts = s.linear_pattern_rsolidlist(s.make_box_rsolid(2, 2, 2), (1, 0, 0), 3, 1.5)
    s.union_rsolid(parts)


@scenario
def bool_cut_selected_face_tool(s, ql):
    b = _box(s)
    c = s.fillet_rsolid(b, ql.edges().take(4), 1.0)
    s.cut_rsolid(c, s.make_sphere_rsolid(4))


# ---- patterns / transforms ----------------------------------------------------------------
@scenario
def pattern_linear(s, ql):
    s.linear_pattern_rsolidlist(s.make_cylinder_rsolid(1, 2), (1, 0, 0), 4, 3.0)


@scenario
def transform_all(s, ql):
    b = _box(s)
    t = s.translate_shape(b, (1, 2, 3))
    r = s.rotate_shape(t, 30, (0, 0, 1))
    m = s.mirror_shape(r, (0, 0, 0), (1, 0, 0))
    s.scale_rsolid(m, (2.0, 2.0, 2.0))


@scenario
def transform_after_pick(s, ql):
    b = _box(s)
    f = b.get_faces(0)
    s.translate_shape(f, (0, 0, 2))


# ---- tags ---------------------------------------------------------------------------------
@scenario
def tag_apply(s, ql):
    b = _box(s)
    s.apply_tag(b.get_faces(0), "mount")


@scenario
def tag_rselection(s, ql):
    b = _box(s)
    s.apply_tag_rselection(b, ql.faces().where(ql.surface_type("PLANE")).take(2), "side")


@scenario
def tag_chained_pick(s, ql):
    b = _box(s)
    b2 = s.apply_tag_rselection(b, ql.faces().take(1), "pickme")
    s.shell_rsolid(b2, ql.faces().where(ql.tag("pickme")), 1.0)


# ---- surfaces -----------------------------------------------------------------------------
@scenario
def surf_ruled(s, ql):
    a = s.make_line_redge((0, 0, 0), (5, 0, 0))
    b = s.make_line_redge((0, 3, 2), (5, 3, 2))
    s.make_ruled_surface_rface(a, b)


@scenario
def surf_sew_solid(s, ql):
    b = _box(s)
    faces = [b.get_faces(i) for i in range(6)]
    sh = s.sew_faces_rshell(faces)
    s.make_solid_from_shell_rsolid(sh)


@scenario
def surf_trim(s, ql):
    carrier = s.make_rectangle_rface(10, 10)
    outer = s.make_circle_rwire((0, 0, 0), 3)
    s.trim_surface_rface(carrier, outer)


@scenario
def surf_gordon(s, ql):
    p = [s.make_line_redge((0, y, 0), (10, y, 0)) for y in (0.0, 5.0)]
    g = [s.make_line_redge((x, 0, 0), (x, 5, 0)) for x in (0.0, 10.0)]
    s.make_gordon_surface_rface(p, g)


@scenario
def surf_fill_holes(s, ql):
    b = _box(s)
    sh = s.sew_faces_rshell([b.get_faces(i) for i in range(5)])
    s.fill_holes_rshell(sh)


# ---- sketches -----------------------------------------------------------------------------
@scenario
def sketch_face_extrude(s, ql):
    sk = s.make_sketch_rsketch("outline")
    sk = s.add_point_rsketch(sk, "p0", 0, 0)
    sk = s.add_point_rsketch(sk, "p1", 10, 0)
    sk = s.add_point_rsketch(sk, "p2", 10, 6)
    sk = s.add_point_rsketch(sk, "p3", 0, 6)
    sk = s.add_line_rsketch(sk, "l0", "p0", "p1")
    sk = s.add_line_rsketch(sk, "l1", "p1", "p2")
    sk = s.add_line_rsketch(sk, "l2", "p2", "p3")
    sk = s.add_line_rsketch(sk, "l3", "p3", "p0")
    f = s.make_face_from_sketch_rface(sk)
    s.extrude_rsolid(f, (0, 0, 1), 4)


@scenario
def sketch_circle_wire(s, ql):
    sk = s.make_sketch_rsketch("c")
    sk = s.add_point_rsketch(sk, "c0", 0, 0)
    sk = s.add_circle_rsketch(sk, "ring", "c0", 3.0)
    s.make_wire_from_sketch_rwire(sk)


# ---- products ------------------------------------------------------------------------------
@scenario
def product_part(s, ql):
    b = _box(s)
    f = s.apply_tag(b.get_faces(0), "interface.mount")
    p = s.make_part_rpart("blk", b, name="Block")
    s.add_connector_rpart(p, s.make_face_connector_rconnector("mount", f))


@scenario
def product_assembly(s, ql):
    b = _box(s)
    f = s.apply_tag(b.get_faces(0), "interface.mount")
    p = s.make_part_rpart("blk", b, name="Block")
    p = s.add_connector_rpart(p, s.make_face_connector_rconnector("mount", f))
    asm = s.make_assembly_rassembly("asm")
    asm = s.add_component_rassembly(asm, p, component_id="a", placement=s.identity_placement_rplacement())
    asm = s.add_component_rassembly(asm, p, component_id="b", placement=s.make_placement_rplacement((30, 0, 0)))
    asm = s.ground_component_rassembly(asm, "a")
    asm = s.add_revolute_constraint_rassembly(
        asm, "j", s.make_connector_ref_rconnectorref("a", "mount"), s.make_connector_ref_rconnectorref("b", "mount"), drive_angle_degrees=10.0
    )
    s.solve_assembly_constraints_rassembly(asm)


# ---- std parts -----------------------------------------------------------------------------
@scenario
def std_gear(s, ql):
    from simplecadapi import std
    std.make_spur_gear_rsolid(module=1.0, teeth=12, thickness=4.0) if hasattr(std, "make_spur_gear_rsolid") else None


# ---- symbolic parameters ----------------------------------------------------------------------
@scenario
def param_vars(s, ql):
    w = s.Var("w", 20.0) if hasattr(s, "Var") else 20.0
    b = s.make_box_rsolid(w, w * 2, 10)
    s.fillet_rsolid(b, ql.edges().take(3), 1)

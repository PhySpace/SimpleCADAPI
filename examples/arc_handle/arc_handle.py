# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "arc_handle"
# revision = "4.0.0"
# ///
"""Parametric arched handle with rounded capsule mounting lands.

X: hole span. Y: bow height and countersunk-hole axis. Z: section width.
The handle is one fused solid. Bolt insertion envelopes are subtractive
installation clearances, not display-only validation geometry.

    sca run examples/arc_handle/arc_handle.py
    uv run python examples/arc_handle/export.py        # check + package + render
    uv run python examples/arc_handle/fem_analysis.py  # Gmsh + CalculiX
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql

    # Fixed section and hardware constants; the four parameters are in the
    # params cell.
    ROD_RADIUS = 8.5
    LAND_DEPTH = 5.0
    COUNTERSINK_RADIAL_ALLOWANCE = 2.75
    LAND_RADIAL_MARGIN = 3.5
    ROOT_PAD_RADIUS = 12.0
    ROOT_OFFSET_CLEARANCE = 1.5
    LAND_EDGE_FILLET = 1.2
    ROOT_FILLET_RADIUS = 2.5
    COUNTERSINK_DEPTH = 2.0
    CUT_OVERSHOOT = 1.0
    BOLT_DIAMETRAL_CLEARANCE = 0.2
    INSERTION_START_Y = LAND_DEPTH / 2.0 + 2.0 * ROD_RADIUS + CUT_OVERSHOOT
    BOLT_TRAVEL_HEIGHT = INSERTION_START_Y + LAND_DEPTH + 2.0 * CUT_OVERSHOOT
    THROUGH_CUT_HEIGHT = LAND_DEPTH + 2.0 * ROD_RADIUS + 2.0 * CUT_OVERSHOOT


@app.function
def print_stage(label: str, solid: scad.Solid) -> None:
    """Fact card: face/edge counts and volume, not the whole solid."""
    faces = ql.faces().resolve(solid)
    edges = ql.edges().resolve(solid)
    print(f"{label}: faces={len(faces)} edges={len(edges)} volume={solid.get_volume():.3f}")


@app.function
def capsule_land(*, hole_x: float, root_x: float, hole_radius: float, label: str) -> scad.Solid:
    """One mounting land: hole pad + root pad joined by a bridge, rims rounded."""
    hole_pad = scad.make_cylinder_rsolid(
        radius=hole_radius,
        height=LAND_DEPTH,
        bottom_face_center=(hole_x, -LAND_DEPTH / 2.0, 0.0),
        axis=(0.0, 1.0, 0.0),
        tag_prefix=f"arc_handle.{label}.hole_pad",
        end_face_tag=f"arc_handle.{label}.pad.front",
        result_tag=f"solid.arc_handle.{label}.hole_pad",
    )
    root_pad = scad.make_cylinder_rsolid(
        radius=ROOT_PAD_RADIUS,
        height=LAND_DEPTH,
        bottom_face_center=(root_x, -LAND_DEPTH / 2.0, 0.0),
        axis=(0.0, 1.0, 0.0),
        tag_prefix=f"arc_handle.{label}.root_pad",
        end_face_tag=f"arc_handle.{label}.pad.front",
        result_tag=f"solid.arc_handle.{label}.root_pad",
    )
    bridge = scad.make_box_rsolid(
        width=abs(root_x - hole_x),
        height=LAND_DEPTH,
        depth=2.0 * ROOT_PAD_RADIUS,
        bottom_face_center=((hole_x + root_x) / 2.0, 0.0, -ROOT_PAD_RADIUS),
        tag_prefix=f"arc_handle.{label}.capsule_bridge",
        front_face_tag=f"arc_handle.{label}.pad.front",
        result_tag=f"solid.arc_handle.{label}.capsule_bridge",
    )
    land = scad.union_rsolid([hole_pad, root_pad, bridge], clean=True, glue=False)
    rim = ql.edges().where(
        ql.and_(
            ql.prop("geom.type", "==", "CIRCLE"),
            ql.or_(
                ql.prop("geom.center.y", ">", LAND_DEPTH / 2.0 - 0.01),
                ql.prop("geom.center.y", "<", -LAND_DEPTH / 2.0 + 0.01),
            ),
        )
    ).exactly(4)
    rim_edges = rim.resolve(land)
    print(f"ql_{label}_land_rim_edges={len(rim_edges)}")
    return scad.fillet_rsolid(
        solid=land,
        edges=rim_edges,
        radius=LAND_EDGE_FILLET,
        result_tag=f"solid.arc_handle.{label}.roundedcapsule_land",
    )


@app.function
def root_blend_edges(*, body: scad.Solid, label: str) -> list[scad.Edge]:
    """The edge where the rod meets the *label* land's front pad face."""
    side = "<" if label == "left" else ">"
    pad_face = ql.faces().where(
        ql.and_(
            ql.prop("geom.normal.y", ">", 0.9),
            ql.prop("geom.center.y", ">", 1.0),
            ql.prop("geom.center.x", side, 0.0),
        )
    ).exactly(1)
    # The fused rod's side faces may merge into one face spanning the whole
    # arc, so the end is discriminated by the pad face alone; the rod side is
    # matched without a centroid-side constraint.
    rod_face = ql.faces().where(ql.tag("arc_handle.rod.side")).at_least(1)
    shared = pad_face.shared_boundary(rod_face, to_kind="edge").exactly(1)
    edges = shared.resolve(body)
    print(f"ql_{label}_root_shared_edges={len(edges)}")
    return edges


@app.function
def through_and_countersink_cutters(*, center_x: float, through_diameter: float) -> tuple[scad.Solid, scad.Solid]:
    """The through-hole and countersink cutters of one hole, opening on +Y."""
    through_radius = through_diameter / 2.0
    countersink_radius = through_radius + COUNTERSINK_RADIAL_ALLOWANCE
    outside_radius = countersink_radius + (countersink_radius - through_radius) * CUT_OVERSHOOT / COUNTERSINK_DEPTH
    through = scad.make_cylinder_rsolid(
        radius=through_radius,
        height=THROUGH_CUT_HEIGHT,
        bottom_face_center=(center_x, -LAND_DEPTH / 2.0 - CUT_OVERSHOOT, 0.0),
        axis=(0.0, 1.0, 0.0),
        tag_prefix="arc_handle.hole.through",
        result_tag="solid.arc_handle.hole.through.cutter",
    )
    countersink = scad.make_cone_rsolid(
        bottom_radius=countersink_radius,
        top_radius=outside_radius,
        height=COUNTERSINK_DEPTH + CUT_OVERSHOOT,
        bottom_face_center=(center_x, LAND_DEPTH / 2.0 + CUT_OVERSHOOT, 0.0),
        axis=(0.0, -1.0, 0.0),
        tag_prefix="arc_handle.hole.countersink",
        result_tag="solid.arc_handle.hole.countersink.cutter",
    )
    return through, countersink


@app.function
def countersunk_bolt_insertion_envelope(*, center_x: float, through_diameter: float, label: str) -> scad.Solid:
    """The volume a countersunk bolt sweeps when inserted from +Y."""
    shaft_radius = (through_diameter - BOLT_DIAMETRAL_CLEARANCE) / 2.0
    head_radius = (through_diameter + 2.0 * COUNTERSINK_RADIAL_ALLOWANCE - BOLT_DIAMETRAL_CLEARANCE) / 2.0
    shaft = scad.make_cylinder_rsolid(
        radius=shaft_radius,
        height=BOLT_TRAVEL_HEIGHT,
        bottom_face_center=(center_x, -LAND_DEPTH / 2.0 - CUT_OVERSHOOT, 0.0),
        axis=(0.0, 1.0, 0.0),
        tag_prefix=f"arc_handle.validation.{label}.shaft",
        result_tag=f"solid.arc_handle.validation.{label}.shaft",
    )
    moving_head = scad.make_cylinder_rsolid(
        radius=head_radius,
        height=INSERTION_START_Y + LAND_DEPTH / 2.0,
        bottom_face_center=(center_x, INSERTION_START_Y, 0.0),
        axis=(0.0, -1.0, 0.0),
        tag_prefix=f"arc_handle.validation.{label}.head",
        result_tag=f"solid.arc_handle.validation.{label}.head",
    )
    return scad.union_rsolid([shaft, moving_head], clean=True, glue=False, tracking_policy="graph")


@app.cell
def _():
    # ---- params ----
    HOLE_SPAN = scad.var(name="hole_span", default=110.0, comment="center-to-center hole span along X", unit="mm", tolerance=0.1)
    BOW_HEIGHT = scad.var(name="bow_height", default=24.0, comment="arc midpoint height along Y", unit="mm", tolerance=0.1)
    LEFT_HOLE_D = scad.var(name="left_hole_diameter", default=5.5, comment="left through-hole diameter", unit="mm", tolerance=0.05)
    RIGHT_HOLE_D = scad.var(name="right_hole_diameter", default=5.5, comment="right through-hole diameter", unit="mm", tolerance=0.05)
    return BOW_HEIGHT, HOLE_SPAN, LEFT_HOLE_D, RIGHT_HOLE_D


@app.cell
def _(BOW_HEIGHT, HOLE_SPAN, LEFT_HOLE_D, RIGHT_HOLE_D):
    # ---- guard: parameter feasibility ----
    if float(HOLE_SPAN) <= 4.0 * ROOT_PAD_RADIUS:
        raise ValueError("hole span is too short for the capsule lands")
    if float(BOW_HEIGHT) <= 0.0:
        raise ValueError("bow height must be positive")
    if COUNTERSINK_DEPTH >= LAND_DEPTH:
        raise ValueError("countersink depth must be less than land depth")
    for _label, _diameter in (("left", float(LEFT_HOLE_D)), ("right", float(RIGHT_HOLE_D))):
        if _diameter <= 0.0:
            raise ValueError(f"{_label} through-hole diameter must be positive")
    return


@app.cell
def _(HOLE_SPAN, LEFT_HOLE_D, RIGHT_HOLE_D):
    # ---- layout ----
    # Hole and root-pad positions along X. The root pads sit far enough
    # inboard that a bolt head clears them.
    left_x = -HOLE_SPAN / 2.0
    right_x = HOLE_SPAN / 2.0
    left_land_radius = float(LEFT_HOLE_D) / 2.0 + COUNTERSINK_RADIAL_ALLOWANCE + LAND_RADIAL_MARGIN
    right_land_radius = float(RIGHT_HOLE_D) / 2.0 + COUNTERSINK_RADIAL_ALLOWANCE + LAND_RADIAL_MARGIN
    _head_radius = (float(LEFT_HOLE_D) + 2.0 * COUNTERSINK_RADIAL_ALLOWANCE - BOLT_DIAMETRAL_CLEARANCE) / 2.0
    root_offset = _head_radius + ROOT_PAD_RADIUS + ROOT_OFFSET_CLEARANCE
    left_root_x = left_x + root_offset
    right_root_x = right_x - root_offset
    return (
        left_land_radius,
        left_root_x,
        left_x,
        right_land_radius,
        right_root_x,
        right_x,
        root_offset,
    )


@app.cell
def _(BOW_HEIGHT, left_root_x, right_root_x):
    # ---- feature: arched-rod (build, profile=geometry, path=geometry) ----
    # A cubic Bezier from root to root; control points at 4/3 of the bow
    # height put the arc's midpoint at the bow height.
    _control_y = BOW_HEIGHT * 4.0 / 3.0
    _path = scad.make_spline_rwire(
        control_points=[(left_root_x, 0.0, 0.0), (left_root_x, _control_y, 0.0), (right_root_x, _control_y, 0.0), (right_root_x, 0.0, 0.0)],
        degree=3,
    )
    _profile = scad.make_circle_rface(center=(float(left_root_x), 0.0, 0.0), radius=ROD_RADIUS, normal=(0.0, 1.0, 0.0), tag_prefix="arc_handle.rod.profile")
    arched_rod = scad.sweep_rsolid(profile=_profile, path=_path, is_frenet=True, tag_prefix="arc_handle.rod", side_faces_tag="arc_handle.rod.side", result_tag="solid.arc_handle.arched_rod")
    return (arched_rod,)


@app.cell
def _(
    arched_rod,
    left_land_radius,
    left_root_x,
    left_x,
    right_land_radius,
    right_root_x,
    right_x,
):
    # ---- feature: capsule-lands (add) ----
    _left = capsule_land(hole_x=float(left_x), root_x=float(left_root_x), hole_radius=left_land_radius, label="left")
    _right = capsule_land(hole_x=float(right_x), root_x=float(right_root_x), hole_radius=right_land_radius, label="right")
    capsule_lands = scad.union_rsolid([arched_rod, _left, _right], clean=True, glue=False)
    print_stage("fused_capsule_handle", capsule_lands)
    return (capsule_lands,)


@app.cell
def _(capsule_lands):
    # ---- feature: root-blends (modify) ----
    _edges = root_blend_edges(body=capsule_lands, label="left") + root_blend_edges(body=capsule_lands, label="right")
    if len(_edges) != 2:
        raise ValueError(f"expected two QL-selected root edges, got {len(_edges)}")
    root_blends = scad.fillet_rsolid(solid=capsule_lands, edges=_edges, radius=ROOT_FILLET_RADIUS, result_tag="solid.arc_handle.root_blends")
    return (root_blends,)


@app.cell
def _(LEFT_HOLE_D, RIGHT_HOLE_D, left_x, right_x, root_blends):
    # ---- feature: countersunk-holes (subtract) ----
    # The bolt envelopes are cut too: the bolts must go in from +Y unobstructed.
    _tools = []
    for _x, _d, _label in ((left_x, LEFT_HOLE_D, "left"), (right_x, RIGHT_HOLE_D, "right")):
        _tools += through_and_countersink_cutters(center_x=float(_x), through_diameter=float(_d))
    for _x, _d, _label in ((left_x, LEFT_HOLE_D, "left"), (right_x, RIGHT_HOLE_D, "right")):
        _tools.append(countersunk_bolt_insertion_envelope(center_x=float(_x), through_diameter=float(_d), label=_label))
    countersunk_holes = scad.cut_rsolid(root_blends, _tools, skip_non_intersecting=False)
    return (countersunk_holes,)


@app.cell
def _(
    HOLE_SPAN,
    LEFT_HOLE_D,
    RIGHT_HOLE_D,
    countersunk_holes,
    left_land_radius,
    right_land_radius,
    root_offset,
):
    # ---- feature: handle-roles (annotate) ----
    _body = scad.apply_tag(shape=countersunk_holes, tag="role.arc_handle.continuous_body")
    handle_roles = scad.apply_tag(shape=_body, tag="role.arc_handle.full_bolt_installation_clearance")
    for _key, _value in (
        ("coordinate_convention", "X=span, Y=bow-height and hole axis, Z=thickness"),
        ("hole_axis", (0.0, 1.0, 0.0)),
        ("countersink_opening_face", "+Y capsule-land faces"),
        ("hole_span_mm", float(HOLE_SPAN)),
        ("left_hole_diameter_mm", float(LEFT_HOLE_D)),
        ("right_hole_diameter_mm", float(RIGHT_HOLE_D)),
        ("left_mounting_land_radius_mm", left_land_radius),
        ("right_mounting_land_radius_mm", right_land_radius),
        ("root_pad_radius_mm", ROOT_PAD_RADIUS),
        ("root_offset_mm", root_offset),
        ("root_blend_radius_mm", ROOT_FILLET_RADIUS),
        ("countersink_depth_mm", COUNTERSINK_DEPTH),
    ):
        handle_roles.set_metadata(_key, _value)
    print_stage("finished_body", handle_roles)
    return (handle_roles,)


@app.cell
def _(handle_roles):
    arc_handle = scad.make_part_rpart(part_id="arc_handle", body=handle_roles, name="Parametric capsule-land arched handle with countersunk through holes")
    return (arc_handle,)


if __name__ == "__main__":
    app.run()

# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "constrained_sketch"
# revision = "1.0.0"
# ///
"""Constrained sketch-first modeling: a bracket whose every profile is a sketch.

Each profile is authored in the sketch API with the constraints that carry
its design intent, checked fully constrained, and promoted to a face with
``make_face_from_sketch_rface``. Concrete geometry APIs stay for paths, pure
geometry and lowering targets.

    sca run examples/constrained_sketch/constrained_sketch.py
    uv run python examples/constrained_sketch/export.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    # Through-cutters start below the plate and end above it.
    CUT_OVERSHOOT = 1.0


@app.function
def report_sketch(name, sketch):
    """Print the sketch's solve status, DOF, residual and a few solved values."""
    result = scad.inspect_sketch_rsketchresult(
        sketch=sketch,
        require_fully_constrained=True,
    )
    points = sorted(
        (point_id, round(point[0], 3), round(point[1], 3))
        for point_id, point in result.solved_points.items()
    )
    scalars = sorted(
        (key, round(value, 3)) for key, value in result.solved_scalars.items()
    )
    print(
        f"{name}_sketch", result.status, "dof", result.dof,
        "residual", f"{result.residual_norm:.2e}",
        "points", points[:4], "scalars", scalars[:2],
    )


@app.function
def promote_face(name, sketch):
    """Report the sketch, then promote it to a face; it must be fully constrained."""
    report_sketch(name=name, sketch=sketch)
    return scad.make_face_from_sketch_rface(
        sketch=sketch,
        require_fully_constrained=True,
    )


@app.function
def profile_entity_tags(profile):
    """The ``sketch_entity.*`` tags the promotion put on the profile's edges."""
    return sorted(
        tag
        for edge in scad.ql.edges()
        .where(scad.ql.tag(pattern="sketch_entity.*"))
        .resolve(profile)
        for tag in scad.list_tags(shape=edge)
        if tag.startswith("sketch_entity.")
    )


@app.function
def through_cutter(profile, depth, slug, tag):
    """Extrude *profile* into a cutter that passes through a plate *depth* thick."""
    cutter = scad.extrude_rsolid(
        profile=profile,
        direction=(0.0, 0.0, 1.0),
        distance=depth + 2.0 * CUT_OVERSHOOT,
        tag_prefix=f"constrained_sketch.{slug}.cutter",
        result_tag=f"tool.constrained_sketch.{tag}",
    )
    return scad.translate_shape(shape=cutter, vector=(0.0, 0.0, -CUT_OVERSHOOT))


@app.function
def make_rect_profile(name, x0, y0, width, height):
    """A rectangle held by parallel/perpendicular/equal-length constraints."""
    sketch = scad.make_sketch_rsketch(name=name, plane="XY")

    sketch = scad.add_point_rsketch(sketch=sketch, point_id="p0", x=x0, y=y0)
    sketch = scad.add_point_rsketch(
        sketch=sketch,
        point_id="p1",
        x=x0 + width,
        y=y0,
    )
    sketch = scad.add_point_rsketch(
        sketch=sketch,
        point_id="p2",
        x=x0 + width,
        y=y0 + height,
    )
    sketch = scad.add_point_rsketch(
        sketch=sketch,
        point_id="p3",
        x=x0,
        y=y0 + height,
    )

    sketch = scad.add_line_rsketch(
        sketch=sketch,
        entity_id="bottom",
        start="p0",
        end="p1",
    )
    sketch = scad.add_line_rsketch(
        sketch=sketch,
        entity_id="right",
        start="p1",
        end="p2",
    )
    sketch = scad.add_line_rsketch(
        sketch=sketch,
        entity_id="top",
        start="p2",
        end="p3",
    )
    sketch = scad.add_line_rsketch(
        sketch=sketch,
        entity_id="left",
        start="p3",
        end="p0",
    )

    sketch = scad.constrain_horizontal_rsketch(sketch=sketch, line="bottom")
    sketch = scad.constrain_vertical_rsketch(sketch=sketch, line="right")
    sketch = scad.constrain_parallel_rsketch(
        sketch=sketch,
        a="bottom",
        b="top",
    )
    sketch = scad.constrain_parallel_rsketch(
        sketch=sketch,
        a="left",
        b="right",
    )
    sketch = scad.constrain_perpendicular_rsketch(
        sketch=sketch,
        a="bottom",
        b="right",
    )
    sketch = scad.constrain_equal_length_rsketch(
        sketch=sketch,
        a="bottom",
        b="top",
    )
    sketch = scad.constrain_equal_length_rsketch(
        sketch=sketch,
        a="left",
        b="right",
    )
    sketch = scad.constrain_distance_rsketch(
        sketch=sketch,
        a="p0",
        b="p1",
        value=width,
    )
    sketch = scad.constrain_distance_rsketch(
        sketch=sketch,
        a="p0",
        b="p3",
        value=height,
    )
    sketch = scad.constrain_fix_rsketch(sketch=sketch, target="p0")
    return promote_face(name=name, sketch=sketch)


@app.function
def make_circle_profile(name, center_x, center_y, radius, circle_id):
    """A circle with a fixed center and a radius constraint."""
    sketch = scad.make_sketch_rsketch(name=name, plane="XY")
    sketch = scad.add_point_rsketch(
        sketch=sketch,
        point_id="center",
        x=center_x,
        y=center_y,
    )
    sketch = scad.add_circle_rsketch(
        sketch=sketch,
        entity_id=circle_id,
        center="center",
        radius=radius,
    )
    sketch = scad.constrain_fix_rsketch(sketch=sketch, target="center")
    sketch = scad.constrain_radius_rsketch(
        sketch=sketch,
        circle=circle_id,
        value=radius,
    )
    return promote_face(name=name, sketch=sketch)


@app.function
def make_guided_diamond_profile(name, center_x, center_y, width, height, guide_gap):
    """A diamond whose sides are placed by two parallel construction rails."""
    half_w = width / 2.0
    half_h = height / 2.0
    sketch = scad.make_sketch_rsketch(name=name, plane="XY")

    for point_id, x, y in (
        ("center", center_x, center_y),
        ("left", center_x - half_w, center_y),
        ("top", center_x, center_y + half_h),
        ("right", center_x + half_w, center_y),
        ("bottom", center_x, center_y - half_h),
        ("guide_upper_start", center_x - half_w, center_y + guide_gap),
        ("guide_upper_end", center_x, center_y + half_h + guide_gap),
        ("guide_lower_start", center_x + half_w, center_y - guide_gap),
        ("guide_lower_end", center_x, center_y - half_h - guide_gap),
    ):
        sketch = scad.add_point_rsketch(
            sketch=sketch,
            point_id=point_id,
            x=x,
            y=y,
        )

    for entity_id, start, end, construction in (
        ("bottom_left", "left", "bottom", False),
        ("right_bottom", "bottom", "right", False),
        ("top_right", "right", "top", False),
        ("left_top", "top", "left", False),
        ("guide_upper", "guide_upper_start", "guide_upper_end", True),
        ("guide_lower", "guide_lower_start", "guide_lower_end", True),
    ):
        sketch = scad.add_line_rsketch(
            sketch=sketch,
            entity_id=entity_id,
            start=start,
            end=end,
            construction=construction,
        )

    sketch = scad.constrain_fix_rsketch(sketch=sketch, target="center")
    for function, a, b, value in (
        (scad.constrain_distance_x_rsketch, "left", "center", half_w),
        (scad.constrain_distance_y_rsketch, "left", "center", 0.0),
        (scad.constrain_distance_x_rsketch, "center", "right", half_w),
        (scad.constrain_distance_y_rsketch, "center", "right", 0.0),
        (scad.constrain_distance_x_rsketch, "center", "top", 0.0),
        (scad.constrain_distance_y_rsketch, "center", "top", half_h),
        (scad.constrain_distance_x_rsketch, "bottom", "center", 0.0),
        (scad.constrain_distance_y_rsketch, "bottom", "center", half_h),
    ):
        sketch = function(sketch=sketch, a=a, b=b, value=value)

    for function, a, b in (
        (scad.constrain_parallel_rsketch, "left_top", "right_bottom"),
        (scad.constrain_parallel_rsketch, "top_right", "bottom_left"),
        (scad.constrain_equal_length_rsketch, "left_top", "top_right"),
        (scad.constrain_equal_length_rsketch, "top_right", "right_bottom"),
        (scad.constrain_equal_length_rsketch, "right_bottom", "bottom_left"),
    ):
        sketch = function(sketch=sketch, a=a, b=b)

    for function, a, b, value in (
        (scad.constrain_distance_x_rsketch, "left", "guide_upper_start", 0.0),
        (scad.constrain_distance_y_rsketch, "left", "guide_upper_start", guide_gap),
        (scad.constrain_distance_x_rsketch, "top", "guide_upper_end", 0.0),
        (scad.constrain_distance_y_rsketch, "top", "guide_upper_end", guide_gap),
        (scad.constrain_distance_x_rsketch, "guide_lower_start", "right", 0.0),
        (scad.constrain_distance_y_rsketch, "guide_lower_start", "right", guide_gap),
        (scad.constrain_distance_x_rsketch, "guide_lower_end", "bottom", 0.0),
        (scad.constrain_distance_y_rsketch, "guide_lower_end", "bottom", guide_gap),
    ):
        sketch = function(sketch=sketch, a=a, b=b, value=value)

    for function, a, b in (
        (scad.constrain_parallel_rsketch, "guide_upper", "guide_lower"),
        (scad.constrain_parallel_rsketch, "guide_upper", "right_bottom"),
        (scad.constrain_parallel_rsketch, "guide_lower", "left_top"),
        (scad.constrain_equal_length_rsketch, "guide_upper", "right_bottom"),
        (scad.constrain_equal_length_rsketch, "guide_lower", "left_top"),
    ):
        sketch = function(sketch=sketch, a=a, b=b)
    return promote_face(name=name, sketch=sketch)


@app.function
def make_curve_guided_relief_profile(name, center_x, center_y, radius, guide_span):
    """A circle held by tangent construction rails and a concentric twin."""
    sketch = scad.make_sketch_rsketch(name=name, plane="XY")

    for point_id, x, y in (
        ("center", center_x, center_y),
        ("rim", center_x + radius, center_y),
        ("clearance_center", center_x, center_y),
        ("upper_left", center_x - guide_span, center_y + radius),
        ("upper_right", center_x + guide_span, center_y + radius),
        ("lower_left", center_x - guide_span, center_y - radius),
        ("lower_right", center_x + guide_span, center_y - radius),
    ):
        sketch = scad.add_point_rsketch(
            sketch=sketch,
            point_id=point_id,
            x=x,
            y=y,
        )

    sketch = scad.add_circle_rsketch(
        sketch=sketch,
        entity_id="relief",
        center="center",
        radius=radius,
    )
    sketch = scad.add_circle_rsketch(
        sketch=sketch,
        entity_id="clearance",
        center="clearance_center",
        radius=radius,
        construction=True,
    )
    for entity_id, start, end in (
        ("radius_probe", "center", "rim"),
        ("upper_rail", "upper_left", "upper_right"),
        ("lower_rail", "lower_left", "lower_right"),
    ):
        sketch = scad.add_line_rsketch(
            sketch=sketch,
            entity_id=entity_id,
            start=start,
            end=end,
            construction=True,
        )

    sketch = scad.constrain_fix_rsketch(sketch=sketch, target="center")
    sketch = scad.constrain_radius_rsketch(
        sketch=sketch,
        circle="relief",
        value=radius,
    )
    sketch = scad.constrain_point_on_rsketch(
        sketch=sketch,
        point="rim",
        entity="relief",
    )
    sketch = scad.constrain_horizontal_rsketch(
        sketch=sketch,
        line="radius_probe",
    )
    sketch = scad.constrain_length_rsketch(
        sketch=sketch,
        line="radius_probe",
        value=radius,
    )

    sketch = scad.constrain_concentric_rsketch(
        sketch=sketch,
        a="relief",
        b="clearance",
    )
    sketch = scad.constrain_equal_radius_rsketch(
        sketch=sketch,
        a="relief",
        b="clearance",
    )
    sketch = scad.constrain_horizontal_rsketch(
        sketch=sketch,
        line="upper_rail",
    )
    sketch = scad.constrain_horizontal_rsketch(
        sketch=sketch,
        line="lower_rail",
    )
    sketch = scad.constrain_tangent_rsketch(
        sketch=sketch,
        a="upper_rail",
        b="relief",
    )
    sketch = scad.constrain_tangent_rsketch(
        sketch=sketch,
        a="lower_rail",
        b="relief",
    )

    for a, b, value in (
        ("center", "upper_left", -guide_span),
        ("center", "upper_right", guide_span),
        ("center", "lower_left", -guide_span),
        ("center", "lower_right", guide_span),
    ):
        sketch = scad.constrain_distance_x_rsketch(
            sketch=sketch,
            a=a,
            b=b,
            value=value,
        )
    return promote_face(name=name, sketch=sketch)


@app.cell
def _():
    # ---- params: plate ----
    PLATE_W = scad.var(name="plate_w", default=96.0, comment="plate width")
    PLATE_H = scad.var(name="plate_h", default=54.0, comment="plate height")
    PLATE_T = scad.var(name="plate_t", default=6.0, comment="plate thickness")
    return PLATE_H, PLATE_T, PLATE_W


@app.cell
def _():
    # ---- params: boss and bore ----
    BOSS_R = scad.var(name="boss_r", default=14.0, comment="raised center boss radius")
    BOSS_H = scad.var(name="boss_h", default=5.0, comment="raised center boss height")
    BORE_R = scad.var(name="bore_r", default=5.0, comment="through bore radius")
    return BORE_R, BOSS_H, BOSS_R


@app.cell
def _():
    # ---- params: cutouts ----
    MOUNT_R = scad.var(name="mount_r", default=3.0, comment="mounting hole radius")
    MOUNT_MARGIN_X = scad.var(
        name="mount_margin_x", default=12.0, comment="mounting hole x margin")
    MOUNT_MARGIN_Y = scad.var(
        name="mount_margin_y", default=9.0, comment="mounting hole y margin")
    SLOT_W = scad.var(name="slot_w", default=34.0, comment="service slot width")
    SLOT_H = scad.var(name="slot_h", default=8.0, comment="service slot height")
    SLOT_Y = scad.var(name="slot_center_y", default=16.0, comment="service slot center y")
    DIAMOND_W = scad.var(
        name="guided_diamond_w", default=14.0, comment="guided diamond pocket width")
    DIAMOND_H = scad.var(
        name="guided_diamond_h", default=8.0, comment="guided diamond pocket height")
    DIAMOND_GUIDE_GAP = scad.var(
        name="guided_diamond_guide_gap", default=5.0, comment="parallel guide rail offset")
    RELIEF_R = scad.var(
        name="curve_relief_r", default=4.0, comment="curve-guided relief radius")
    RELIEF_GUIDE_SPAN = scad.var(
        name="curve_relief_guide_span", default=9.0,
        comment="curve relief construction rail half span")
    return (
        DIAMOND_GUIDE_GAP,
        DIAMOND_H,
        DIAMOND_W,
        MOUNT_MARGIN_X,
        MOUNT_MARGIN_Y,
        MOUNT_R,
        RELIEF_GUIDE_SPAN,
        RELIEF_R,
        SLOT_H,
        SLOT_W,
        SLOT_Y,
    )


@app.cell
def _(PLATE_H, PLATE_T, PLATE_W):
    # ---- feature: base-plate (build, profile=sketch) ----
    _profile = make_rect_profile(
        name="plate_outline", x0=0.0, y0=0.0, width=PLATE_W, height=PLATE_H)
    _profile = scad.apply_tag(shape=_profile, tag="demo.profile.plate")
    plate_entity_tags = profile_entity_tags(_profile)
    _plate = scad.extrude_rsolid(
        profile=_profile,
        direction=(0.0, 0.0, 1.0),
        distance=PLATE_T,
        tag_prefix="constrained_sketch.plate",
        result_tag="part.constrained_sketch.base_plate",
    )
    base_plate = scad.apply_tag(shape=_plate, tag="demo.body.base_plate")
    return base_plate, plate_entity_tags


@app.cell
def _(BOSS_H, BOSS_R, PLATE_H, PLATE_T, PLATE_W, base_plate):
    # ---- feature: raised-boss (add, profile=sketch) ----
    # The boss sinks 1 mm into the plate so the union has a volume overlap.
    _overlap = 1.0
    _profile = make_circle_profile(
        name="center_boss", center_x=PLATE_W / 2.0, center_y=PLATE_H / 2.0,
        radius=BOSS_R, circle_id="boss_outer")
    _boss = scad.extrude_rsolid(
        profile=_profile,
        direction=(0.0, 0.0, 1.0),
        distance=BOSS_H + _overlap,
        tag_prefix="constrained_sketch.boss",
        result_tag="part.constrained_sketch.raised_boss",
    )
    _boss = scad.translate_shape(shape=_boss, vector=(0.0, 0.0, PLATE_T - _overlap))
    _boss = scad.apply_tag(shape=_boss, tag="demo.body.raised_boss")
    raised_boss = scad.union_rsolid(base_plate, _boss, glue=False)
    return (raised_boss,)


@app.cell
def _(BORE_R, BOSS_H, PLATE_H, PLATE_T, PLATE_W, raised_boss):
    # ---- feature: center-bore (subtract, profile=sketch) ----
    _profile = make_circle_profile(
        name="center_bore", center_x=PLATE_W / 2.0, center_y=PLATE_H / 2.0,
        radius=BORE_R, circle_id="bore")
    center_bore = scad.cut_rsolid(
        raised_boss,
        through_cutter(_profile, PLATE_T + BOSS_H, "bore", "center_bore"),
        skip_non_intersecting=False,
    )
    return (center_bore,)


@app.cell
def _(PLATE_T, PLATE_W, SLOT_H, SLOT_W, SLOT_Y, center_bore):
    # ---- feature: service-slot (subtract, profile=sketch) ----
    _profile = make_rect_profile(
        name="service_slot",
        x0=PLATE_W / 2.0 - SLOT_W / 2.0,
        y0=SLOT_Y - SLOT_H / 2.0,
        width=SLOT_W,
        height=SLOT_H,
    )
    service_slot = scad.cut_rsolid(
        center_bore,
        through_cutter(_profile, PLATE_T, "slot", "service_slot"),
        skip_non_intersecting=False,
    )
    return (service_slot,)


@app.cell
def _(DIAMOND_GUIDE_GAP, DIAMOND_H, DIAMOND_W, PLATE_H, PLATE_T, PLATE_W, service_slot):
    # ---- feature: guided-diamond-pocket (subtract, profile=sketch) ----
    _profile = make_guided_diamond_profile(
        name="guided_diamond_pocket",
        center_x=PLATE_W - 24.0,
        center_y=PLATE_H - 18.0,
        width=DIAMOND_W,
        height=DIAMOND_H,
        guide_gap=DIAMOND_GUIDE_GAP,
    )
    diamond_entity_tags = profile_entity_tags(_profile)
    guided_diamond_pocket = scad.cut_rsolid(
        service_slot,
        through_cutter(_profile, PLATE_T, "diamond", "diamond_pocket"),
        skip_non_intersecting=False,
    )
    return diamond_entity_tags, guided_diamond_pocket


@app.cell
def _(PLATE_H, PLATE_T, PLATE_W, RELIEF_GUIDE_SPAN, RELIEF_R, guided_diamond_pocket):
    # ---- feature: curve-guided-relief (subtract, profile=sketch) ----
    _profile = make_curve_guided_relief_profile(
        name="curve_guided_relief",
        center_x=PLATE_W / 3.0,
        center_y=PLATE_H - 12.0,
        radius=RELIEF_R,
        guide_span=RELIEF_GUIDE_SPAN,
    )
    curve_entity_tags = profile_entity_tags(_profile)
    curve_guided_relief = scad.cut_rsolid(
        guided_diamond_pocket,
        through_cutter(_profile, PLATE_T, "curve_relief", "curve_relief"),
        skip_non_intersecting=False,
    )
    return curve_entity_tags, curve_guided_relief


@app.cell
def _(MOUNT_MARGIN_X, MOUNT_MARGIN_Y, MOUNT_R, PLATE_H, PLATE_T, PLATE_W, curve_guided_relief):
    # ---- feature: mount-holes (subtract, profile=sketch) ----
    _cutters = []
    for _name, _x, _y in (
        ("mount_sw", MOUNT_MARGIN_X, MOUNT_MARGIN_Y),
        ("mount_se", PLATE_W - MOUNT_MARGIN_X, MOUNT_MARGIN_Y),
        ("mount_ne", PLATE_W - MOUNT_MARGIN_X, PLATE_H - MOUNT_MARGIN_Y),
        ("mount_nw", MOUNT_MARGIN_X, PLATE_H - MOUNT_MARGIN_Y),
    ):
        _profile = make_circle_profile(
            name=_name, center_x=_x, center_y=_y, radius=MOUNT_R, circle_id="mount_hole")
        _tag = _name.replace("_", ".")
        _cutters.append(through_cutter(_profile, PLATE_T, _tag, _tag))
    mount_holes = scad.cut_rsolid(curve_guided_relief, _cutters, skip_non_intersecting=False)
    return (mount_holes,)


@app.cell
def _(curve_entity_tags, diamond_entity_tags, mount_holes, plate_entity_tags):
    _body = scad.apply_tag(shape=mount_holes, tag="demo.constrained_sketch_bracket")
    constrained_sketch = scad.make_part_rpart(
        part_id="constrained_sketch", body=_body, name="Constrained sketch bracket")
    # The promotions tag each profile edge with its sketch entity; keep the
    # tag lists on the part so exports can show where each edge came from.
    constrained_sketch.set_metadata(
        "example.profile_entity_tags",
        {
            "plate": plate_entity_tags,
            "diamond": diamond_entity_tags,
            "curve": curve_entity_tags,
        },
    )
    return (constrained_sketch,)


if __name__ == "__main__":
    app.run()

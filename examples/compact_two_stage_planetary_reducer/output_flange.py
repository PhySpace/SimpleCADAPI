# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "output_flange"
# ///
"""Output flange: the sealed rotating face a robot link bolts onto.

A broad disk running close to the housing seal bore, a center boss, and a
shallow raised register ring split into three pads. The pads give the
mating link a positive angular index (torque is not carried by screw
friction alone): two counterbored link screws sit on each pad, and three
smaller counterbored screws near the center retain the output cap.

The flange is built at the origin and moved to ``OUTPUT_FLANGE_BOTTOM_Z``;
the ``axis`` connector sits on the boss's top face.

    sca run examples/compact_two_stage_planetary_reducer/output_flange.py
"""

import marimo

app = marimo.App()

with app.setup:
    import math

    import simplecadapi as scad

    from common import AxialFace, apply_tags, make_axis_part_rpart
    from dimensions import (
        OUTPUT_FLANGE_BOSS_HEIGHT,
        OUTPUT_FLANGE_BOSS_OUTER_DIAMETER,
        OUTPUT_FLANGE_BOTTOM_Z,
        OUTPUT_FLANGE_CENTER_COUNTERBORE_DEPTH,
        OUTPUT_FLANGE_CENTER_COUNTERBORE_DIAMETER,
        OUTPUT_FLANGE_CENTER_FASTENER_CIRCLE_DIAMETER,
        OUTPUT_FLANGE_CENTER_FASTENER_COUNT,
        OUTPUT_FLANGE_CENTER_FASTENER_DIAMETER,
        OUTPUT_FLANGE_HOLE_CIRCLE_DIAMETER,
        OUTPUT_FLANGE_HOLE_COUNTERBORE_DEPTH,
        OUTPUT_FLANGE_HOLE_COUNTERBORE_DIAMETER,
        OUTPUT_FLANGE_HOLE_DIAMETER,
        OUTPUT_FLANGE_HOLE_OFFSET_DEGREES,
        OUTPUT_FLANGE_HOLES_PER_PAD,
        OUTPUT_FLANGE_INNER_DIAMETER,
        OUTPUT_FLANGE_OUTER_DIAMETER,
        OUTPUT_FLANGE_REGISTER_GAP_WIDTH,
        OUTPUT_FLANGE_REGISTER_HEIGHT,
        OUTPUT_FLANGE_REGISTER_INNER_DIAMETER,
        OUTPUT_FLANGE_REGISTER_OUTER_DIAMETER,
        OUTPUT_FLANGE_REGISTER_PAD_COUNT,
        OUTPUT_FLANGE_THICKNESS,
        OUTPUT_FLANGE_TOP_Z,
    )
    from materials import make_reducer_material_rmaterial

    TAG_PREFIX = "reducer.output.flange"


@app.function
def z_cylinder(
    radius: float,
    height: float,
    bottom: tuple[float, float, float],
    tag: str,
    cutter: bool = False,
) -> scad.Solid:
    """A +Z cylinder; faces tagged ``<TAG_PREFIX>.<tag>``, the solid ``solid.<...>``.

    A cutter's solid tag ends in ``.cutter``.
    """
    suffix = ".cutter" if cutter else ""
    return scad.make_cylinder_rsolid(
        radius=radius,
        height=height,
        bottom_face_center=bottom,
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"{TAG_PREFIX}.{tag}",
        result_tag=f"solid.{TAG_PREFIX}.{tag}{suffix}",
    )


@app.cell
def _():
    # ---- feature: flange-blank (build) ----
    # Disk, boss and register ring in one union; boss and ring sink 0.05 mm
    # into the disk. The ring is a shallow annulus (outer minus inner).
    _disk = z_cylinder(OUTPUT_FLANGE_OUTER_DIAMETER / 2.0, OUTPUT_FLANGE_THICKNESS, (0.0, 0.0, 0.0), "base")
    _boss = z_cylinder(
        OUTPUT_FLANGE_BOSS_OUTER_DIAMETER / 2.0,
        OUTPUT_FLANGE_BOSS_HEIGHT + 0.05,
        (0.0, 0.0, OUTPUT_FLANGE_THICKNESS - 0.05),
        "boss",
    )
    _register = scad.cut_rsolid(
        z_cylinder(
            OUTPUT_FLANGE_REGISTER_OUTER_DIAMETER / 2.0,
            OUTPUT_FLANGE_REGISTER_HEIGHT + 0.05,
            (0.0, 0.0, OUTPUT_FLANGE_THICKNESS - 0.05),
            "register.outer",
        ),
        z_cylinder(
            OUTPUT_FLANGE_REGISTER_INNER_DIAMETER / 2.0,
            OUTPUT_FLANGE_REGISTER_HEIGHT + 0.55,
            (0.0, 0.0, OUTPUT_FLANGE_THICKNESS - 0.30),
            "register.inner",
            cutter=True,
        ),
        skip_non_intersecting=False,
    )
    flange_blank = scad.union_rsolid([_disk, _boss, _register], glue=False)
    return (flange_blank,)


@app.cell
def _(flange_blank):
    # ---- feature: register-gaps-and-fastener-holes (subtract) ----
    # One cut with every cutter: the center bore, three radial gaps that split
    # the register ring into pads, two counterbored link screws per pad, and
    # three counterbored cap screws on the inner circle.
    _cutters = [
        z_cylinder(
            OUTPUT_FLANGE_INNER_DIAMETER / 2.0,
            OUTPUT_FLANGE_THICKNESS + OUTPUT_FLANGE_BOSS_HEIGHT + 2.0,
            (0.0, 0.0, -1.0),
            "center.bore",
            cutter=True,
        )
    ]

    _register_mid_radius = (
        OUTPUT_FLANGE_REGISTER_INNER_DIAMETER + OUTPUT_FLANGE_REGISTER_OUTER_DIAMETER
    ) / 4.0
    _register_radial_width = (
        OUTPUT_FLANGE_REGISTER_OUTER_DIAMETER - OUTPUT_FLANGE_REGISTER_INNER_DIAMETER
    ) / 2.0
    for _index in range(OUTPUT_FLANGE_REGISTER_PAD_COUNT):
        _gap = scad.make_box_rsolid(
            width=_register_radial_width + 2.2,
            height=OUTPUT_FLANGE_REGISTER_GAP_WIDTH,
            depth=OUTPUT_FLANGE_REGISTER_HEIGHT + 0.6,
            bottom_face_center=(_register_mid_radius, 0.0, OUTPUT_FLANGE_THICKNESS - 0.25),
            tag_prefix=f"{TAG_PREFIX}.register.gap.i{_index + 1}",
            result_tag=f"solid.{TAG_PREFIX}.register.gap.i{_index + 1}.cutter",
        )
        _cutters.append(
            scad.rotate_shape(
                shape=_gap,
                angle=60.0 + 360.0 * _index / OUTPUT_FLANGE_REGISTER_PAD_COUNT,
                axis=(0.0, 0.0, 1.0),
                origin=(0.0, 0.0, 0.0),
            )
        )

    # Link screws: one each side of every pad center, clamping through the pad.
    _link_angles = [
        360.0 * _pad / OUTPUT_FLANGE_REGISTER_PAD_COUNT
        + (-1.0 if _hole == 0 else 1.0) * OUTPUT_FLANGE_HOLE_OFFSET_DEGREES
        for _pad in range(OUTPUT_FLANGE_REGISTER_PAD_COUNT)
        for _hole in range(OUTPUT_FLANGE_HOLES_PER_PAD)
    ]
    _link_radius = OUTPUT_FLANGE_HOLE_CIRCLE_DIAMETER / 2.0
    for _index, _degrees in enumerate(_link_angles):
        _x = _link_radius * math.cos(math.radians(_degrees))
        _y = _link_radius * math.sin(math.radians(_degrees))
        _cutters.append(
            z_cylinder(
                OUTPUT_FLANGE_HOLE_DIAMETER / 2.0,
                OUTPUT_FLANGE_THICKNESS + OUTPUT_FLANGE_REGISTER_HEIGHT + 1.0,
                (_x, _y, -0.5),
                f"link.hole.i{_index + 1}",
                cutter=True,
            )
        )
        _cutters.append(
            z_cylinder(
                OUTPUT_FLANGE_HOLE_COUNTERBORE_DIAMETER / 2.0,
                OUTPUT_FLANGE_HOLE_COUNTERBORE_DEPTH + 0.3,
                (
                    _x,
                    _y,
                    OUTPUT_FLANGE_THICKNESS
                    + OUTPUT_FLANGE_REGISTER_HEIGHT
                    - OUTPUT_FLANGE_HOLE_COUNTERBORE_DEPTH,
                ),
                f"link.counterbore.i{_index + 1}",
                cutter=True,
            )
        )

    # Cap screws retain the internal output cap; the link screws carry the robot.
    _cap_radius = OUTPUT_FLANGE_CENTER_FASTENER_CIRCLE_DIAMETER / 2.0
    for _index in range(OUTPUT_FLANGE_CENTER_FASTENER_COUNT):
        _angle = 2.0 * math.pi * _index / OUTPUT_FLANGE_CENTER_FASTENER_COUNT + math.radians(30.0)
        _x = _cap_radius * math.cos(_angle)
        _y = _cap_radius * math.sin(_angle)
        _cutters.append(
            z_cylinder(
                OUTPUT_FLANGE_CENTER_FASTENER_DIAMETER / 2.0,
                OUTPUT_FLANGE_THICKNESS + OUTPUT_FLANGE_BOSS_HEIGHT + 1.0,
                (_x, _y, -0.5),
                f"cap.hole.i{_index + 1}",
                cutter=True,
            )
        )
        _cutters.append(
            z_cylinder(
                OUTPUT_FLANGE_CENTER_COUNTERBORE_DIAMETER / 2.0,
                OUTPUT_FLANGE_CENTER_COUNTERBORE_DEPTH + 0.3,
                (
                    _x,
                    _y,
                    OUTPUT_FLANGE_THICKNESS
                    + OUTPUT_FLANGE_BOSS_HEIGHT
                    - OUTPUT_FLANGE_CENTER_COUNTERBORE_DEPTH,
                ),
                f"cap.counterbore.i{_index + 1}",
                cutter=True,
            )
        )
    _cut = scad.cut_rsolid(flange_blank, _cutters, skip_non_intersecting=False)
    register_gaps_and_fastener_holes = apply_tags(
        _cut, tags=("role.output_register_pads", "role.link_mount_interface")
    )
    return (register_gaps_and_fastener_holes,)


@app.cell
def _(register_gaps_and_fastener_holes):
    # ---- feature: axial-seat (modify) ----
    axial_seat = scad.translate_shape(
        shape=register_gaps_and_fastener_holes,
        vector=(0.0, 0.0, OUTPUT_FLANGE_BOTTOM_Z),
    )
    return (axial_seat,)


@app.cell
def _(axial_seat):
    # ---- product: boss-face axis connector ----
    _body = apply_tags(axial_seat, tags=("role.output_flange", "group.two_stage_reducer"))
    output_flange = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        solid=_body,
        name="Six-hole output flange",
        material=make_reducer_material_rmaterial(key="shaft"),
        faces=(AxialFace("axis", target_z=OUTPUT_FLANGE_TOP_Z, normal_z=1.0),),
    )
    return (output_flange,)


if __name__ == "__main__":
    app.run()

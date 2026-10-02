# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "input_flange"
# ///
"""Input flange: the six-hole motor-side disk that drives the input shaft.

A flat disk with a short center boss, a through bore and six counterbored
bolt holes. It is built at the origin and moved to its axial seat at
``INPUT_FLANGE_BOTTOM_Z``; the ``axis`` connector sits on the boss's top face.
No edge picks (fillets/chamfers) so the FreeCAD export stays stable.

    sca run examples/compact_two_stage_planetary_reducer/input_flange.py
"""

import marimo

app = marimo.App()

with app.setup:
    import math

    import simplecadapi as scad

    from common import AxialFace, apply_tags, make_axis_part_rpart
    from dimensions import (
        INPUT_FLANGE_BOSS_HEIGHT,
        INPUT_FLANGE_BOSS_OUTER_DIAMETER,
        INPUT_FLANGE_BOTTOM_Z,
        INPUT_FLANGE_HOLE_CIRCLE_DIAMETER,
        INPUT_FLANGE_HOLE_COUNT,
        INPUT_FLANGE_HOLE_COUNTERBORE_DEPTH,
        INPUT_FLANGE_HOLE_COUNTERBORE_DIAMETER,
        INPUT_FLANGE_HOLE_DIAMETER,
        INPUT_FLANGE_INNER_DIAMETER,
        INPUT_FLANGE_OUTER_DIAMETER,
        INPUT_FLANGE_THICKNESS,
        INPUT_FLANGE_TOP_Z,
    )
    from materials import make_reducer_material_rmaterial

    TAG_PREFIX = "reducer.input.flange"


@app.cell
def _():
    # ---- feature: flange-blank (build) ----
    _disk = scad.make_cylinder_rsolid(
        radius=INPUT_FLANGE_OUTER_DIAMETER / 2.0,
        height=INPUT_FLANGE_THICKNESS,
        bottom_face_center=(0.0, 0.0, 0.0),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"{TAG_PREFIX}.base",
        result_tag=f"solid.{TAG_PREFIX}.base",
    )
    # The boss sinks 0.05 mm into the disk so the union is a real overlap.
    _boss = scad.make_cylinder_rsolid(
        radius=INPUT_FLANGE_BOSS_OUTER_DIAMETER / 2.0,
        height=INPUT_FLANGE_BOSS_HEIGHT + 0.05,
        bottom_face_center=(0.0, 0.0, INPUT_FLANGE_THICKNESS - 0.05),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"{TAG_PREFIX}.boss",
        result_tag=f"solid.{TAG_PREFIX}.boss",
    )
    flange_blank = scad.union_rsolid([_disk, _boss], glue=False)
    return (flange_blank,)


@app.cell
def _(flange_blank):
    # ---- feature: bore-and-bolt-holes (subtract) ----
    # One cut: the center bore, then a through hole plus a screw-head
    # counterbore per bolt, so the motor-side cover can sit flush.
    _through_height = INPUT_FLANGE_THICKNESS + INPUT_FLANGE_BOSS_HEIGHT + 2.0
    _cutters = [
        scad.make_cylinder_rsolid(
            radius=INPUT_FLANGE_INNER_DIAMETER / 2.0,
            height=_through_height,
            bottom_face_center=(0.0, 0.0, -1.0),
            axis=(0.0, 0.0, 1.0),
            tag_prefix=f"{TAG_PREFIX}.center.bore",
            result_tag=f"solid.{TAG_PREFIX}.center.bore.cutter",
        )
    ]
    _bolt_circle_radius = INPUT_FLANGE_HOLE_CIRCLE_DIAMETER / 2.0
    for _index in range(INPUT_FLANGE_HOLE_COUNT):
        _angle = 2.0 * math.pi * _index / INPUT_FLANGE_HOLE_COUNT
        _x = _bolt_circle_radius * math.cos(_angle)
        _y = _bolt_circle_radius * math.sin(_angle)
        _cutters.append(
            scad.make_cylinder_rsolid(
                radius=INPUT_FLANGE_HOLE_DIAMETER / 2.0,
                height=_through_height,
                bottom_face_center=(_x, _y, -1.0),
                axis=(0.0, 0.0, 1.0),
                tag_prefix=f"{TAG_PREFIX}.mount.hole.i{_index + 1}",
                result_tag=f"solid.{TAG_PREFIX}.mount.hole.i{_index + 1}.cutter",
            )
        )
        _cutters.append(
            scad.make_cylinder_rsolid(
                radius=INPUT_FLANGE_HOLE_COUNTERBORE_DIAMETER / 2.0,
                height=INPUT_FLANGE_HOLE_COUNTERBORE_DEPTH + 0.3,
                bottom_face_center=(
                    _x,
                    _y,
                    INPUT_FLANGE_THICKNESS - INPUT_FLANGE_HOLE_COUNTERBORE_DEPTH,
                ),
                axis=(0.0, 0.0, 1.0),
                tag_prefix=f"{TAG_PREFIX}.mount.counterbore.i{_index + 1}",
                result_tag=f"solid.{TAG_PREFIX}.mount.counterbore.i{_index + 1}.cutter",
            )
        )
    bore_and_bolt_holes = scad.cut_rsolid(flange_blank, _cutters, skip_non_intersecting=False)
    return (bore_and_bolt_holes,)


@app.cell
def _(bore_and_bolt_holes):
    # ---- feature: axial-seat (modify) ----
    axial_seat = scad.translate_shape(
        shape=bore_and_bolt_holes,
        vector=(0.0, 0.0, INPUT_FLANGE_BOTTOM_Z),
    )
    return (axial_seat,)


@app.cell
def _(axial_seat):
    # ---- product: boss-face axis connector ----
    _body = apply_tags(axial_seat, tags=("role.input_flange", "group.two_stage_reducer"))
    input_flange = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        solid=_body,
        name="Six-hole input flange",
        material=make_reducer_material_rmaterial(key="shaft"),
        faces=(AxialFace("axis", target_z=INPUT_FLANGE_TOP_Z, normal_z=1.0),),
    )
    return (input_flange,)


if __name__ == "__main__":
    app.run()

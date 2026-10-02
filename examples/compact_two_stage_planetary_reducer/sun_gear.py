# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "stage1_sun_gear"
# ///
"""Bored external herringbone sun gear: a part family, one member per stage.

The ``STAGE`` key selects the stage spec in ``dimensions.STAGES``. The bore
fits the shaft that drives the sun: the input shaft for stage 1, the stage 1
carrier's shaft for stage 2. Built on z = 0; the assembly lifts it to the
stage plane.

    sca run examples/compact_two_stage_planetary_reducer/sun_gear.py --id stage2_sun_gear --set STAGE=stage2
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import AxialFace, apply_tags, cut_gear_bore_rsolid, make_axis_part_rpart
    from dimensions import (
        ADDENDUM_FACTOR,
        BACKLASH,
        CLEARANCE_FACTOR,
        GEAR_HEIGHT,
        MODULE,
        PRESSURE_ANGLE,
        STAGES,
    )
    from materials import make_reducer_material_rmaterial


@app.cell
def _():
    # ---- params: stage ----
    STAGE = "stage1"
    return (STAGE,)


@app.cell
def _(STAGE):
    # ---- feature: herringbone-sun (build) ----
    _stage = STAGES[STAGE]
    _sun = scad.std.gear.make_herringbone_gear_rsolid(
        n_teeth=_stage.sun_teeth,
        module=MODULE,
        pressure_angle=PRESSURE_ANGLE,
        helix_angle=_stage.sun_helix_angle,
        gear_height=GEAR_HEIGHT,
        addendum_factor=ADDENDUM_FACTOR,
        clearance_factor=CLEARANCE_FACTOR,
        backlash=BACKLASH,
    )
    herringbone_sun = scad.apply_tag(shape=_sun, tag=f"solid.reducer.{STAGE}.sun.gear")
    return (herringbone_sun,)


@app.cell
def _(STAGE, herringbone_sun):
    # ---- feature: shaft-bore (subtract) ----
    shaft_bore = cut_gear_bore_rsolid(
        solid=herringbone_sun,
        bore_radius=STAGES[STAGE].sun_bore_radius,
        tag_prefix=f"reducer.{STAGE}.sun.bore",
        label=f"{STAGE}_sun_bore",
    )
    return (shaft_bore,)


@app.cell
def _(STAGE, shaft_bore):
    # ---- product: top-face axis connector ----
    _body = apply_tags(shaft_bore, tags=(f"role.{STAGE}.sun_gear", "group.two_stage_reducer"))
    sun_gear = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        solid=_body,
        name=f"{STAGES[STAGE].label} herringbone sun gear",
        material=make_reducer_material_rmaterial(key="gear"),
        faces=(AxialFace("axis", target_z=GEAR_HEIGHT, normal_z=1.0),),
    )
    return (sun_gear,)


if __name__ == "__main__":
    app.run()

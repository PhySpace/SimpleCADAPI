# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "stage1_reusable_planet"
# ///
"""Bearing-supported herringbone planet: a part family, one per stage.

The ``STAGE`` key (``"stage1"`` / ``"stage2"``) selects the stage spec in
``dimensions.STAGES``. Each planet is bored for a standard 3x6x3 bearing,
which turns on a carrier pin. Built on z = 0; the actuator places all
three copies of each stage.

    sca run examples/integrated_bldc_joint_actuator/planet_gear.py --id stage2_reusable_planet --set STAGE=stage2
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import apply_tags, make_axis_part_rpart
    from dimensions import (
        ADDENDUM_FACTOR,
        BACKLASH,
        CLEARANCE_FACTOR,
        GEAR_HEIGHT,
        HELIX_ANGLE,
        PLANET_BEARING,
        PRESSURE_ANGLE,
        STAGES,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- params: stage ----
    STAGE = "stage1"
    return (STAGE,)


@app.cell
def _(STAGE):
    # ---- feature: herringbone-planet (build) ----
    _stage = STAGES[STAGE]
    _planet = scad.std.gear.make_herringbone_gear_rsolid(
        n_teeth=_stage.planet_teeth,
        module=_stage.module,
        pressure_angle=PRESSURE_ANGLE,
        helix_angle=-HELIX_ANGLE,
        gear_height=GEAR_HEIGHT,
        addendum_factor=ADDENDUM_FACTOR,
        clearance_factor=CLEARANCE_FACTOR,
        backlash=BACKLASH,
    )
    herringbone_planet = scad.apply_tag(
        shape=_planet, tag=f"solid.stdlib.{STAGE}.reusable.herringbone.planet.gear"
    )
    return (herringbone_planet,)


@app.cell
def _(STAGE, herringbone_planet):
    # ---- feature: bearing-seat (subtract) ----
    # Through bore 0.05 mm over the bearing OD.
    _bearing_seat = scad.make_cylinder_rsolid(
        radius=PLANET_BEARING.outer_diameter / 2.0 + 0.05,
        height=GEAR_HEIGHT + 2.0,
        bottom_face_center=(0.0, 0.0, -1.0),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"reducer.{STAGE}.planet.bearing.seat",
        result_tag=f"tool.reducer.{STAGE}.planet.bearing.seat",
    )
    bearing_seat = scad.cut_rsolid(herringbone_planet, _bearing_seat, skip_non_intersecting=False)
    return (bearing_seat,)


@app.cell
def _(STAGE, bearing_seat):
    # ---- product: spin and bearing axes ----
    reusable_planet = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=bearing_seat,
            tags=(f"role.{STAGE}.planet_gear", "role.planet_bearing_seat", "group.two_stage_reducer"),
        ),
        name=f"{STAGES[STAGE].label} reusable bearing-supported planet",
        material=make_actuator_material_rmaterial(key="gear"),
        connectors=(
            ("axis", (0.0, 0.0, GEAR_HEIGHT / 2.0), "Planet spin axis"),
            ("bearing_axis", (0.0, 0.0, GEAR_HEIGHT / 2.0), "Planet bearing outer-ring axis"),
        ),
    )
    return (reusable_planet,)


if __name__ == "__main__":
    app.run()

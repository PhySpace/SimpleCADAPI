# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "stage1_planet_gear"
# ///
"""Herringbone planet gear with a bearing seat: a part family, one member per stage.

The ``STAGE`` key selects the stage spec in ``dimensions.STAGES``. All three
planets of a stage are instances of the one part. The bore is a seat for the
stage's planet bearing outer ring (0.06 mm radial clearance); the
``bearing_axis`` connector sits at the seat's mid-plane. Built on z = 0.

    sca run examples/compact_two_stage_planetary_reducer/planet_gear.py --id stage2_planet_gear --set STAGE=stage2
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import (
        AxialFace,
        add_placement_axis_connector_rpart,
        apply_tags,
        cut_gear_bore_rsolid,
        make_axis_part_rpart,
    )
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

    BEARING_SEAT_CLEARANCE = 0.06


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
        module=MODULE,
        pressure_angle=PRESSURE_ANGLE,
        helix_angle=_stage.planet_helix_angle,
        gear_height=GEAR_HEIGHT,
        addendum_factor=ADDENDUM_FACTOR,
        clearance_factor=CLEARANCE_FACTOR,
        backlash=BACKLASH,
    )
    herringbone_planet = scad.apply_tag(shape=_planet, tag=f"solid.reducer.{STAGE}.planet.gear")
    return (herringbone_planet,)


@app.cell
def _(STAGE, herringbone_planet):
    # ---- feature: bearing-seat (subtract) ----
    bearing_seat = cut_gear_bore_rsolid(
        solid=herringbone_planet,
        bore_radius=STAGES[STAGE].planet_bearing.outer_diameter / 2.0 + BEARING_SEAT_CLEARANCE,
        tag_prefix=f"reducer.{STAGE}.planet.bearing.seat",
        label=f"{STAGE}_planet_bearing_seat",
    )
    return (bearing_seat,)


@app.cell
def _(STAGE, bearing_seat):
    # ---- product: top-face axis, bearing seat axis ----
    _stage = STAGES[STAGE]
    _body = apply_tags(bearing_seat, tags=(f"role.{STAGE}.planet_gear", "group.two_stage_reducer"))
    _part = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        solid=_body,
        name=f"{_stage.label} reusable herringbone planet gear",
        material=make_reducer_material_rmaterial(key="gear"),
        faces=(AxialFace("axis", target_z=GEAR_HEIGHT, normal_z=1.0),),
    )
    planet_gear = add_placement_axis_connector_rpart(
        part=_part,
        connector_id="bearing_axis",
        origin=(0.0, 0.0, _stage.gear_height / 2.0),
        name=f"{_stage.label} planet bearing bore axis",
    )
    return (planet_gear,)


if __name__ == "__main__":
    app.run()

# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "stage1_carrier_integral_stage2_sun"
# ///
"""Stage-1 planet carrier with the stage-2 sun on an integral shaft.

The carrier plate holds the three stage-1 planet pins. Its 5 mm shaft runs
through the interstage bearing and carries the stage-2 herringbone sun, so
the interstage drive is a single part.

    sca run examples/integrated_bldc_joint_actuator/stage1_carrier_sun.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import apply_tags, make_axis_part_rpart, make_carrier_body_rsolid, planet_connectors
    from dimensions import (
        ADDENDUM_FACTOR,
        BACKLASH,
        CLEARANCE_FACTOR,
        GEAR_HEIGHT,
        HELIX_ANGLE,
        INTERSTAGE_BEARING_CENTER_Z,
        INTERSTAGE_SHAFT_RADIUS,
        PRESSURE_ANGLE,
        STAGE1_ARM_WIDTH,
        STAGE1_CARRIER_BOTTOM_Z,
        STAGE1_CARRIER_THICKNESS,
        STAGE1_HUB_RADIUS,
        STAGE1_PAD_RADIUS,
        STAGE1_PIN_BOTTOM_Z,
        STAGE1_PIN_RADIUS,
        STAGE_1,
        STAGE_2,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: carrier-sun-body (build) ----
    # Carrier plate with pins, the interstage shaft, and the stage-2 sun
    # lifted onto the shaft end; one union.
    _carrier = make_carrier_body_rsolid(
        stage=STAGE_1,
        plate_bottom_z=STAGE1_CARRIER_BOTTOM_Z,
        plate_thickness=STAGE1_CARRIER_THICKNESS,
        pin_bottom_z=STAGE1_PIN_BOTTOM_Z,
        pin_radius=STAGE1_PIN_RADIUS,
        hub_radius=STAGE1_HUB_RADIUS,
        arm_width=STAGE1_ARM_WIDTH,
        pad_radius=STAGE1_PAD_RADIUS,
    )
    _shaft = scad.make_cylinder_rsolid(
        radius=INTERSTAGE_SHAFT_RADIUS,
        height=STAGE_2.top_z - STAGE1_CARRIER_BOTTOM_Z + 0.1,
        bottom_face_center=(0.0, 0.0, STAGE1_CARRIER_BOTTOM_Z - 0.05),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="reducer.stage1.carrier.interstage.shaft",
        result_tag="feature.reducer.stage1.carrier.interstage.shaft",
    )
    _stage2_sun = scad.std.gear.make_herringbone_gear_rsolid(
        n_teeth=STAGE_2.sun_teeth,
        module=STAGE_2.module,
        pressure_angle=PRESSURE_ANGLE,
        helix_angle=HELIX_ANGLE,
        gear_height=GEAR_HEIGHT,
        addendum_factor=ADDENDUM_FACTOR,
        clearance_factor=CLEARANCE_FACTOR,
        backlash=BACKLASH,
    )
    _stage2_sun = scad.apply_tag(
        shape=_stage2_sun, tag="solid.stdlib.stage2.integral.herringbone.sun.gear"
    )
    _stage2_sun = scad.translate_shape(shape=_stage2_sun, vector=(0.0, 0.0, STAGE_2.bottom_z))
    carrier_sun_body = scad.union_rsolid(_carrier, _shaft, _stage2_sun, glue=False)
    return (carrier_sun_body,)


@app.cell
def _(carrier_sun_body):
    # ---- product: carrier, bearing, sun and planet-pin axes ----
    stage1_carrier_integral_stage2_sun = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=carrier_sun_body,
            tags=(
                "role.stage1.planet_carrier",
                "role.stage2.sun_gear",
                "role.integral_interstage_drive",
                "group.two_stage_reducer",
            ),
        ),
        name="Stage 1 carrier with integral stage-2 sun shaft",
        material=make_actuator_material_rmaterial(key="gear"),
        connectors=(
            ("carrier_axis", (0.0, 0.0, INTERSTAGE_BEARING_CENTER_Z), "Stage 1 carrier bearing axis"),
            (
                "interstage_bearing_axis",
                (0.0, 0.0, INTERSTAGE_BEARING_CENTER_Z),
                "Interstage bearing inner-ring seat",
            ),
            ("stage2_sun_axis", (0.0, 0.0, STAGE_2.mid_z), "Integral stage 2 sun axis"),
            *planet_connectors(stage=STAGE_1),
        ),
    )
    return (stage1_carrier_integral_stage2_sun,)


if __name__ == "__main__":
    app.run()

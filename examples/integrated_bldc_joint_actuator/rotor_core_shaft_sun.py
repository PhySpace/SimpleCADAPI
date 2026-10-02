# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "rotor_core_shaft_sun"
# ///
"""Rotor back iron, 8 mm drive shaft and stage-1 sun gear, as one part.

The motor drives the reducer directly: the stage-1 herringbone sun is cut
on the end of the rotor shaft, so there is no coupling between them. The
part exposes one rotated bond datum per magnet (``magnet_01`` .. ``magnet_14``).

    sca run examples/integrated_bldc_joint_actuator/rotor_core_shaft_sun.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import apply_tags, make_axis_part_rpart, radial_centers, z_rotation_placement
    from dimensions import (
        ADDENDUM_FACTOR,
        BACKLASH,
        CLEARANCE_FACTOR,
        GEAR_HEIGHT,
        HELIX_ANGLE,
        MOTOR_POLE_COUNT,
        MOTOR_ROTOR_BACKIRON_RADIUS,
        MOTOR_ROTOR_BOTTOM_Z,
        MOTOR_ROTOR_TOP_Z,
        MOTOR_SHAFT_RADIUS,
        PRESSURE_ANGLE,
        REAR_BEARING_CENTER_Z,
        STAGE_1,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: rotor-body (build) ----
    # Shaft from the rear bearing to the stage-1 gear plane, the back-iron
    # cylinder, and the stage-1 sun lifted onto the shaft end.
    _shaft_bottom_z = REAR_BEARING_CENTER_Z - 3.0
    _shaft = scad.make_cylinder_rsolid(
        radius=MOTOR_SHAFT_RADIUS,
        height=STAGE_1.top_z - _shaft_bottom_z,
        bottom_face_center=(0.0, 0.0, _shaft_bottom_z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="motor.rotor.drive.shaft",
        result_tag="feature.motor.rotor.drive.shaft",
    )
    _back_iron = scad.make_cylinder_rsolid(
        radius=MOTOR_ROTOR_BACKIRON_RADIUS,
        height=MOTOR_ROTOR_TOP_Z - MOTOR_ROTOR_BOTTOM_Z,
        bottom_face_center=(0.0, 0.0, MOTOR_ROTOR_BOTTOM_Z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="motor.rotor.back.iron",
        result_tag="feature.motor.rotor.back.iron",
    )
    _sun = scad.std.gear.make_herringbone_gear_rsolid(
        n_teeth=STAGE_1.sun_teeth,
        module=STAGE_1.module,
        pressure_angle=PRESSURE_ANGLE,
        helix_angle=HELIX_ANGLE,
        gear_height=GEAR_HEIGHT,
        addendum_factor=ADDENDUM_FACTOR,
        clearance_factor=CLEARANCE_FACTOR,
        backlash=BACKLASH,
    )
    _sun = scad.apply_tag(shape=_sun, tag="solid.stdlib.stage1.integral.herringbone.sun.gear")
    _sun = scad.translate_shape(shape=_sun, vector=(0.0, 0.0, STAGE_1.bottom_z))
    rotor_body = scad.union_rsolid(_shaft, _back_iron, _sun, glue=False)
    return (rotor_body,)


@app.cell
def _(rotor_body):
    # ---- product: bearing/sun axes + per-pole magnet datums ----
    _part = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=rotor_body,
            tags=(
                "role.rotor_back_iron",
                "role.direct_drive_shaft",
                "role.stage1.sun_gear",
                "group.bldc_motor",
            ),
        ),
        name="Integrated rotor back iron, 8 mm shaft, and stage-1 sun",
        material=make_actuator_material_rmaterial(key="gear"),
        connectors=(
            ("rotor_axis", (0.0, 0.0, -2.5), "Motor rotation axis"),
            ("rear_bearing_axis", (0.0, 0.0, REAR_BEARING_CENTER_Z), "Rear motor bearing shaft seat"),
            ("front_bearing_axis", (0.0, 0.0, -2.5), "Front motor bearing shaft seat"),
            ("stage1_sun_axis", (0.0, 0.0, STAGE_1.mid_z), "Integrated stage-1 sun axis"),
        ),
    )
    for _index, _angle, _center in radial_centers(count=MOTOR_POLE_COUNT, radius=0.0):
        _part = scad.add_connector_rpart(
            part=_part,
            connector=scad.make_placement_connector_rconnector(
                connector_id=f"magnet_{_index + 1:02d}",
                placement=z_rotation_placement(origin=(0.0, 0.0, 0.0), angle_degrees=_angle),
                name=f"Magnet {_index + 1} bond datum",
            ),
        )
    rotor_core_shaft_sun = _part
    return (rotor_core_shaft_sun,)


if __name__ == "__main__":
    app.run()

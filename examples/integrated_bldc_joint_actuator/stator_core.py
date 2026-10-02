# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "stator_core"
# ///
"""12-slot laminated stator core: back-iron yoke plus twelve radial teeth.

Each tooth carries one discrete copper winding pack. The core exposes one
rotated datum per slot (``winding_01`` .. ``winding_12``), and the stator
sub-assembly fixes a pack to each datum.

    sca run examples/integrated_bldc_joint_actuator/stator_core.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import (
        apply_tags,
        make_annulus_rsolid,
        make_axis_part_rpart,
        radial_centers,
        z_rotation_placement,
    )
    from dimensions import (
        MOTOR_SLOT_COUNT,
        MOTOR_STATOR_BOTTOM_Z,
        MOTOR_STATOR_OUTER_RADIUS,
        MOTOR_STATOR_TOOTH_INNER_RADIUS,
        MOTOR_STATOR_TOOTH_WIDTH,
        MOTOR_STATOR_TOP_Z,
        MOTOR_STATOR_YOKE_INNER_RADIUS,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: back-iron (build) ----
    back_iron = make_annulus_rsolid(
        outer_radius=MOTOR_STATOR_OUTER_RADIUS,
        inner_radius=MOTOR_STATOR_YOKE_INNER_RADIUS,
        bottom_z=MOTOR_STATOR_BOTTOM_Z,
        height=MOTOR_STATOR_TOP_Z - MOTOR_STATOR_BOTTOM_Z,
        tag_prefix="motor.stator.back.iron",
        tags=("role.stator_back_iron",),
    )
    return (back_iron,)


@app.cell
def _(back_iron):
    # ---- feature: teeth (add) ----
    # Each tooth overlaps the yoke by 0.4 mm so the union is one solid.
    _tooth_length = MOTOR_STATOR_YOKE_INNER_RADIUS - MOTOR_STATOR_TOOTH_INNER_RADIUS + 0.40
    _tooth_center_radius = MOTOR_STATOR_TOOTH_INNER_RADIUS + _tooth_length / 2.0
    _teeth = []
    for _index, _angle, _center in radial_centers(count=MOTOR_SLOT_COUNT, radius=0.0):
        _tooth = scad.make_box_rsolid(
            width=_tooth_length,
            height=MOTOR_STATOR_TOOTH_WIDTH,
            depth=MOTOR_STATOR_TOP_Z - MOTOR_STATOR_BOTTOM_Z,
            bottom_face_center=(_tooth_center_radius, 0.0, MOTOR_STATOR_BOTTOM_Z),
            tag_prefix=f"motor.stator.tooth{_index + 1}",
            result_tag=f"feature.motor.stator.tooth{_index + 1}",
        )
        _teeth.append(
            scad.rotate_shape(shape=_tooth, angle=_angle, axis=(0.0, 0.0, 1.0), origin=(0.0, 0.0, 0.0))
        )
    teeth = scad.union_rsolid(back_iron, _teeth, glue=False)
    return (teeth,)


@app.cell
def _(teeth):
    # ---- product: press-fit axis + per-slot winding datums ----
    _part = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=teeth,
            tags=("role.stator_core", "role.stator_thermal_path", "group.bldc_motor"),
        ),
        name="12-slot laminated electrical-steel stator stack",
        material=make_actuator_material_rmaterial(key="electrical_steel"),
        connectors=(
            (
                "shell_axis",
                (0.0, 0.0, (MOTOR_STATOR_BOTTOM_Z + MOTOR_STATOR_TOP_Z) / 2.0),
                "Stator press-fit axis",
            ),
        ),
    )
    for _index, _angle, _center in radial_centers(count=MOTOR_SLOT_COUNT, radius=0.0):
        _part = scad.add_connector_rpart(
            part=_part,
            connector=scad.make_placement_connector_rconnector(
                connector_id=f"winding_{_index + 1:02d}",
                placement=z_rotation_placement(origin=(0.0, 0.0, 0.0), angle_degrees=_angle),
                name=f"Slot winding {_index + 1} retention datum",
            ),
        )
    stator_core = _part
    return (stator_core,)


if __name__ == "__main__":
    app.run()

# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "motor_shell"
# ///
"""Fixed 50 mm BLDC motor shell: stator sleeve, front land, rear columns.

The sleeve is the stator's thermal press-fit seat. Six M3 clearance holes
in the front land bolt it to the reducer housing; four rear columns carry
the rear bearing spider and the electronics cover on shared M2.5 screws.

    sca run examples/integrated_bldc_joint_actuator/motor_shell.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import (
        apply_tags,
        make_annulus_rsolid,
        make_axial_hole_cutters_rsolids,
        make_axis_part_rpart,
        radial_centers,
    )
    from dimensions import (
        HOUSING_INTERFACE_LAND_INNER_RADIUS,
        M3_CLEARANCE_RADIUS,
        MOTOR_INTERFACE_PCD,
        MOTOR_SHELL_BOTTOM_Z,
        MOTOR_SHELL_INNER_RADIUS,
        MOTOR_SHELL_TOP_Z,
        MOTOR_STATOR_BOTTOM_Z,
        MOTOR_STATOR_TOP_Z,
        PACKAGE_RADIUS,
        REAR_COLUMN_PCD,
        REAR_COLUMN_RADIUS,
        REAR_FASTENER_HOLE_RADIUS,
        REAR_SPIDER_BOTTOM_Z,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: shell-body (build) ----
    # Stator sleeve + front attachment land + four rear structural columns.
    _sleeve = make_annulus_rsolid(
        outer_radius=PACKAGE_RADIUS,
        inner_radius=MOTOR_SHELL_INNER_RADIUS,
        bottom_z=MOTOR_SHELL_BOTTOM_Z,
        height=MOTOR_SHELL_TOP_Z - MOTOR_SHELL_BOTTOM_Z,
        tag_prefix="housing.motor.shell.sleeve",
        tags=("role.motor_shell", "role.stator_thermal_path"),
    )
    _front_land = make_annulus_rsolid(
        outer_radius=PACKAGE_RADIUS,
        inner_radius=HOUSING_INTERFACE_LAND_INNER_RADIUS,
        bottom_z=MOTOR_SHELL_TOP_Z - 1.4,
        height=1.4,
        tag_prefix="housing.motor.shell.front.land",
        tags=("role.motor_reducer_mount",),
    )
    _columns = [
        scad.make_cylinder_rsolid(
            radius=REAR_COLUMN_RADIUS,
            height=REAR_SPIDER_BOTTOM_Z - MOTOR_SHELL_BOTTOM_Z,
            bottom_face_center=(_center[0], _center[1], MOTOR_SHELL_BOTTOM_Z),
            axis=(0.0, 0.0, 1.0),
            tag_prefix=f"housing.motor.shell.rear.column{_index + 1}",
            result_tag=f"feature.housing.motor.shell.rear.column{_index + 1}",
        )
        for _index, _angle, _center in radial_centers(count=4, radius=REAR_COLUMN_PCD / 2.0)
    ]
    shell_body = scad.union_rsolid(_sleeve, _front_land, _columns, glue=False)
    return (shell_body,)


@app.cell
def _(shell_body):
    # ---- feature: fastener-clearances (subtract) ----
    # Six M3 reducer-interface holes, four M2.5 rear-column holes.
    fastener_clearances = scad.cut_rsolid(
        shell_body,
        make_axial_hole_cutters_rsolids(
            count=6,
            pcd=MOTOR_INTERFACE_PCD,
            hole_radius=M3_CLEARANCE_RADIUS,
            bottom_z=MOTOR_SHELL_TOP_Z - 2.8,
            height=3.6,
            tag_prefix="housing.motor.shell.interface.clearance",
            angle_offset=30.0,
        ),
        make_axial_hole_cutters_rsolids(
            count=4,
            pcd=REAR_COLUMN_PCD,
            hole_radius=REAR_FASTENER_HOLE_RADIUS,
            bottom_z=MOTOR_SHELL_BOTTOM_Z - 1.0,
            height=10.4,
            tag_prefix="housing.motor.shell.rear.fastener.clearance",
        ),
        skip_non_intersecting=False,
    )
    return (fastener_clearances,)


@app.cell
def _(fastener_clearances):
    # ---- product: axis connectors ----
    motor_shell = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=fastener_clearances,
            tags=("role.fixed_motor_housing", "group.integrated_bldc_actuator"),
        ),
        name="50 mm BLDC motor shell with rear structural columns",
        material=make_actuator_material_rmaterial(key="housing"),
        connectors=(
            ("reducer_mount_axis", (0.0, 0.0, MOTOR_SHELL_TOP_Z), "Six-screw reducer mount"),
            (
                "stator_axis",
                (0.0, 0.0, (MOTOR_STATOR_BOTTOM_Z + MOTOR_STATOR_TOP_Z) / 2.0),
                "Stator thermal press-fit axis",
            ),
            ("rear_spider_axis", (0.0, 0.0, REAR_SPIDER_BOTTOM_Z), "Rear bearing spider mount"),
            ("rear_cover_axis", (0.0, 0.0, MOTOR_SHELL_BOTTOM_Z), "Rear electronics cover mount"),
        ),
    )
    return (motor_shell,)


if __name__ == "__main__":
    app.run()

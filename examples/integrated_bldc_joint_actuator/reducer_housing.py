# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "reducer_housing"
# ///
"""Fixed reducer housing: sleeve, motor-bearing bulkhead, interstage divider.

The sleeve takes both press-fit ring inserts. Its rear face bolts to the
motor shell, and its front land takes the output bearing cap; both use six
M3 screws on a 43 mm circle.

    sca run examples/integrated_bldc_joint_actuator/reducer_housing.py
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
    )
    from dimensions import (
        FRONT_MOTOR_BEARING,
        FRONT_MOTOR_BEARING_CENTER_Z,
        HOUSING_INTERFACE_LAND_INNER_RADIUS,
        INTERSTAGE_BEARING,
        INTERSTAGE_BEARING_CENTER_Z,
        M3_CLEARANCE_RADIUS,
        MOTOR_INTERFACE_PCD,
        MOTOR_SHELL_TOP_Z,
        OUTPUT_CAP_INTERFACE_PCD,
        OUTPUT_CASE_CLAMP_CENTER_Z,
        PACKAGE_RADIUS,
        REDUCER_HOUSING_BOTTOM_Z,
        REDUCER_HOUSING_FRONT_Z,
        REDUCER_HOUSING_INNER_RADIUS,
        STAGE2_CARRIER_BOTTOM_Z,
        STAGE_1,
        STAGE_2,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: housing-body (build) ----
    # Sleeve + front bearing bulkhead + interstage bearing divider + output land.
    _sleeve = make_annulus_rsolid(
        outer_radius=PACKAGE_RADIUS,
        inner_radius=REDUCER_HOUSING_INNER_RADIUS,
        bottom_z=REDUCER_HOUSING_BOTTOM_Z,
        height=REDUCER_HOUSING_FRONT_Z - REDUCER_HOUSING_BOTTOM_Z,
        tag_prefix="housing.reducer.sleeve",
        tags=("role.reducer_housing_sleeve",),
    )
    _bulkhead = make_annulus_rsolid(
        outer_radius=23.10,
        inner_radius=FRONT_MOTOR_BEARING.outer_diameter / 2.0 + 0.05,
        bottom_z=REDUCER_HOUSING_BOTTOM_Z,
        height=STAGE_1.bottom_z - REDUCER_HOUSING_BOTTOM_Z,
        tag_prefix="housing.reducer.front.bulkhead",
        tags=("role.motor_front_bearing_bulkhead",),
    )
    _interstage_divider = make_annulus_rsolid(
        outer_radius=23.10,
        inner_radius=INTERSTAGE_BEARING.outer_diameter / 2.0 + 0.05,
        bottom_z=INTERSTAGE_BEARING_CENTER_Z - INTERSTAGE_BEARING.width / 2.0,
        height=INTERSTAGE_BEARING.width,
        tag_prefix="housing.reducer.interstage.divider",
        tags=("role.interstage_bearing_divider",),
    )
    _output_mount_land = make_annulus_rsolid(
        outer_radius=PACKAGE_RADIUS,
        inner_radius=HOUSING_INTERFACE_LAND_INNER_RADIUS,
        bottom_z=REDUCER_HOUSING_FRONT_Z - 2.2,
        height=2.2,
        tag_prefix="housing.reducer.output.mount.land",
        tags=("role.output_cap_mount_land",),
    )
    housing_body = scad.union_rsolid(
        _sleeve,
        _bulkhead,
        _interstage_divider,
        _output_mount_land,
        glue=False,
    )
    return (housing_body,)


@app.cell
def _(housing_body):
    # ---- feature: interface-clearances (subtract) ----
    # Six M3 holes to the motor shell (offset 30°), six to the output cap.
    interface_clearances = scad.cut_rsolid(
        housing_body,
        make_axial_hole_cutters_rsolids(
            count=6,
            pcd=MOTOR_INTERFACE_PCD,
            hole_radius=M3_CLEARANCE_RADIUS,
            bottom_z=REDUCER_HOUSING_BOTTOM_Z - 1.0,
            height=STAGE_1.bottom_z - REDUCER_HOUSING_BOTTOM_Z + 2.0,
            tag_prefix="housing.reducer.motor.interface.clearance",
            angle_offset=30.0,
        ),
        make_axial_hole_cutters_rsolids(
            count=6,
            pcd=OUTPUT_CAP_INTERFACE_PCD,
            hole_radius=M3_CLEARANCE_RADIUS,
            bottom_z=REDUCER_HOUSING_FRONT_Z - 2.2,
            height=3.2,
            tag_prefix="housing.reducer.output.interface.clearance",
        ),
        skip_non_intersecting=False,
    )
    return (interface_clearances,)


@app.cell
def _(interface_clearances):
    # ---- product: axis connectors ----
    reducer_housing = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=interface_clearances,
            tags=(
                "role.fixed_reducer_housing",
                "role.ring_gear_press_fit",
                "group.integrated_bldc_actuator",
            ),
        ),
        name="50 mm reducer housing with motor bearing bulkhead",
        material=make_actuator_material_rmaterial(key="housing"),
        connectors=(
            ("motor_mount_axis", (0.0, 0.0, MOTOR_SHELL_TOP_Z), "Motor shell six-screw interface"),
            (
                "front_motor_bearing_axis",
                (0.0, 0.0, FRONT_MOTOR_BEARING_CENTER_Z),
                "Front motor bearing seat",
            ),
            ("stage1_ring_axis", (0.0, 0.0, STAGE_1.mid_z), "Stage 1 fixed ring seat"),
            ("stage1_carrier_axis", (0.0, 0.0, INTERSTAGE_BEARING_CENTER_Z), "Stage 1 carrier axis"),
            (
                "interstage_bearing_axis",
                (0.0, 0.0, INTERSTAGE_BEARING_CENTER_Z),
                "Interstage bearing outer seat",
            ),
            ("stage2_ring_axis", (0.0, 0.0, STAGE_2.mid_z), "Stage 2 fixed ring seat"),
            ("stage2_carrier_axis", (0.0, 0.0, STAGE2_CARRIER_BOTTOM_Z + 1.50), "Output carrier axis"),
            (
                "case_clamp_axis",
                (0.0, 0.0, OUTPUT_CASE_CLAMP_CENTER_Z),
                "External split-clamp datum on reducer sleeve",
            ),
            ("output_cap_axis", (0.0, 0.0, REDUCER_HOUSING_FRONT_Z), "Output bearing cap interface"),
        ),
    )
    return (reducer_housing,)


if __name__ == "__main__":
    app.run()

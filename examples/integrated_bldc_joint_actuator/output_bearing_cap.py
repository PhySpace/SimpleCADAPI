# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "output_bearing_cap"
# ///
"""Removable output cap: a cartridge for the paired 16x24x5 output bearings.

The cartridge seats both bearings 5 mm apart. A retainer ring holds them
axially, and an outer lip forms a labyrinth around the rotating output
flange. Six M3 screws fix it to the reducer housing.

    sca run examples/integrated_bldc_joint_actuator/output_bearing_cap.py
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
        M3_CLEARANCE_RADIUS,
        OUTPUT_BEARING_1_CENTER_Z,
        OUTPUT_BEARING_2_CENTER_Z,
        OUTPUT_CAP_BOTTOM_Z,
        OUTPUT_CAP_CARTRIDGE_TOP_Z,
        OUTPUT_CAP_INTERFACE_PCD,
        OUTPUT_CAP_TOP_Z,
        OUTPUT_FLANGE_RADIUS,
        PACKAGE_RADIUS,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: cap-body (build) ----
    # Mount flange + bearing cartridge + axial retainer + labyrinth lip.
    _bearing_clearance_radius = 12.05
    _rear_flange = make_annulus_rsolid(
        outer_radius=PACKAGE_RADIUS,
        inner_radius=_bearing_clearance_radius,
        bottom_z=OUTPUT_CAP_BOTTOM_Z,
        height=3.0,
        tag_prefix="housing.output.cap.rear.flange",
        tags=("role.output_cap_mount_flange",),
    )
    _cartridge = make_annulus_rsolid(
        outer_radius=15.0,
        inner_radius=_bearing_clearance_radius,
        bottom_z=OUTPUT_CAP_BOTTOM_Z,
        height=OUTPUT_CAP_CARTRIDGE_TOP_Z - OUTPUT_CAP_BOTTOM_Z + 0.1,
        tag_prefix="housing.output.cap.bearing.cartridge",
        tags=("role.paired_output_bearing_seat",),
    )
    _bearing_retainer = make_annulus_rsolid(
        outer_radius=PACKAGE_RADIUS,
        inner_radius=8.10,
        bottom_z=OUTPUT_CAP_CARTRIDGE_TOP_Z - 0.1,
        height=0.5,
        tag_prefix="housing.output.cap.bearing.retainer",
        tags=("role.output_axial_retainer",),
    )
    _outer_lip = make_annulus_rsolid(
        outer_radius=PACKAGE_RADIUS,
        inner_radius=OUTPUT_FLANGE_RADIUS + 0.30,
        bottom_z=OUTPUT_CAP_CARTRIDGE_TOP_Z - 0.1,
        height=OUTPUT_CAP_TOP_Z - OUTPUT_CAP_CARTRIDGE_TOP_Z + 0.1,
        tag_prefix="housing.output.cap.labyrinth.lip",
        tags=("role.output_labyrinth_lip",),
    )
    cap_body = scad.union_rsolid(
        _rear_flange, _cartridge, _bearing_retainer, _outer_lip, glue=False
    )
    return (cap_body,)


@app.cell
def _(cap_body):
    # ---- feature: interface-clearances (subtract) ----
    interface_clearances = scad.cut_rsolid(
        cap_body,
        make_axial_hole_cutters_rsolids(
            count=6,
            pcd=OUTPUT_CAP_INTERFACE_PCD,
            hole_radius=M3_CLEARANCE_RADIUS,
            bottom_z=OUTPUT_CAP_BOTTOM_Z - 1.0,
            height=OUTPUT_CAP_TOP_Z - OUTPUT_CAP_BOTTOM_Z + 2.0,
            tag_prefix="housing.output.cap.interface.clearance",
        ),
        skip_non_intersecting=False,
    )
    return (interface_clearances,)


@app.cell
def _(interface_clearances):
    # ---- product: axis connectors ----
    output_bearing_cap = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=interface_clearances,
            tags=("role.removable_output_bearing_cap", "group.integrated_bldc_actuator"),
        ),
        name="Paired output-bearing cartridge and removable cap",
        material=make_actuator_material_rmaterial(key="carrier"),
        connectors=(
            ("housing_axis", (0.0, 0.0, OUTPUT_CAP_BOTTOM_Z), "Six-screw housing interface"),
            ("bearing_1_axis", (0.0, 0.0, OUTPUT_BEARING_1_CENTER_Z), "Rear output bearing seat"),
            ("bearing_2_axis", (0.0, 0.0, OUTPUT_BEARING_2_CENTER_Z), "Front output bearing seat"),
            ("case_mount_axis", (0.0, 0.0, OUTPUT_CAP_TOP_Z), "Fixed actuator case datum"),
        ),
    )
    return (output_bearing_cap,)


if __name__ == "__main__":
    app.run()

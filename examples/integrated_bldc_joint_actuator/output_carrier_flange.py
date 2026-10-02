# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "stage2_output_carrier_flange"
# ///
"""Stage-2 output carrier: planet pins, paired-bearing shaft, output flange.

The 16 mm shaft runs in the two output bearings and ends in the flange
and pilot register. The flange face has six tapped holes for the driven
link.

    sca run examples/integrated_bldc_joint_actuator/output_carrier_flange.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import (
        apply_tags,
        make_axial_hole_cutters_rsolids,
        make_axis_part_rpart,
        make_carrier_body_rsolid,
        planet_connectors,
    )
    from dimensions import (
        OUTPUT_BEARING_1_CENTER_Z,
        OUTPUT_BEARING_2_CENTER_Z,
        OUTPUT_FLANGE_BOTTOM_Z,
        OUTPUT_FLANGE_RADIUS,
        OUTPUT_FLANGE_TOP_Z,
        OUTPUT_LINK_BOLT_ANGLES_DEGREES,
        OUTPUT_LINK_BOLT_COUNT,
        OUTPUT_LINK_HOLE_PCD,
        OUTPUT_LINK_TAP_RADIUS,
        OUTPUT_LINK_THREAD_DEPTH,
        OUTPUT_REGISTER_HEIGHT,
        OUTPUT_SHAFT_RADIUS,
        STAGE2_ARM_WIDTH,
        STAGE2_CARRIER_BOTTOM_Z,
        STAGE2_CARRIER_THICKNESS,
        STAGE2_HUB_RADIUS,
        STAGE2_PAD_RADIUS,
        STAGE2_PIN_BOTTOM_Z,
        STAGE2_PIN_RADIUS,
        STAGE_2,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: carrier-output-body (build) ----
    # Carrier plate with pins, the output shaft (through the pilot
    # register), and the output flange; one union.
    _carrier = make_carrier_body_rsolid(
        stage=STAGE_2,
        plate_bottom_z=STAGE2_CARRIER_BOTTOM_Z,
        plate_thickness=STAGE2_CARRIER_THICKNESS,
        pin_bottom_z=STAGE2_PIN_BOTTOM_Z,
        pin_radius=STAGE2_PIN_RADIUS,
        hub_radius=STAGE2_HUB_RADIUS,
        arm_width=STAGE2_ARM_WIDTH,
        pad_radius=STAGE2_PAD_RADIUS,
    )
    _shaft = scad.make_cylinder_rsolid(
        radius=OUTPUT_SHAFT_RADIUS,
        height=OUTPUT_FLANGE_TOP_Z + OUTPUT_REGISTER_HEIGHT - STAGE2_CARRIER_BOTTOM_Z + 0.05,
        bottom_face_center=(0.0, 0.0, STAGE2_CARRIER_BOTTOM_Z - 0.05),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="reducer.stage2.output.shaft",
        result_tag="feature.reducer.stage2.output.shaft",
    )
    _flange = scad.make_cylinder_rsolid(
        radius=OUTPUT_FLANGE_RADIUS,
        height=OUTPUT_FLANGE_TOP_Z - OUTPUT_FLANGE_BOTTOM_Z,
        bottom_face_center=(0.0, 0.0, OUTPUT_FLANGE_BOTTOM_Z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="reducer.stage2.output.flange",
        result_tag="feature.reducer.stage2.output.flange",
    )
    carrier_output_body = scad.union_rsolid(_carrier, _shaft, _flange, glue=False)
    return (carrier_output_body,)


@app.cell
def _(carrier_output_body):
    # ---- feature: link-threads (subtract) ----
    # Six blind tap-drill holes in the flange face for the driven link.
    link_threads = scad.cut_rsolid(
        carrier_output_body,
        make_axial_hole_cutters_rsolids(
            count=OUTPUT_LINK_BOLT_COUNT,
            pcd=OUTPUT_LINK_HOLE_PCD,
            hole_radius=OUTPUT_LINK_TAP_RADIUS,
            bottom_z=OUTPUT_FLANGE_TOP_Z - OUTPUT_LINK_THREAD_DEPTH,
            height=OUTPUT_LINK_THREAD_DEPTH + 1.0,
            tag_prefix="reducer.stage2.output.flange.thread",
            angle_offset=OUTPUT_LINK_BOLT_ANGLES_DEGREES[0],
        ),
        skip_non_intersecting=False,
    )
    return (link_threads,)


@app.cell
def _(link_threads):
    # ---- product: carrier, bearing, link and planet-pin axes ----
    stage2_output_carrier_flange = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=link_threads,
            tags=(
                "role.stage2.output_carrier",
                "role.output_bearing_land",
                "role.output_link_flange",
                "group.two_stage_reducer",
            ),
        ),
        name="Stage 2 carrier with paired-bearing shaft and output flange",
        material=make_actuator_material_rmaterial(key="carrier"),
        connectors=(
            (
                "carrier_axis",
                (0.0, 0.0, STAGE2_CARRIER_BOTTOM_Z + STAGE2_CARRIER_THICKNESS / 2.0),
                "Stage 2 output carrier axis",
            ),
            ("bearing_1_axis", (0.0, 0.0, OUTPUT_BEARING_1_CENTER_Z), "Rear output bearing inner-ring seat"),
            ("bearing_2_axis", (0.0, 0.0, OUTPUT_BEARING_2_CENTER_Z), "Front output bearing inner-ring seat"),
            ("output_link_axis", (0.0, 0.0, OUTPUT_FLANGE_TOP_Z), "Six-hole driven-link flange"),
            *planet_connectors(stage=STAGE_2),
        ),
    )
    return (stage2_output_carrier_flange,)


if __name__ == "__main__":
    app.run()

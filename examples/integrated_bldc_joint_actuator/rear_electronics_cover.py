# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "rear_electronics_cover"
# ///
"""Rear cover: carries the controller PCB and exposes its terminals.

Four standoffs hold the circular ESC. Two 9.2 x 7.2 mm apertures give
service access to the phase and power/CAN terminal blocks.

    sca run examples/integrated_bldc_joint_actuator/rear_electronics_cover.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import (
        apply_tags,
        make_axial_hole_cutters_rsolids,
        make_axis_part_rpart,
        radial_centers,
    )
    from dimensions import (
        MOTOR_SHELL_BOTTOM_Z,
        PACKAGE_RADIUS,
        PCB_BOTTOM_Z,
        PCB_STANDOFF_PCD,
        REAR_COLUMN_PCD,
        REAR_COVER_BOTTOM_Z,
        REAR_COVER_THICKNESS,
        REAR_FASTENER_HOLE_RADIUS,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: cover-body (build) ----
    # Cover plate + four PCB standoffs on a 45°-offset circle.
    _plate = scad.make_cylinder_rsolid(
        radius=PACKAGE_RADIUS,
        height=REAR_COVER_THICKNESS,
        bottom_face_center=(0.0, 0.0, REAR_COVER_BOTTOM_Z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="housing.rear.cover.plate",
        result_tag="feature.housing.rear.cover.plate",
    )
    _standoffs = [
        scad.make_cylinder_rsolid(
            radius=2.4,
            height=PCB_BOTTOM_Z - REAR_COVER_BOTTOM_Z - REAR_COVER_THICKNESS + 0.1,
            bottom_face_center=(
                _center[0],
                _center[1],
                REAR_COVER_BOTTOM_Z + REAR_COVER_THICKNESS - 0.1,
            ),
            axis=(0.0, 0.0, 1.0),
            tag_prefix=f"housing.rear.cover.pcb.standoff{_index + 1}",
            result_tag=f"feature.housing.rear.cover.pcb.standoff{_index + 1}",
        )
        for _index, _angle, _center in radial_centers(
            count=4, radius=PCB_STANDOFF_PCD / 2.0, angle_offset=45.0
        )
    ]
    cover_body = scad.union_rsolid(_plate, _standoffs, glue=False)
    return (cover_body,)


@app.cell
def _(cover_body):
    # ---- feature: access-openings (subtract) ----
    # Terminal apertures, the centre service hole, and both fastener patterns.
    _phase_aperture = scad.make_box_rsolid(
        width=9.2,
        height=7.2,
        depth=REAR_COVER_THICKNESS + 2.0,
        bottom_face_center=(-11.0, 0.0, REAR_COVER_BOTTOM_Z - 1.0),
        tag_prefix="housing.rear.cover.phase.aperture",
        result_tag="tool.housing.rear.cover.phase.aperture",
    )
    _power_aperture = scad.make_box_rsolid(
        width=9.2,
        height=7.2,
        depth=REAR_COVER_THICKNESS + 2.0,
        bottom_face_center=(11.0, 0.0, REAR_COVER_BOTTOM_Z - 1.0),
        tag_prefix="housing.rear.cover.power.can.aperture",
        result_tag="tool.housing.rear.cover.power.can.aperture",
    )
    _center_service = scad.make_cylinder_rsolid(
        radius=3.2,
        height=REAR_COVER_THICKNESS + 2.0,
        bottom_face_center=(0.0, 0.0, REAR_COVER_BOTTOM_Z - 1.0),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="housing.rear.cover.center.service",
        result_tag="tool.housing.rear.cover.center.service",
    )
    access_openings = scad.cut_rsolid(
        cover_body,
        _phase_aperture,
        _power_aperture,
        _center_service,
        make_axial_hole_cutters_rsolids(
            count=4,
            pcd=REAR_COLUMN_PCD,
            hole_radius=REAR_FASTENER_HOLE_RADIUS,
            bottom_z=REAR_COVER_BOTTOM_Z - 1.0,
            height=REAR_COVER_THICKNESS + 2.0,
            tag_prefix="housing.rear.cover.column.fastener.clearance",
        ),
        make_axial_hole_cutters_rsolids(
            count=4,
            pcd=PCB_STANDOFF_PCD,
            hole_radius=1.1,
            bottom_z=REAR_COVER_BOTTOM_Z - 1.0,
            height=PCB_BOTTOM_Z - REAR_COVER_BOTTOM_Z + 2.0,
            tag_prefix="housing.rear.cover.pcb.fastener.clearance",
            angle_offset=45.0,
        ),
        skip_non_intersecting=False,
    )
    return (access_openings,)


@app.cell
def _(access_openings):
    # ---- product: axis connectors ----
    rear_electronics_cover = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=access_openings,
            tags=(
                "role.rear_electronics_cover",
                "role.terminal_access",
                "group.integrated_bldc_actuator",
            ),
        ),
        name="Rear electronics cover with terminal access",
        material=make_actuator_material_rmaterial(key="housing"),
        connectors=(
            ("shell_axis", (0.0, 0.0, MOTOR_SHELL_BOTTOM_Z), "Four-screw motor shell interface"),
            ("pcb_axis", (0.0, 0.0, PCB_BOTTOM_Z + 0.8), "Controller PCB mounting plane"),
            ("phase_access", (-11.0, 0.0, REAR_COVER_BOTTOM_Z), "Three-phase terminal access"),
            ("power_can_access", (11.0, 0.0, REAR_COVER_BOTTOM_Z), "Power and CAN terminal access"),
        ),
    )
    return (rear_electronics_cover,)


if __name__ == "__main__":
    app.run()

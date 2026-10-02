# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "circular_controller_pcb"
# ///
"""44.4 mm circular ESC board that fits inside the motor shell's rear columns.

It has a centre bore for the rotor shaft, four mounting holes, four notches
for the rear columns, and through-holes for the two terminal blocks. It
exposes solder datums for six MOSFETs and both terminals.

    sca run examples/integrated_bldc_joint_actuator/controller_pcb.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import (
        apply_tags,
        make_axial_hole_cutters_rsolids,
        make_axis_part_rpart,
        mosfet_center_xy,
    )
    from dimensions import (
        MOSFET_ANGLES,
        PCB_BOTTOM_Z,
        PCB_CENTER_BORE_RADIUS,
        PCB_MOUNT_HOLE_RADIUS,
        PCB_RADIUS,
        PCB_STANDOFF_PCD,
        PCB_THICKNESS,
        PHASE_TERMINAL_CENTER,
        POWER_CAN_TERMINAL_CENTER,
        REAR_COLUMN_PCD,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: board (build) ----
    board = scad.make_cylinder_rsolid(
        radius=PCB_RADIUS,
        height=PCB_THICKNESS,
        bottom_face_center=(0.0, 0.0, PCB_BOTTOM_Z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="controller.pcb.board",
        result_tag="feature.controller.pcb.board",
    )
    return (board,)


@app.cell
def _(board):
    # ---- feature: board-holes (subtract) ----
    # Centre bore, mounting holes, rear-column notches, and terminal pin holes
    # (3 phase + 4 power/CAN, 1.8 mm pitch).
    _cutters: list[scad.Solid] = [
        scad.make_cylinder_rsolid(
            radius=PCB_CENTER_BORE_RADIUS,
            height=PCB_THICKNESS + 2.0,
            bottom_face_center=(0.0, 0.0, PCB_BOTTOM_Z - 1.0),
            axis=(0.0, 0.0, 1.0),
            tag_prefix="controller.pcb.center.bore",
            result_tag="tool.controller.pcb.center.bore",
        )
    ]
    _cutters.extend(
        make_axial_hole_cutters_rsolids(
            count=4,
            pcd=PCB_STANDOFF_PCD,
            hole_radius=PCB_MOUNT_HOLE_RADIUS,
            bottom_z=PCB_BOTTOM_Z - 1.0,
            height=PCB_THICKNESS + 2.0,
            tag_prefix="controller.pcb.mount.hole",
            angle_offset=45.0,
        )
    )
    _cutters.extend(
        make_axial_hole_cutters_rsolids(
            count=4,
            pcd=REAR_COLUMN_PCD,
            hole_radius=3.45,
            bottom_z=PCB_BOTTOM_Z - 1.0,
            height=PCB_THICKNESS + 2.0,
            tag_prefix="controller.pcb.rear.column.clearance",
        )
    )
    for _terminal_id, _x, _count in (
        ("phase", PHASE_TERMINAL_CENTER[0], 3),
        ("power.can", POWER_CAN_TERMINAL_CENTER[0], 4),
    ):
        for _pin in range(_count):
            _cutters.append(
                scad.make_cylinder_rsolid(
                    radius=0.65,
                    height=PCB_THICKNESS + 2.0,
                    bottom_face_center=(_x, (_pin - (_count - 1) / 2.0) * 1.8, PCB_BOTTOM_Z - 1.0),
                    axis=(0.0, 0.0, 1.0),
                    tag_prefix=f"controller.pcb.terminal.{_terminal_id}.pin{_pin + 1}",
                    result_tag=f"tool.controller.pcb.terminal.{_terminal_id}.pin{_pin + 1}",
                )
            )
    board_holes = scad.cut_rsolid(board, _cutters, skip_non_intersecting=False)
    return (board_holes,)


@app.cell
def _(board_holes):
    # ---- product: cover plane, terminal and MOSFET solder datums ----
    circular_controller_pcb = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=board_holes,
            tags=(
                "role.circular_esc_pcb",
                "role.controller_mounting_holes",
                "group.integrated_electronics",
            ),
        ),
        name="44.4 mm circular ESC PCB with service cutouts",
        material=make_actuator_material_rmaterial(key="pcb"),
        connectors=(
            ("cover_axis", (0.0, 0.0, PCB_BOTTOM_Z + PCB_THICKNESS / 2.0), "Rear-cover PCB plane"),
            ("phase_terminal", (*PHASE_TERMINAL_CENTER, PCB_BOTTOM_Z), "Phase terminal solder datum"),
            (
                "power_can_terminal",
                (*POWER_CAN_TERMINAL_CENTER, PCB_BOTTOM_Z),
                "Power/CAN terminal solder datum",
            ),
            ("phase_access", (*PHASE_TERMINAL_CENTER, -37.0), "Phase terminal service axis"),
            ("power_can_access", (*POWER_CAN_TERMINAL_CENTER, -37.0), "Power/CAN service axis"),
            *(
                (
                    f"mosfet_{_index + 1}",
                    (*mosfet_center_xy(index=_index), PCB_BOTTOM_Z + PCB_THICKNESS),
                    f"MOSFET {_index + 1} solder datum",
                )
                for _index in range(len(MOSFET_ANGLES))
            ),
        ),
    )
    return (circular_controller_pcb,)


if __name__ == "__main__":
    app.run()

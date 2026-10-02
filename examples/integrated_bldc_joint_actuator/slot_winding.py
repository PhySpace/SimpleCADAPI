# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "reusable_slot_winding"
# ///
"""One copper tooth-winding pack, reused at all twelve stator slots.

Modeled on the +X tooth: two slot sides along the tooth, and an end turn
over each end of the stack. The stator sub-assembly rotates it onto every
slot datum.

    sca run examples/integrated_bldc_joint_actuator/slot_winding.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import apply_tags, make_axis_part_rpart
    from dimensions import MOTOR_STATOR_BOTTOM_Z, MOTOR_STATOR_TOP_Z
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: winding-pack (build) ----
    # Two slot sides plus rear and front end turns, as one solid.
    _side_depth = MOTOR_STATOR_TOP_Z - MOTOR_STATOR_BOTTOM_Z + 0.4
    _side_bottom_z = MOTOR_STATOR_BOTTOM_Z - 0.2
    _side_positive = scad.make_box_rsolid(
        width=4.2,
        height=1.2,
        depth=_side_depth,
        bottom_face_center=(17.55, 2.1, _side_bottom_z),
        tag_prefix="motor.winding.side.positive",
        result_tag="feature.motor.winding.side.positive",
    )
    _side_negative = scad.make_box_rsolid(
        width=4.2,
        height=1.2,
        depth=_side_depth,
        bottom_face_center=(17.55, -2.1, _side_bottom_z),
        tag_prefix="motor.winding.side.negative",
        result_tag="feature.motor.winding.side.negative",
    )
    _rear_end_turn = scad.make_box_rsolid(
        width=4.2,
        height=5.4,
        depth=0.9,
        bottom_face_center=(17.55, 0.0, MOTOR_STATOR_BOTTOM_Z - 1.0),
        tag_prefix="motor.winding.rear.end.turn",
        result_tag="feature.motor.winding.rear.end.turn",
    )
    _front_end_turn = scad.make_box_rsolid(
        width=4.2,
        height=5.4,
        depth=0.9,
        bottom_face_center=(17.55, 0.0, MOTOR_STATOR_TOP_Z + 0.1),
        tag_prefix="motor.winding.front.end.turn",
        result_tag="feature.motor.winding.front.end.turn",
    )
    winding_pack = scad.union_rsolid(
        _side_positive, _side_negative, _rear_end_turn, _front_end_turn, glue=False
    )
    return (winding_pack,)


@app.cell
def _(winding_pack):
    # ---- product: potting datum ----
    reusable_slot_winding = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=winding_pack,
            tags=("role.copper_slot_winding", "group.three_phase_windings"),
        ),
        name="Reusable four-segment copper tooth winding pack",
        material=make_actuator_material_rmaterial(key="copper"),
        connectors=(("mount_axis", (0.0, 0.0, 0.0), "Core potting datum"),),
    )
    return (reusable_slot_winding,)


if __name__ == "__main__":
    app.run()

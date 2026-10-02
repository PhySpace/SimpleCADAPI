# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "reusable_rotor_magnet"
# ///
"""One bonded NdFeB surface magnet, reused at all fourteen rotor poles.

A rectangular block on the +X pole. Its outer corners touch the magnet
envelope radius, which sets the air gap to the stator teeth.

    sca run examples/integrated_bldc_joint_actuator/rotor_magnet.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import apply_tags, make_axis_part_rpart
    from dimensions import (
        MOTOR_MAGNET_OUTER_RADIUS,
        MOTOR_MAGNET_TANGENTIAL_WIDTH,
        MOTOR_ROTOR_BACKIRON_RADIUS,
        MOTOR_ROTOR_BOTTOM_Z,
        MOTOR_ROTOR_TOP_Z,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: magnet-block (build) ----
    # The radial depth runs from 0.05 mm inside the back iron out to the
    # x where the block's corners reach the envelope radius.
    _half_width = MOTOR_MAGNET_TANGENTIAL_WIDTH / 2.0
    _outer_x = (MOTOR_MAGNET_OUTER_RADIUS**2 - _half_width**2) ** 0.5
    _radial_depth = _outer_x - MOTOR_ROTOR_BACKIRON_RADIUS + 0.05
    magnet_block = scad.make_box_rsolid(
        width=_radial_depth,
        height=MOTOR_MAGNET_TANGENTIAL_WIDTH,
        depth=MOTOR_ROTOR_TOP_Z - MOTOR_ROTOR_BOTTOM_Z,
        bottom_face_center=(_outer_x - _radial_depth / 2.0, 0.0, MOTOR_ROTOR_BOTTOM_Z),
        tag_prefix="motor.rotor.reusable.magnet",
        result_tag="feature.motor.rotor.reusable.magnet",
    )
    return (magnet_block,)


@app.cell
def _(magnet_block):
    # ---- product: bond datum ----
    reusable_rotor_magnet = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(shape=magnet_block, tags=("role.rotor_magnet", "group.rotor_magnets")),
        name="Reusable bonded NdFeB rotor magnet",
        material=make_actuator_material_rmaterial(key="magnet"),
        connectors=(("bond_axis", (0.0, 0.0, 0.0), "Rotor bond datum"),),
    )
    return (reusable_rotor_magnet,)


if __name__ == "__main__":
    app.run()

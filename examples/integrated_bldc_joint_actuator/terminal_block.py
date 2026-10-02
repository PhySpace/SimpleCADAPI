# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "three_phase_terminal"
# ///
"""Rear wiring terminal block: a part family, sized by its pin count.

``PIN_COUNT`` sets the number of screw-access holes (1.8 mm pitch), and
``TERMINAL_NAME`` is the part's display name. The tag prefix comes from
the notebook id. The controller uses the default 3-pin phase terminal and a
4-pin power/CAN member.

    sca run examples/integrated_bldc_joint_actuator/terminal_block.py --id power_can_terminal \\
        --set PIN_COUNT=4 --set "TERMINAL_NAME=Four-position DC power and CAN terminal"
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import apply_tags, make_axis_part_rpart
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- params: terminal ----
    PIN_COUNT = 3
    TERMINAL_NAME = "Three-position motor phase terminal"
    return PIN_COUNT, TERMINAL_NAME


@app.cell
def _():
    # ---- feature: terminal-body (build) ----
    TERMINAL_WIDTH = 8.0
    _prefix = scad.notebook_id().replace("_", ".")
    terminal_body = scad.make_box_rsolid(
        width=TERMINAL_WIDTH,
        height=6.0,
        depth=4.9,
        bottom_face_center=(0.0, 0.0, 0.0),
        tag_prefix=f"controller.terminal.{_prefix}.body",
        result_tag=f"feature.controller.terminal.{_prefix}.body",
    )
    return TERMINAL_WIDTH, terminal_body


@app.cell
def _(PIN_COUNT, TERMINAL_WIDTH, terminal_body):
    # ---- feature: screw-access (subtract) ----
    # One cross hole per pin along X, through the full body width.
    _prefix = scad.notebook_id().replace("_", ".")
    _access_cutters = [
        scad.make_cylinder_rsolid(
            radius=0.75,
            height=TERMINAL_WIDTH + 2.0,
            bottom_face_center=(-TERMINAL_WIDTH / 2.0 - 1.0, (_pin - (PIN_COUNT - 1) / 2.0) * 1.8, 2.45),
            axis=(1.0, 0.0, 0.0),
            tag_prefix=f"controller.terminal.{_prefix}.access{_pin + 1}",
            result_tag=f"tool.controller.terminal.{_prefix}.access{_pin + 1}",
        )
        for _pin in range(PIN_COUNT)
    ]
    screw_access = scad.cut_rsolid(terminal_body, _access_cutters, skip_non_intersecting=False)
    return (screw_access,)


@app.cell
def _(TERMINAL_NAME, screw_access):
    # ---- product: solder datum ----
    terminal_block = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(shape=screw_access, tags=("role.rear_wiring_terminal", "role.service_access")),
        name=TERMINAL_NAME,
        material=make_actuator_material_rmaterial(key="terminal"),
        connectors=(("solder_axis", (0.0, 0.0, 4.9), "PCB solder and screw datum"),),
    )
    return (terminal_block,)


if __name__ == "__main__":
    app.run()

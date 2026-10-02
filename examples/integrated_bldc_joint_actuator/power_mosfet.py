# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "reusable_power_mosfet"
# ///
"""One power MOSFET package, reused for all six bridge switches.

    sca run examples/integrated_bldc_joint_actuator/power_mosfet.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import apply_tags, make_axis_part_rpart
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: package (build) ----
    package = scad.make_box_rsolid(
        width=4.0,
        height=3.0,
        depth=1.4,
        bottom_face_center=(0.0, 0.0, 0.0),
        tag_prefix="controller.mosfet.package",
        result_tag="feature.controller.mosfet.package",
    )
    return (package,)


@app.cell
def _(package):
    # ---- product: solder datum ----
    reusable_power_mosfet = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(shape=package, tags=("role.power_mosfet", "group.three_phase_bridge")),
        name="Reusable power MOSFET package",
        material=make_actuator_material_rmaterial(key="terminal"),
        connectors=(("solder_axis", (0.0, 0.0, 0.0), "PCB solder plane"),),
    )
    return (reusable_power_mosfet,)


if __name__ == "__main__":
    app.run()

# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "input_shaft"
# ///
"""Input shaft: carries motor torque from the input flange to the stage 1 sun.

One plain cylinder from the input flange's top face up to the top of the
stage 1 gear plane. Face connectors sit on both end faces; the input
bearing seat is a topology-free axis connector at ``INPUT_BEARING_Z``.

    sca run examples/compact_two_stage_planetary_reducer/input_shaft.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import AxialFace, add_placement_axis_connector_rpart, apply_tags, make_axis_part_rpart
    from dimensions import INPUT_BEARING_Z, INPUT_FLANGE_TOP_Z, INPUT_SHAFT_RADIUS, STAGE_1
    from materials import make_reducer_material_rmaterial


@app.cell
def _():
    # ---- feature: shaft (build) ----
    shaft = scad.make_cylinder_rsolid(
        radius=INPUT_SHAFT_RADIUS,
        height=STAGE_1.top_z - INPUT_FLANGE_TOP_Z,
        bottom_face_center=(0.0, 0.0, INPUT_FLANGE_TOP_Z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="reducer.input.shaft",
        result_tag="solid.reducer.input.shaft",
    )
    return (shaft,)


@app.cell
def _(shaft):
    # ---- product: end-face connectors, bearing seat ----
    _body = apply_tags(shaft, tags=("role.input_shaft", "group.two_stage_reducer"))
    _part = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        solid=_body,
        name="Input shaft to first-stage sun",
        material=make_reducer_material_rmaterial(key="shaft"),
        faces=(
            AxialFace("flange_axis", target_z=INPUT_FLANGE_TOP_Z, normal_z=-1.0, flip=True),
            AxialFace("sun_axis", target_z=STAGE_1.top_z, normal_z=1.0),
        ),
    )
    input_shaft = add_placement_axis_connector_rpart(
        part=_part,
        connector_id="input_bearing_axis",
        origin=(0.0, 0.0, INPUT_BEARING_Z),
        name="Input bearing shaft seat axis",
    )
    return (input_shaft,)


if __name__ == "__main__":
    app.run()

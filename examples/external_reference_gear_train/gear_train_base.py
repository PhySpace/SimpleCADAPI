# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "gear_train_base"
# ///
"""Base plate of the gear train: two axis connectors, 20 mm apart."""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- feature: base-block (build) ----
    base_block = scad.make_box_rsolid(width=30.0, height=8.0, depth=2.0)
    return (base_block,)


@app.cell
def _(base_block):
    _body = scad.apply_tag(shape=base_block, tag="role.gear_train_base")
    _part = scad.make_part_rpart(part_id="gear_train_base", body=_body)
    # The gear axes, on the top face.
    for _connector_id, _origin in (
        ("left_axis", (5.0, 4.0, 2.0)),
        ("right_axis", (25.0, 4.0, 2.0)),
    ):
        _part = scad.add_connector_rpart(
            part=_part,
            connector=scad.make_placement_connector_rconnector(
                connector_id=_connector_id,
                placement=scad.make_placement_rplacement(origin=_origin),
            ),
        )
    gear_train_base = _part
    print(
        f"base: volume={gear_train_base.body.get_volume():.1f} "
        f"connectors={','.join(gear_train_base.connector_ids())}"
    )
    return (gear_train_base,)


if __name__ == "__main__":
    app.run()

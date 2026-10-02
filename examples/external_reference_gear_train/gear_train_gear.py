# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "gear_train_gear"
# ///
"""A gear blank with one axis connector at its bottom center.

The gear train uses this one definition for both of its gears.
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- feature: gear-blank (build) ----
    gear_blank = scad.make_cylinder_rsolid(radius=4.0, height=3.0)
    return (gear_blank,)


@app.cell
def _(gear_blank):
    _body = scad.apply_tag(shape=gear_blank, tag="role.gear_train_gear")
    gear_train_gear = scad.add_connector_rpart(
        part=scad.make_part_rpart(part_id="gear_train_gear", body=_body),
        connector=scad.make_placement_connector_rconnector(
            connector_id="axis",
            placement=scad.make_placement_rplacement(origin=(0.0, 0.0, 0.0)),
        ),
    )
    print(
        f"gear: volume={gear_train_gear.body.get_volume():.3f} "
        f"faces={len(scad.ql.faces().resolve(gear_train_gear.body))}"
    )
    return (gear_train_gear,)


if __name__ == "__main__":
    app.run()

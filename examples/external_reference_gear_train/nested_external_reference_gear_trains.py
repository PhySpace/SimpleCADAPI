# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "nested_external_reference_gear_trains"
# ///
"""Two instances of the gear-train stage, side by side.

The stage is a nested assembly definition referenced twice; its constraints
are solved inside the stage, so this assembly only places the instances. The
right train's output axis is the product's public ``service_axis``.

    sca run examples/external_reference_gear_train/nested_external_reference_gear_trains.py
    uv run python examples/external_reference_gear_train/export.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    stage = scad.use("external_reference_gear_train.py")
    return (stage,)


@app.cell
def _(stage):
    _pair = scad.make_assembly_rassembly(
        assembly_id="nested_external_reference_gear_trains",
        name="Repeated nested gear-train definitions",
    )
    _pair = scad.add_component_rassembly(
        assembly=_pair,
        item=stage,
        component_id="train_left",
        placement=scad.identity_placement_rplacement(),
    )
    _pair = scad.add_component_rassembly(
        assembly=_pair,
        item=stage,
        component_id="train_right",
        placement=scad.make_placement_rplacement(origin=(50.0, 0.0, 0.0)),
    )
    nested_external_reference_gear_trains = scad.set_public_connector_rassembly(
        assembly=_pair,
        public_connector_id="service_axis",
        source_component_id="train_right",
        source_connector_id="output_axis",
    )
    return (nested_external_reference_gear_trains,)


if __name__ == "__main__":
    app.run()

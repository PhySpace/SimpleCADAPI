# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "external_reference_gear_train"
# ///
"""One gear-train stage: a base and two meshing gears.

The base and the gear are external references: each is its own notebook and
its own definition, and the gear definition is instanced twice. The stage
exposes the second gear's axis as its public ``output_axis``.
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    base = scad.use("gear_train_base.py")
    gear = scad.use("gear_train_gear.py")
    return base, gear


@app.cell
def _(base, gear):
    # Components start at the identity; the constraints place them.
    _identity = scad.identity_placement_rplacement()
    _stage = scad.make_assembly_rassembly(
        assembly_id="external_reference_gear_train",
        name="Two-axis external-reference gear train",
    )
    for _component_id, _item in (("base", base), ("gear_a", gear), ("gear_b", gear)):
        _stage = scad.add_component_rassembly(
            assembly=_stage, item=_item, component_id=_component_id, placement=_identity
        )
    stage_components = scad.ground_component_rassembly(assembly=_stage, component_id="base")
    return (stage_components,)


@app.cell
def _(stage_components):
    # Each gear turns on its base axis; the mesh couples them 4:8. Gear A is
    # driven to 30 degrees, so gear B turns -15.
    _base_left = scad.make_connector_ref_rconnectorref("base", "left_axis")
    _base_right = scad.make_connector_ref_rconnectorref("base", "right_axis")
    _gear_a = scad.make_connector_ref_rconnectorref("gear_a", "axis")
    _gear_b = scad.make_connector_ref_rconnectorref("gear_b", "axis")
    _stage = scad.add_revolute_constraint_rassembly(
        assembly=stage_components,
        constraint_id="support_a",
        connector_a=_base_left,
        connector_b=_gear_a,
        drive_angle_degrees=30.0,
    )
    _stage = scad.add_revolute_constraint_rassembly(
        assembly=_stage, constraint_id="support_b", connector_a=_base_right, connector_b=_gear_b
    )
    stage_constraints = scad.add_gear_constraint_rassembly(
        assembly=_stage,
        constraint_id="mesh",
        connector_a=_gear_a,
        connector_b=_gear_b,
        pitch_radius_a=4.0,
        pitch_radius_b=8.0,
    )
    return (stage_constraints,)


@app.cell
def _(stage_constraints):
    _solved = scad.solve_assembly_constraints_rassembly(assembly=stage_constraints)
    external_reference_gear_train = scad.set_public_connector_rassembly(
        assembly=_solved,
        public_connector_id="output_axis",
        source_component_id="gear_b",
        source_connector_id="axis",
    )
    return (external_reference_gear_train,)


if __name__ == "__main__":
    app.run()

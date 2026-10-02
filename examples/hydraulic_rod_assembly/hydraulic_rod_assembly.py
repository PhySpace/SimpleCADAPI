# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "hydraulic_rod_assembly"
# ///
"""Hydraulic cylinder: the piston rod slides in the outer sleeve.

The sleeve is grounded; a prismatic mate on the two ``slide_axis``
connectors carries the rod along +X with a 0..100 mm stroke.

    sca run examples/hydraulic_rod_assembly/hydraulic_rod_assembly.py
    uv run python examples/hydraulic_rod_assembly/export.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    outer_sleeve = scad.use("outer_sleeve.py")
    piston_rod = scad.use("piston_rod.py")
    return outer_sleeve, piston_rod


@app.cell
def _(outer_sleeve, piston_rod):
    # Both parts start at the identity; the mate places the rod.
    _identity = scad.identity_placement_rplacement()
    _assembly = scad.make_assembly_rassembly(
        assembly_id="hydraulic_rod_assembly", name="Hydraulic rod assembly"
    )
    _assembly = scad.add_component_rassembly(
        assembly=_assembly, item=outer_sleeve, component_id="outer_sleeve", placement=_identity
    )
    _assembly = scad.add_component_rassembly(
        assembly=_assembly, item=piston_rod, component_id="inner_piston_rod", placement=_identity
    )
    rod_components = scad.ground_component_rassembly(
        assembly=_assembly, component_id="outer_sleeve"
    )
    return (rod_components,)


@app.cell
def _(rod_components):
    rod_slide = scad.add_prismatic_constraint_rassembly(
        assembly=rod_components,
        constraint_id="rod_slide",
        connector_a=scad.make_connector_ref_rconnectorref(
            component_id="outer_sleeve", connector_id="slide_axis"
        ),
        connector_b=scad.make_connector_ref_rconnectorref(
            component_id="inner_piston_rod", connector_id="slide_axis"
        ),
        drive_distance=0.0,
        distance_limit=scad.make_scalar_limit_rscalarlimit(lower_value=0.0, upper_value=100.0),
    )
    return (rod_slide,)


@app.cell
def _(rod_slide):
    hydraulic_rod_assembly = scad.solve_assembly_constraints_rassembly(assembly=rod_slide)
    return (hydraulic_rod_assembly,)


if __name__ == "__main__":
    app.run()

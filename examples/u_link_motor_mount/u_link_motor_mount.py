# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "u-link-motor-mount-assembly"
# revision = "1.0.0"
# ///
"""u_link assembly: upper body + lower shell, shell fixed onto the split plane.

Both parts are modeled in install position, so both start at the identity and
the fixed constraint through the placement connectors (z axes -Y, origins on
the back_y plane) solves with zero residual.

    sca run examples/u_link_motor_mount/u_link_motor_mount.py
    uv run python examples/u_link_motor_mount/export.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    body = scad.use("u_link.py")
    shell = scad.use("shell.py")
    return body, shell


@app.cell
def _(body, shell):
    _identity = scad.identity_placement_rplacement()
    _assembly = scad.make_assembly_rassembly(
        assembly_id="u-link-motor-mount-assembly", name="U link body + shell"
    )
    _assembly = scad.add_component_rassembly(
        assembly=_assembly, item=body, component_id="body", placement=_identity,
        name="U link upper body",
    )
    _assembly = scad.add_component_rassembly(
        assembly=_assembly, item=shell, component_id="shell", placement=_identity,
        name="U link shell",
    )
    u_link_components = scad.ground_component_rassembly(assembly=_assembly, component_id="body")
    return (u_link_components,)


@app.cell
def _(u_link_components):
    u_link_fixed = scad.add_fixed_constraint_rassembly(
        assembly=u_link_components,
        constraint_id="shell_on_split",
        connector_a=scad.make_connector_ref_rconnectorref(
            component_id="body", connector_id="back_datum"),
        connector_b=scad.make_connector_ref_rconnectorref(
            component_id="shell", connector_id="shell_rim"),
    )
    return (u_link_fixed,)


@app.cell
def _(u_link_fixed):
    u_link_motor_mount = scad.solve_assembly_constraints_rassembly(
        assembly=u_link_fixed, strict=True
    )
    return (u_link_motor_mount,)


if __name__ == "__main__":
    app.run()

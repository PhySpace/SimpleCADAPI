# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "l-link-motor-mount-star3"
# revision = "1.0.0"
# ///
"""l_link assembly: upper body + shell + motor-2 adapter plate, one member per plate preset.

All three parts are modeled in install position -> identity placements; body grounded,
shell fixed on the split plane (split_datum <-> shell_rim, z -Y), plate fixed on mount
face 2 (mount2_datum <-> plate_back, z +X, x along key_phase -> the fixed constraint also
locks the three-spoke key phase). Motor interfaces are exposed as public connectors.

Family member id = ``dimensions.assembly_id(preset)``:

    sca run examples/l_link_motor_mount/l_link_motor_mount.py
    sca run examples/l_link_motor_mount/l_link_motor_mount.py --id l-link-motor-mount-center4 --set PRESET=center4
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from dimensions import PlatePreset, assembly_id, plate_part_id


@app.cell
def _():
    # ---- params: plate preset (family member) ----
    PRESET = "star3"
    return (PRESET,)


@app.cell
def _(PRESET):
    # ---- guard: the member id names its preset ----
    preset = PlatePreset(PRESET)
    assert scad.notebook_id() == assembly_id(preset), \
        f"notebook id {scad.notebook_id()!r} must be {assembly_id(preset)!r} for preset {PRESET!r}"
    return (preset,)


@app.cell
def _(PRESET, preset):
    body = scad.use("l_link.py")
    shell = scad.use("shell.py")
    plate = scad.use("adapter_plate.py", id=plate_part_id(preset), PRESET=PRESET)
    return body, plate, shell


@app.cell
def _(body, plate, preset, shell):
    _identity = scad.identity_placement_rplacement()
    _assembly = scad.make_assembly_rassembly(
        assembly_id=scad.notebook_id(), name=f"L link body + shell + adapter plate ({preset.value})")
    for _component_id, _part, _name in (("body", body, "L link upper body"), ("shell", shell, "L link shell"),
                                        ("plate", plate, f"Motor 2 adapter plate ({preset.value})")):
        _assembly = scad.add_component_rassembly(
            assembly=_assembly, item=_part, component_id=_component_id, placement=_identity, name=_name)
    l_link_components = scad.ground_component_rassembly(assembly=_assembly, component_id="body")
    return (l_link_components,)


@app.cell
def _(l_link_components):
    _assembly = l_link_components
    for _constraint_id, _a, _b in (("shell_on_split", ("body", "split_datum"), ("shell", "shell_rim")),
                                   ("plate_on_mount2", ("body", "mount2_datum"), ("plate", "plate_back"))):
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly, constraint_id=_constraint_id,
            connector_a=scad.make_connector_ref_rconnectorref(component_id=_a[0], connector_id=_a[1]),
            connector_b=scad.make_connector_ref_rconnectorref(component_id=_b[0], connector_id=_b[1]))
    l_link_fixed = _assembly
    return (l_link_fixed,)


@app.cell
def _(l_link_fixed):
    _assembly = l_link_fixed
    for _public_id, _component_id in (("motor_left", "body"), ("motor_right", "plate")):
        _assembly = scad.set_public_connector_rassembly(
            assembly=_assembly, public_connector_id=_public_id,
            source_component_id=_component_id, source_connector_id=_public_id)
    l_link_motor_mount = scad.solve_assembly_constraints_rassembly(assembly=_assembly, strict=True)
    return (l_link_motor_mount,)


if __name__ == "__main__":
    app.run()

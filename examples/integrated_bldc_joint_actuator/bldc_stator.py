# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "bldc_12_slot_stator"
# ///
"""12-slot stator sub-assembly: the laminated core plus twelve winding packs.

One winding-pack definition is placed on each slot datum of the core and
fixed there (varnish and potting). The core is grounded; the sub-assembly
exposes only the press-fit axis.

    sca run examples/integrated_bldc_joint_actuator/bldc_stator.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import connector_ref, z_rotation_placement
    from dimensions import MOTOR_SLOT_COUNT


@app.cell
def _():
    stator_core = scad.use("stator_core.py")
    slot_winding = scad.use("slot_winding.py")
    return slot_winding, stator_core


@app.cell
def _(slot_winding, stator_core):
    # The grounded core, then one winding pack per slot, potted to its datum.
    _assembly = scad.make_assembly_rassembly(
        assembly_id="bldc_12_slot_stator",
        name="12-slot laminated stator with discrete copper slot packs",
    )
    _assembly = scad.add_component_rassembly(
        assembly=_assembly,
        item=stator_core,
        component_id="stator_core",
        placement=scad.identity_placement_rplacement(),
        name="Laminated stator core",
    )
    _assembly = scad.ground_component_rassembly(assembly=_assembly, component_id="stator_core")
    for _index in range(MOTOR_SLOT_COUNT):
        _component_id = f"winding_{_index + 1:02d}"
        _assembly = scad.add_component_rassembly(
            assembly=_assembly,
            item=slot_winding,
            component_id=_component_id,
            placement=z_rotation_placement(
                origin=(0.0, 0.0, 0.0), angle_degrees=360.0 * _index / MOTOR_SLOT_COUNT
            ),
            name=f"Slot winding pack {_index + 1}",
        )
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly,
            constraint_id=f"{_component_id}_potted_to_core",
            connector_a=connector_ref(component_id="stator_core", connector_id=_component_id),
            connector_b=connector_ref(component_id=_component_id, connector_id="mount_axis"),
            name=f"Winding {_index + 1} varnish and potting retention",
        )
    stator_windings = _assembly
    return (stator_windings,)


@app.cell
def _(stator_windings):
    _assembly = scad.set_public_connector_rassembly(
        assembly=stator_windings,
        public_connector_id="shell_axis",
        source_component_id="stator_core",
        source_connector_id="shell_axis",
        name="Stator press-fit axis",
    )
    bldc_12_slot_stator = scad.solve_assembly_constraints_rassembly(assembly=_assembly, strict=True)
    return (bldc_12_slot_stator,)


if __name__ == "__main__":
    app.run()

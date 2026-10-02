# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "integrated_circular_motor_controller"
# ///
"""Circular ESC sub-assembly: PCB, six MOSFETs and two rear terminal blocks.

The six bridge MOSFETs are soldered to the top of the board. The 3-pin
phase terminal and the 4-pin power/CAN terminal hang below it, behind the
rear-cover apertures. Both terminals come from one part family.

    sca run examples/integrated_bldc_joint_actuator/integrated_controller.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import connector_ref, mosfet_center_xy
    from dimensions import (
        MOSFET_ANGLES,
        PCB_BOTTOM_Z,
        PCB_THICKNESS,
        PHASE_TERMINAL_CENTER,
        POWER_CAN_TERMINAL_CENTER,
    )


@app.cell
def _():
    controller_pcb = scad.use("controller_pcb.py")
    power_mosfet = scad.use("power_mosfet.py")
    return controller_pcb, power_mosfet


@app.cell
def _():
    phase_terminal = scad.use(
        "terminal_block.py",
        id="three_phase_terminal",
        PIN_COUNT=3,
        TERMINAL_NAME="Three-position motor phase terminal",
    )
    power_can_terminal = scad.use(
        "terminal_block.py",
        id="power_can_terminal",
        PIN_COUNT=4,
        TERMINAL_NAME="Four-position DC power and CAN terminal",
    )
    return phase_terminal, power_can_terminal


@app.cell
def _(controller_pcb, power_mosfet):
    # The grounded board, then each MOSFET soldered to its pad datum.
    _assembly = scad.make_assembly_rassembly(
        assembly_id="integrated_circular_motor_controller",
        name="44.4 mm circular integrated BLDC controller",
    )
    _assembly = scad.add_component_rassembly(
        assembly=_assembly,
        item=controller_pcb,
        component_id="pcb",
        placement=scad.identity_placement_rplacement(),
        name="Circular controller PCB",
    )
    _assembly = scad.ground_component_rassembly(assembly=_assembly, component_id="pcb")
    for _index in range(len(MOSFET_ANGLES)):
        _component_id = f"mosfet_{_index + 1}"
        _assembly = scad.add_component_rassembly(
            assembly=_assembly,
            item=power_mosfet,
            component_id=_component_id,
            placement=scad.make_placement_rplacement(
                origin=(*mosfet_center_xy(index=_index), PCB_BOTTOM_Z + PCB_THICKNESS)
            ),
            name=f"Power MOSFET package {_index + 1}",
        )
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly,
            constraint_id=f"{_component_id}_soldered",
            connector_a=connector_ref(component_id="pcb", connector_id=_component_id),
            connector_b=connector_ref(component_id=_component_id, connector_id="solder_axis"),
            name=f"MOSFET {_index + 1} solder attachment",
        )
    controller_bridge = _assembly
    return (controller_bridge,)


@app.cell
def _(controller_bridge, phase_terminal, power_can_terminal):
    # Both terminal blocks, soldered and screwed to their datums under the board.
    _assembly = controller_bridge
    for _component_id, _item, _center in (
        ("phase_terminal", phase_terminal, PHASE_TERMINAL_CENTER),
        ("power_can_terminal", power_can_terminal, POWER_CAN_TERMINAL_CENTER),
    ):
        _assembly = scad.add_component_rassembly(
            assembly=_assembly,
            item=_item,
            component_id=_component_id,
            placement=scad.make_placement_rplacement(origin=(_center[0], _center[1], -38.5)),
            name=_item.name,
        )
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly,
            constraint_id=f"{_component_id}_soldered",
            connector_a=connector_ref(component_id="pcb", connector_id=_component_id),
            connector_b=connector_ref(component_id=_component_id, connector_id="solder_axis"),
            name=f"{_component_id.replace('_', ' ')} solder and screw retention",
        )
    controller_terminals = _assembly
    return (controller_terminals,)


@app.cell
def _(controller_terminals):
    _assembly = controller_terminals
    for _connector_id in ("cover_axis", "phase_access", "power_can_access"):
        _assembly = scad.set_public_connector_rassembly(
            assembly=_assembly,
            public_connector_id=_connector_id,
            source_component_id="pcb",
            source_connector_id=_connector_id,
            name=_connector_id.replace("_", " "),
        )
    integrated_circular_motor_controller = scad.solve_assembly_constraints_rassembly(
        assembly=_assembly, strict=True
    )
    return (integrated_circular_motor_controller,)


if __name__ == "__main__":
    app.run()

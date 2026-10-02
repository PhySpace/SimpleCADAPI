# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "direct_coupled_bldc_rotor"
# ///
"""14-pole rotor sub-assembly: the rotor/shaft/sun part plus fourteen magnets.

One magnet definition is bonded to each pole datum of the rotor core. The
core is grounded; the sub-assembly exposes the rotation axis, both bearing
seats, and the stage-1 sun axis.

    sca run examples/integrated_bldc_joint_actuator/bldc_rotor.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import connector_ref, z_rotation_placement
    from dimensions import MOTOR_POLE_COUNT


@app.cell
def _():
    rotor_core_shaft_sun = scad.use("rotor_core_shaft_sun.py")
    rotor_magnet = scad.use("rotor_magnet.py")
    return rotor_core_shaft_sun, rotor_magnet


@app.cell
def _(rotor_core_shaft_sun, rotor_magnet):
    # The grounded rotor core, then one magnet per pole, bonded to its datum.
    _assembly = scad.make_assembly_rassembly(
        assembly_id="direct_coupled_bldc_rotor",
        name="14-pole BLDC rotor with integrated stage-1 sun shaft",
    )
    _assembly = scad.add_component_rassembly(
        assembly=_assembly,
        item=rotor_core_shaft_sun,
        component_id="rotor_core_shaft_sun",
        placement=scad.identity_placement_rplacement(),
        name="Rotor back iron, shaft, and stage-1 sun",
    )
    _assembly = scad.ground_component_rassembly(assembly=_assembly, component_id="rotor_core_shaft_sun")
    for _index in range(MOTOR_POLE_COUNT):
        _component_id = f"magnet_{_index + 1:02d}"
        _assembly = scad.add_component_rassembly(
            assembly=_assembly,
            item=rotor_magnet,
            component_id=_component_id,
            placement=z_rotation_placement(
                origin=(0.0, 0.0, 0.0), angle_degrees=360.0 * _index / MOTOR_POLE_COUNT
            ),
            name=f"Bonded rotor magnet {_index + 1}",
        )
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly,
            constraint_id=f"{_component_id}_bonded_to_rotor",
            connector_a=connector_ref(component_id="rotor_core_shaft_sun", connector_id=_component_id),
            connector_b=connector_ref(component_id=_component_id, connector_id="bond_axis"),
            name=f"Magnet {_index + 1} adhesive and sleeve retention",
        )
    rotor_magnets = _assembly
    return (rotor_magnets,)


@app.cell
def _(rotor_magnets):
    _assembly = rotor_magnets
    for _connector_id in ("rotor_axis", "rear_bearing_axis", "front_bearing_axis", "stage1_sun_axis"):
        _assembly = scad.set_public_connector_rassembly(
            assembly=_assembly,
            public_connector_id=_connector_id,
            source_component_id="rotor_core_shaft_sun",
            source_connector_id=_connector_id,
            name=_connector_id.replace("_", " "),
        )
    direct_coupled_bldc_rotor = scad.solve_assembly_constraints_rassembly(assembly=_assembly, strict=True)
    return (direct_coupled_bldc_rotor,)


if __name__ == "__main__":
    app.run()

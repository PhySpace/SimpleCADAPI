# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "integrated_50mm_bldc_joint_actuator"
# ///
"""50 mm BLDC joint actuator: 12-slot/14-pole motor, 20:1 reducer, circular ESC.

Power path: the controller drives the stator, which turns the rotor. The
rotor shaft carries the stage-1 sun. Stage-1 planets (fixed ring) turn the
stage-1 carrier, which is also the stage-2 sun. Stage-2 planets (fixed
ring) turn the output carrier and its six-hole output flange.

The housing parts, the gears and the carriers are part notebooks. The
per-stage ring and planet are part families (``id=`` + ``STAGE=``). The
stator, rotor and controller are sub-assembly notebooks. Five standard ball
bearings sit at the rotor, interstage and output seats and in each of the
six planets; all have their balls fused to the outer ring. The solve is
strict.

    sca run examples/integrated_bldc_joint_actuator/integrated_bldc_joint_actuator.py
    uv run python examples/integrated_bldc_joint_actuator/export_all.py  # package, STEP, FCStd, MJCF
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from bearings import build_actuator_bearing_rassembly, coaxial_bearing_placement, planet_bearing_placement
    from common import connector_ref, planet_center_xy, z_rotation_placement
    from dimensions import (
        FRONT_MOTOR_BEARING,
        FRONT_MOTOR_BEARING_CENTER_Z,
        INTERSTAGE_BEARING,
        INTERSTAGE_BEARING_CENTER_Z,
        OUTPUT_BEARING,
        OUTPUT_BEARING_1_CENTER_Z,
        OUTPUT_BEARING_2_CENTER_Z,
        PLANET_BEARING,
        PLANET_COUNT,
        REAR_BEARING_CENTER_Z,
        REAR_MOTOR_BEARING,
        STAGE_1,
        STAGE_2,
        StageSpec,
    )
    from materials import make_actuator_material_rmaterial


@app.function
def planet_placement(stage: StageSpec, index: int) -> scad.Placement:
    """Place one planet on its carrier pin, phased to mesh with sun and ring.

    The spin turns the planet by its carrier angle plus half a tooth, so a
    tooth gap faces the sun at every pin.
    """
    x, y = planet_center_xy(stage=stage, index=index)
    spin = 360.0 * index / PLANET_COUNT + 180.0 - 180.0 / stage.planet_teeth
    return z_rotation_placement(origin=(x, y, stage.bottom_z), angle_degrees=spin)


@app.function
def add_stage_mesh(
    assembly: scad.Assembly,
    stage: StageSpec,
    driver: scad.ConnectorRef,
    ring_component_id: str,
    carrier_component_id: str,
) -> scad.Assembly:
    """Add one stage's planet revolutes and sun/ring meshes.

    Each planet spins on its carrier pin. The sun (``driver``) drives it by
    an external gear mesh. The fixed ring constrains it by an internal mesh,
    modeled as a same-direction belt between the pitch circles.
    """
    for index in range(PLANET_COUNT):
        i = index + 1
        planet_axis = connector_ref(component_id=f"{stage.stage_id}_planet_{i}", connector_id="axis")
        assembly = scad.add_revolute_constraint_rassembly(
            assembly=assembly,
            constraint_id=f"{stage.stage_id}_planet_{i}_revolute",
            connector_a=connector_ref(component_id=carrier_component_id, connector_id=f"planet_{i}_axis"),
            connector_b=planet_axis,
            drive_angle_degrees=None,
            angle_limit=None,
            name=f"{stage.label} planet {i} bearing axis",
        )
        assembly = scad.add_gear_constraint_rassembly(
            assembly=assembly,
            constraint_id=f"{stage.stage_id}_sun_planet_{i}_mesh",
            connector_a=driver,
            connector_b=planet_axis,
            pitch_radius_a=stage.sun_pitch_radius,
            pitch_radius_b=stage.planet_pitch_radius,
            phase_offset=None,
            name=f"{stage.label} sun to planet {i} external mesh",
        )
        assembly = scad.add_belt_constraint_rassembly(
            assembly=assembly,
            constraint_id=f"{stage.stage_id}_ring_planet_{i}_internal_mesh",
            connector_a=connector_ref(component_id=ring_component_id, connector_id="axis"),
            connector_b=planet_axis,
            pulley_radius_a=stage.ring_pitch_radius,
            pulley_radius_b=stage.planet_pitch_radius,
            phase_offset=None,
            name=f"{stage.label} fixed-ring to planet {i} internal mesh",
        )
    return assembly


@app.cell
def _():
    reducer_housing = scad.use("reducer_housing.py")
    motor_shell = scad.use("motor_shell.py")
    rear_bearing_spider = scad.use("rear_bearing_spider.py")
    rear_electronics_cover = scad.use("rear_electronics_cover.py")
    output_bearing_cap = scad.use("output_bearing_cap.py")
    return motor_shell, output_bearing_cap, rear_bearing_spider, rear_electronics_cover, reducer_housing


@app.cell
def _():
    stator = scad.use("bldc_stator.py")
    rotor = scad.use("bldc_rotor.py")
    controller = scad.use("integrated_controller.py")
    return controller, rotor, stator


@app.cell
def _():
    stage1_ring = scad.use("ring_gear.py", id="stage1_fixed_ring", STAGE="stage1")
    stage1_planet = scad.use("planet_gear.py", id="stage1_reusable_planet", STAGE="stage1")
    stage1_carrier = scad.use("stage1_carrier_sun.py")
    stage2_ring = scad.use("ring_gear.py", id="stage2_fixed_ring", STAGE="stage2")
    stage2_planet = scad.use("planet_gear.py", id="stage2_reusable_planet", STAGE="stage2")
    output_carrier = scad.use("output_carrier_flange.py")
    return output_carrier, stage1_carrier, stage1_planet, stage1_ring, stage2_planet, stage2_ring


@app.cell
def _():
    # Five standard bearing sizes; the planet size is reused at all six pins.
    _material = make_actuator_material_rmaterial(key="gear")
    rear_motor_bearing = build_actuator_bearing_rassembly(
        assembly_id="rear_motor_8x16x5", spec=REAR_MOTOR_BEARING, material=_material
    )
    front_motor_bearing = build_actuator_bearing_rassembly(
        assembly_id="front_motor_8x19x6", spec=FRONT_MOTOR_BEARING, material=_material
    )
    interstage_bearing = build_actuator_bearing_rassembly(
        assembly_id="interstage_5x10x3", spec=INTERSTAGE_BEARING, material=_material
    )
    planet_bearing = build_actuator_bearing_rassembly(
        assembly_id="planet_3x6x3", spec=PLANET_BEARING, material=_material
    )
    output_bearing = build_actuator_bearing_rassembly(
        assembly_id="output_16x24x5", spec=OUTPUT_BEARING, material=_material
    )
    return front_motor_bearing, interstage_bearing, output_bearing, planet_bearing, rear_motor_bearing


@app.cell
def _(
    controller,
    motor_shell,
    output_bearing_cap,
    output_carrier,
    rear_bearing_spider,
    rear_electronics_cover,
    reducer_housing,
    rotor,
    stage1_carrier,
    stage1_planet,
    stage1_ring,
    stage2_planet,
    stage2_ring,
    stator,
):
    # Housing, motor, controller and carriers are modeled in place; the rings
    # are lifted to their stage planes and the planets set on their pins.
    _assembly = scad.make_assembly_rassembly(
        assembly_id="integrated_50mm_bldc_joint_actuator",
        name="50 mm 12-slot/14-pole BLDC joint actuator with 20:1 reducer and circular ESC",
    )
    _identity = scad.identity_placement_rplacement()
    for _component_id, _item, _placement, _name in (
        ("reducer_housing", reducer_housing, _identity, "Fixed reducer housing"),
        ("motor_shell", motor_shell, _identity, "Fixed BLDC shell"),
        ("rear_bearing_spider", rear_bearing_spider, _identity, "Rear motor-bearing spider"),
        ("rear_electronics_cover", rear_electronics_cover, _identity, "Rear controller cover"),
        ("output_bearing_cap", output_bearing_cap, _identity, "Output bearing cap"),
        ("stator", stator, _identity, "12-slot fixed stator"),
        ("rotor", rotor, _identity, "14-pole rotor and direct sun shaft"),
        ("controller", controller, _identity, "Circular integrated controller"),
        ("stage1_carrier", stage1_carrier, _identity, "Stage 1 carrier and stage 2 sun"),
        ("output_carrier", output_carrier, _identity, "Stage 2 carrier and output flange"),
        (
            "stage1_ring",
            stage1_ring,
            scad.make_placement_rplacement(origin=(0.0, 0.0, STAGE_1.bottom_z)),
            "Stage 1 fixed ring insert",
        ),
        (
            "stage2_ring",
            stage2_ring,
            scad.make_placement_rplacement(origin=(0.0, 0.0, STAGE_2.bottom_z)),
            "Stage 2 fixed ring insert",
        ),
    ):
        _assembly = scad.add_component_rassembly(
            assembly=_assembly, item=_item, component_id=_component_id, placement=_placement, name=_name
        )
    for _stage, _planet in ((STAGE_1, stage1_planet), (STAGE_2, stage2_planet)):
        for _index in range(PLANET_COUNT):
            _assembly = scad.add_component_rassembly(
                assembly=_assembly,
                item=_planet,
                component_id=f"{_stage.stage_id}_planet_{_index + 1}",
                placement=planet_placement(_stage, _index),
                name=f"{_stage.label} planet {_index + 1}",
            )
    actuator_parts = _assembly
    return (actuator_parts,)


@app.cell
def _(
    actuator_parts,
    front_motor_bearing,
    interstage_bearing,
    output_bearing,
    planet_bearing,
    rear_motor_bearing,
):
    # Coaxial rotor, interstage and output bearings, then one bearing
    # centered in each planet.
    _assembly = actuator_parts
    for _component_id, _item, _center_z, _name in (
        ("rear_motor_bearing", rear_motor_bearing, REAR_BEARING_CENTER_Z, "Rear rotor bearing"),
        ("front_motor_bearing", front_motor_bearing, FRONT_MOTOR_BEARING_CENTER_Z, "Front rotor bearing"),
        ("interstage_bearing", interstage_bearing, INTERSTAGE_BEARING_CENTER_Z, "Stage 1 carrier support bearing"),
        ("output_bearing_1", output_bearing, OUTPUT_BEARING_1_CENTER_Z, "Rear output bearing"),
        ("output_bearing_2", output_bearing, OUTPUT_BEARING_2_CENTER_Z, "Front output bearing"),
    ):
        _assembly = scad.add_component_rassembly(
            assembly=_assembly,
            item=_item,
            component_id=_component_id,
            placement=coaxial_bearing_placement(center_z=_center_z),
            name=_name,
        )
    for _stage in (STAGE_1, STAGE_2):
        for _index in range(PLANET_COUNT):
            _assembly = scad.add_component_rassembly(
                assembly=_assembly,
                item=planet_bearing,
                component_id=f"{_stage.stage_id}_planet_bearing_{_index + 1}",
                placement=planet_bearing_placement(stage=_stage, index=_index),
                name=f"{_stage.label} planet bearing {_index + 1}",
            )
    actuator_bearings = _assembly
    return (actuator_bearings,)


@app.cell
def _(actuator_bearings):
    # Stable module datums for the robot integrator; component ids stay private.
    _assembly = actuator_bearings
    for _public_id, _component_id, _connector_id, _name in (
        ("case_clamp_axis", "reducer_housing", "case_clamp_axis", "External split-clamp datum"),
        ("case_mount_axis", "output_bearing_cap", "case_mount_axis", "Fixed actuator case datum"),
        ("output_link_axis", "output_carrier", "output_link_axis", "Rotating six-hole output flange"),
        ("phase_terminal_access", "controller", "phase_access", "Rear phase-terminal service datum"),
        ("power_can_terminal_access", "controller", "power_can_access", "Rear power/CAN service datum"),
    ):
        _assembly = scad.set_public_connector_rassembly(
            assembly=_assembly,
            public_connector_id=_public_id,
            source_component_id=_component_id,
            source_connector_id=_connector_id,
            name=_name,
        )
    actuator_interface = _assembly
    return (actuator_interface,)


@app.cell
def _(actuator_interface):
    # The reducer housing and both rings are grounded; the shell stack, the
    # stator, the controller and the output cap are fixed to the housing.
    _assembly = actuator_interface
    for _component_id in ("reducer_housing", "stage1_ring", "stage2_ring"):
        _assembly = scad.ground_component_rassembly(assembly=_assembly, component_id=_component_id)
    for _constraint_id, _a, _a_connector, _b, _b_connector in (
        ("motor_shell_to_reducer_housing", "reducer_housing", "motor_mount_axis", "motor_shell", "reducer_mount_axis"),
        ("rear_spider_to_motor_shell", "motor_shell", "rear_spider_axis", "rear_bearing_spider", "shell_axis"),
        ("rear_cover_to_motor_shell", "motor_shell", "rear_cover_axis", "rear_electronics_cover", "shell_axis"),
        ("stator_to_motor_shell", "motor_shell", "stator_axis", "stator", "shell_axis"),
        ("controller_to_rear_cover", "rear_electronics_cover", "pcb_axis", "controller", "cover_axis"),
        ("stage1_ring_fixed", "reducer_housing", "stage1_ring_axis", "stage1_ring", "axis"),
        ("stage2_ring_fixed", "reducer_housing", "stage2_ring_axis", "stage2_ring", "axis"),
        ("output_cap_to_reducer_housing", "reducer_housing", "output_cap_axis", "output_bearing_cap", "housing_axis"),
    ):
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly,
            constraint_id=_constraint_id,
            connector_a=connector_ref(component_id=_a, connector_id=_a_connector),
            connector_b=connector_ref(component_id=_b, connector_id=_b_connector),
            name=_constraint_id.replace("_", " "),
        )
    actuator_fixed = _assembly
    return (actuator_fixed,)


@app.cell
def _(actuator_fixed):
    # The rotor and both carriers turn in the reducer housing.
    _assembly = actuator_fixed
    for _constraint_id, _a_connector, _b, _b_connector in (
        ("rotor_revolute", "front_motor_bearing_axis", "rotor", "front_bearing_axis"),
        ("stage1_carrier_revolute", "stage1_carrier_axis", "stage1_carrier", "carrier_axis"),
        ("output_carrier_revolute", "stage2_carrier_axis", "output_carrier", "carrier_axis"),
    ):
        _assembly = scad.add_revolute_constraint_rassembly(
            assembly=_assembly,
            constraint_id=_constraint_id,
            connector_a=connector_ref(component_id="reducer_housing", connector_id=_a_connector),
            connector_b=connector_ref(component_id=_b, connector_id=_b_connector),
            drive_angle_degrees=0.0,
            angle_limit=None,
            name=_constraint_id.replace("_", " "),
        )
    actuator_shafts = _assembly
    return (actuator_shafts,)


@app.cell
def _(actuator_shafts):
    # Stage 1 is driven by the rotor's sun, stage 2 by the stage 1 carrier.
    _assembly = add_stage_mesh(
        actuator_shafts,
        STAGE_1,
        connector_ref(component_id="rotor", connector_id="front_bearing_axis"),
        "stage1_ring",
        "stage1_carrier",
    )
    actuator_meshes = add_stage_mesh(
        _assembly,
        STAGE_2,
        connector_ref(component_id="stage1_carrier", connector_id="carrier_axis"),
        "stage2_ring",
        "output_carrier",
    )
    return (actuator_meshes,)


@app.cell
def _(actuator_meshes):
    # Each bearing's outer ring is fixed to its seat, its inner ring to the
    # shaft or carrier pin it supports. The bearing's internal revolute
    # absorbs the spin.
    _assembly = actuator_meshes
    for _constraint_id, _a, _a_connector, _b, _b_connector in (
        ("rear_bearing_outer_to_spider", "rear_bearing_spider", "bearing_axis", "rear_motor_bearing", "outer_axis"),
        ("rear_bearing_inner_to_rotor", "rotor", "rear_bearing_axis", "rear_motor_bearing", "inner_axis"),
        (
            "front_bearing_outer_to_housing",
            "reducer_housing",
            "front_motor_bearing_axis",
            "front_motor_bearing",
            "outer_axis",
        ),
        ("front_bearing_inner_to_rotor", "rotor", "front_bearing_axis", "front_motor_bearing", "inner_axis"),
        (
            "interstage_bearing_outer_to_housing",
            "reducer_housing",
            "interstage_bearing_axis",
            "interstage_bearing",
            "outer_axis",
        ),
        (
            "interstage_bearing_inner_to_carrier",
            "stage1_carrier",
            "interstage_bearing_axis",
            "interstage_bearing",
            "inner_axis",
        ),
        ("output_bearing_1_outer_to_cap", "output_bearing_cap", "bearing_1_axis", "output_bearing_1", "outer_axis"),
        ("output_bearing_1_inner_to_carrier", "output_carrier", "bearing_1_axis", "output_bearing_1", "inner_axis"),
        ("output_bearing_2_outer_to_cap", "output_bearing_cap", "bearing_2_axis", "output_bearing_2", "outer_axis"),
        ("output_bearing_2_inner_to_carrier", "output_carrier", "bearing_2_axis", "output_bearing_2", "inner_axis"),
    ):
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly,
            constraint_id=_constraint_id,
            connector_a=connector_ref(component_id=_a, connector_id=_a_connector),
            connector_b=connector_ref(component_id=_b, connector_id=_b_connector),
            name=_constraint_id.replace("_", " "),
        )
    for _stage, _carrier_id in ((STAGE_1, "stage1_carrier"), (STAGE_2, "output_carrier")):
        for _index in range(PLANET_COUNT):
            _planet_id = f"{_stage.stage_id}_planet_{_index + 1}"
            _bearing_id = f"{_stage.stage_id}_planet_bearing_{_index + 1}"
            _assembly = scad.add_fixed_constraint_rassembly(
                assembly=_assembly,
                constraint_id=f"{_bearing_id}_outer_to_planet",
                connector_a=connector_ref(component_id=_planet_id, connector_id="bearing_axis"),
                connector_b=connector_ref(component_id=_bearing_id, connector_id="outer_axis"),
                name=f"{_stage.label} planet {_index + 1} bearing outer-ring fit",
            )
            _assembly = scad.add_fixed_constraint_rassembly(
                assembly=_assembly,
                constraint_id=f"{_bearing_id}_inner_to_pin",
                connector_a=connector_ref(component_id=_carrier_id, connector_id=f"planet_{_index + 1}_bearing_axis"),
                connector_b=connector_ref(component_id=_bearing_id, connector_id="inner_axis"),
                name=f"{_stage.label} planet {_index + 1} bearing inner-ring pin fit",
            )
    actuator_bearing_seats = _assembly
    return (actuator_bearing_seats,)


@app.cell
def _(actuator_bearing_seats):
    integrated_50mm_bldc_joint_actuator = scad.solve_assembly_constraints_rassembly(
        assembly=actuator_bearing_seats, strict=True
    )
    return (integrated_50mm_bldc_joint_actuator,)


if __name__ == "__main__":
    app.run()

# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "compact_two_stage_planetary_reducer"
# ///
"""Compact two-stage herringbone planetary reducer, 20:1, 58.8 mm OD.

Power path: input flange -> input shaft -> stage 1 sun -> three stage 1
planets (fixed stage 1 ring) -> stage 1 carrier, whose shaft is the stage 2
sun's drive -> three stage 2 planets (fixed stage 2 ring) -> stage 2 carrier
-> output flange. Both rings are grounded in the housing.

Every part is its own notebook; the per-stage gears and carriers are part
families used once per stage (``id=`` + ``STAGE=``). One standard micro
radial ball bearing sits at nine places: three coaxial shaft seats and the
six planet bores. Gear meshes are gear (sun-planet) and belt (ring-planet)
constraints on the planet revolutes; the solve is strict.

    sca run examples/compact_two_stage_planetary_reducer/compact_two_stage_planetary_reducer.py
    uv run python examples/compact_two_stage_planetary_reducer/export.py       # package, STEP, FCStd
    uv run python examples/compact_two_stage_planetary_reducer/export_mjcf.py  # MuJoCo
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import make_z_rotation_rplacement
    from dimensions import (
        INPUT_BEARING_Z,
        INTERMEDIATE_BEARING_Z,
        OUTPUT_BEARING_Z,
        PLANET_COUNT,
        STAGE_1,
        STAGE_2,
        UNIVERSAL_RADIAL_BEARING,
        StageSpec,
    )


@app.function
def ref(component_id: str, connector_id: str) -> scad.ConnectorRef:
    """A connector on one component of the reducer."""
    return scad.make_connector_ref_rconnectorref(component_id=component_id, connector_id=connector_id)


@app.function
def stage_plane(stage: StageSpec) -> scad.Placement:
    """Lift a gear built on z = 0 to its stage's gear plane."""
    return scad.make_placement_rplacement(origin=(0.0, 0.0, stage.bottom_z))


@app.function
def planet_placement(stage: StageSpec, planet_index: int) -> scad.Placement:
    """Place one planet on its carrier pin, phased to mesh with sun and ring.

    The spin turns the planet by its carrier angle plus half a tooth, so a
    tooth gap faces the sun at every pin.
    """
    x, y = stage.planet_center(planet_index)
    spin = stage.planet_angle(planet_index) + 180.0 - 180.0 / stage.planet_teeth
    return make_z_rotation_rplacement(origin=(x, y, stage.bottom_z), angle_degrees=spin)


@app.function
def add_stage_mesh(
    assembly: scad.Assembly,
    stage: StageSpec,
    driver: scad.ConnectorRef,
    ring_component_id: str,
    carrier_component_id: str,
) -> scad.Assembly:
    """Add one stage's planet revolutes and sun/ring meshes.

    Each planet spins on its carrier pin; the sun (``driver``) drives it by
    an external gear mesh and the fixed ring constrains it by an internal
    mesh, modeled as a same-direction belt between the pitch circles.
    """
    for index in range(PLANET_COUNT):
        i = index + 1
        planet_axis = ref(f"{stage.stage_id}_planet_{i}", "axis")
        assembly = scad.add_revolute_constraint_rassembly(
            assembly=assembly,
            constraint_id=f"{stage.stage_id}_planet_{i}_revolute",
            connector_a=ref(carrier_component_id, f"planet_{i}_axis"),
            connector_b=planet_axis,
            drive_angle_degrees=None,
            angle_limit=None,
            name=f"{stage.label} planet {i} pin bearing axis",
        )
        assembly = scad.add_gear_constraint_rassembly(
            assembly=assembly,
            constraint_id=f"{stage.stage_id}_sun_planet_{i}_external_mesh",
            connector_a=driver,
            connector_b=planet_axis,
            pitch_radius_a=stage.sun_pitch_radius,
            pitch_radius_b=stage.planet_pitch_radius,
            phase_offset=None,
            name=f"{stage.label} external sun to planet {i} mesh",
        )
        assembly = scad.add_belt_constraint_rassembly(
            assembly=assembly,
            constraint_id=f"{stage.stage_id}_ring_planet_{i}_internal_mesh",
            connector_a=ref(ring_component_id, "axis"),
            connector_b=planet_axis,
            pulley_radius_a=stage.ring_pitch_radius,
            pulley_radius_b=stage.planet_pitch_radius,
            phase_offset=None,
            name=f"{stage.label} internal fixed-ring to planet {i} mesh",
        )
    return assembly


@app.cell
def _():
    housing = scad.use("housing.py")
    input_flange = scad.use("input_flange.py")
    output_flange = scad.use("output_flange.py")
    input_shaft = scad.use("input_shaft.py")
    return housing, input_flange, input_shaft, output_flange


@app.cell
def _():
    stage1_ring = scad.use("ring_gear.py", id="stage1_ring_gear", STAGE="stage1")
    stage1_sun = scad.use("sun_gear.py", id="stage1_sun_gear", STAGE="stage1")
    stage1_planet = scad.use("planet_gear.py", id="stage1_planet_gear", STAGE="stage1")
    stage1_carrier = scad.use("carrier.py", id="stage1_carrier", STAGE="stage1")
    return stage1_carrier, stage1_planet, stage1_ring, stage1_sun


@app.cell
def _():
    stage2_ring = scad.use("ring_gear.py", id="stage2_ring_gear", STAGE="stage2")
    stage2_sun = scad.use("sun_gear.py", id="stage2_sun_gear", STAGE="stage2")
    stage2_planet = scad.use("planet_gear.py", id="stage2_planet_gear", STAGE="stage2")
    stage2_carrier = scad.use("carrier.py", id="stage2_carrier", STAGE="stage2")
    return stage2_carrier, stage2_planet, stage2_ring, stage2_sun


@app.cell
def _():
    # One standard bearing definition, reused at all nine seats. Separate
    # (unfused) balls keep it a real sub-assembly: rings plus eight balls.
    _spec = UNIVERSAL_RADIAL_BEARING
    radial_bearing = scad.std.bearing.build_ball_bearing(
        bore_diameter=_spec.bore_diameter,
        outer_diameter=_spec.outer_diameter,
        bearing_width=_spec.width,
        ball_diameter=_spec.ball_diameter,
        ball_count=_spec.ball_count,
        raceway_clearance=_spec.raceway_clearance,
        edge_chamfer=_spec.edge_chamfer,
        assembly_id="micro_radial_ball_bearing",
        fuse_rolling_elements=False,
    ).assembly
    return (radial_bearing,)


@app.cell
def _(
    housing,
    input_flange,
    input_shaft,
    output_flange,
    stage1_carrier,
    stage1_planet,
    stage1_ring,
    stage1_sun,
    stage2_carrier,
    stage2_planet,
    stage2_ring,
    stage2_sun,
):
    # Housing, flanges, shaft and carriers are modeled in place; the gears
    # are lifted to their stage planes and the planets set on their pins.
    _assembly = scad.make_assembly_rassembly(
        assembly_id="compact_two_stage_planetary_reducer",
        name="58.8 mm OD 20:1 through-bolted herringbone planetary actuator reducer",
    )
    _identity = scad.identity_placement_rplacement()
    for _component_id, _item, _placement, _name in (
        ("housing", housing, _identity, "Fixed outer housing"),
        ("input_flange", input_flange, _identity, "Rotating input flange"),
        ("output_flange", output_flange, _identity, "Rotating output flange"),
        ("input_shaft", input_shaft, _identity, "Input shaft"),
        ("stage1_carrier", stage1_carrier, _identity, "Stage 1 carrier and stage 2 sun shaft"),
        ("stage2_carrier", stage2_carrier, _identity, "Stage 2 carrier and output shaft"),
        ("stage1_ring", stage1_ring, stage_plane(STAGE_1), "Stage 1 fixed ring"),
        ("stage1_sun", stage1_sun, stage_plane(STAGE_1), "Stage 1 sun"),
        ("stage2_ring", stage2_ring, stage_plane(STAGE_2), "Stage 2 fixed ring"),
        ("stage2_sun", stage2_sun, stage_plane(STAGE_2), "Stage 2 sun"),
    ):
        _assembly = scad.add_component_rassembly(
            assembly=_assembly, item=_item, component_id=_component_id, placement=_placement, name=_name
        )
    for _index in range(PLANET_COUNT):
        for _stage, _planet in ((STAGE_1, stage1_planet), (STAGE_2, stage2_planet)):
            _assembly = scad.add_component_rassembly(
                assembly=_assembly,
                item=_planet,
                component_id=f"{_stage.stage_id}_planet_{_index + 1}",
                placement=planet_placement(_stage, _index),
                name=f"{_stage.label} planet gear {_index + 1}",
            )
    reducer_parts = _assembly
    return (reducer_parts,)


@app.cell
def _(radial_bearing, reducer_parts):
    # Coaxial shaft bearings, then one bearing centered in each planet.
    _assembly = reducer_parts
    for _component_id, _z, _name in (
        ("input_bearing", INPUT_BEARING_Z, "Input shaft radial ball bearing"),
        ("intermediate_bearing", INTERMEDIATE_BEARING_Z, "Intermediate shaft radial ball bearing"),
        ("output_bearing", OUTPUT_BEARING_Z, "Output shaft radial ball bearing"),
    ):
        _assembly = scad.add_component_rassembly(
            assembly=_assembly,
            item=radial_bearing,
            component_id=_component_id,
            placement=make_z_rotation_rplacement(origin=(0.0, 0.0, _z), angle_degrees=0.0),
            name=_name,
        )
    for _stage in (STAGE_1, STAGE_2):
        for _index in range(PLANET_COUNT):
            _assembly = scad.add_component_rassembly(
                assembly=_assembly,
                item=radial_bearing,
                component_id=f"{_stage.stage_id}_planet_bearing_{_index + 1}",
                placement=make_z_rotation_rplacement(
                    origin=(*_stage.planet_center(_index), _stage.mid_z), angle_degrees=0.0
                ),
                name=f"{_stage.label} planet {_index + 1} ball bearing",
            )
    reducer_bearings = _assembly
    return (reducer_bearings,)


@app.cell
def _(reducer_bearings):
    # Stable module datums for the actuator's integrator; component ids stay private.
    _assembly = reducer_bearings
    for _public_id, _component_id, _connector_id, _name in (
        ("housing_mount_axis", "housing", "output_axis", "Fixed case mounting datum"),
        ("input_motor_axis", "input_flange", "axis", "Input flange datum for motor can"),
        ("output_link_axis", "output_flange", "axis", "Output flange datum for driven link"),
    ):
        _assembly = scad.set_public_connector_rassembly(
            assembly=_assembly,
            public_connector_id=_public_id,
            source_component_id=_component_id,
            source_connector_id=_connector_id,
            name=_name,
        )
    reducer_interface = _assembly
    return (reducer_interface,)


@app.cell
def _(reducer_interface):
    # The housing and both rings are grounded; the rigid joints of the power
    # path (ring in housing, flange on shaft, sun on its driver) are fixed.
    _assembly = reducer_interface
    for _component_id in ("housing", "stage1_ring", "stage2_ring"):
        _assembly = scad.ground_component_rassembly(assembly=_assembly, component_id=_component_id)
    for _constraint_id, _a, _b in (
        ("stage1_ring_fixed", ref("housing", "stage1_axis"), ref("stage1_ring", "axis")),
        ("stage2_ring_fixed", ref("housing", "stage2_axis"), ref("stage2_ring", "axis")),
        ("input_flange_to_shaft", ref("input_flange", "axis"), ref("input_shaft", "flange_axis")),
        ("stage1_sun_to_input_shaft", ref("input_shaft", "sun_axis"), ref("stage1_sun", "axis")),
        ("stage2_sun_to_stage1_carrier", ref("stage1_carrier", "stage2_sun_axis"), ref("stage2_sun", "axis")),
        ("output_flange_to_stage2_carrier", ref("stage2_carrier", "output_axis"), ref("output_flange", "axis")),
    ):
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly,
            constraint_id=_constraint_id,
            connector_a=_a,
            connector_b=_b,
            name=_constraint_id.replace("_", " "),
        )
    reducer_fixed = _assembly
    return (reducer_fixed,)


@app.cell
def _(reducer_fixed):
    # The three coaxial shafts of the power path turn in the housing.
    _assembly = reducer_fixed
    for _constraint_id, _a, _b in (
        ("input_shaft_revolute", ref("housing", "input_axis"), ref("input_shaft", "sun_axis")),
        ("stage1_carrier_revolute", ref("housing", "stage2_axis"), ref("stage1_carrier", "carrier_axis")),
        ("stage2_carrier_revolute", ref("housing", "output_axis"), ref("stage2_carrier", "carrier_axis")),
    ):
        _assembly = scad.add_revolute_constraint_rassembly(
            assembly=_assembly,
            constraint_id=_constraint_id,
            connector_a=_a,
            connector_b=_b,
            drive_angle_degrees=0.0,
            angle_limit=None,
            name=_constraint_id.replace("_", " "),
        )
    reducer_shafts = _assembly
    return (reducer_shafts,)


@app.cell
def _(reducer_shafts):
    # Stage 1 is driven by the input shaft, stage 2 by the stage 1 carrier.
    _assembly = add_stage_mesh(
        reducer_shafts, STAGE_1, ref("input_shaft", "sun_axis"), "stage1_ring", "stage1_carrier"
    )
    reducer_meshes = add_stage_mesh(
        _assembly, STAGE_2, ref("stage1_carrier", "carrier_axis"), "stage2_ring", "stage2_carrier"
    )
    return (reducer_meshes,)


@app.cell
def _(reducer_meshes):
    # Each bearing's outer ring is fixed to its seat, its inner ring to the
    # shaft or carrier pin it supports.
    _assembly = reducer_meshes
    for _constraint_id, _a, _b in (
        ("input_bearing_outer_to_housing", ref("housing", "input_bearing_axis"), ref("input_bearing", "outer_axis")),
        ("input_bearing_inner_to_shaft", ref("input_shaft", "input_bearing_axis"), ref("input_bearing", "inner_axis")),
        (
            "intermediate_bearing_outer_to_housing",
            ref("housing", "intermediate_bearing_axis"),
            ref("intermediate_bearing", "outer_axis"),
        ),
        (
            "intermediate_bearing_inner_to_stage1_carrier",
            ref("stage1_carrier", "intermediate_bearing_axis"),
            ref("intermediate_bearing", "inner_axis"),
        ),
        ("output_bearing_outer_to_housing", ref("housing", "output_bearing_axis"), ref("output_bearing", "outer_axis")),
        (
            "output_bearing_inner_to_stage2_carrier",
            ref("stage2_carrier", "output_bearing_axis"),
            ref("output_bearing", "inner_axis"),
        ),
    ):
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly,
            constraint_id=_constraint_id,
            connector_a=_a,
            connector_b=_b,
            name=_constraint_id.replace("_", " "),
        )
    for _stage in (STAGE_1, STAGE_2):
        for _index in range(PLANET_COUNT):
            _planet_id = f"{_stage.stage_id}_planet_{_index + 1}"
            _bearing_id = f"{_stage.stage_id}_planet_bearing_{_index + 1}"
            _assembly = scad.add_fixed_constraint_rassembly(
                assembly=_assembly,
                constraint_id=f"{_bearing_id}_outer_to_planet",
                connector_a=ref(_planet_id, "bearing_axis"),
                connector_b=ref(_bearing_id, "outer_axis"),
                name=f"{_bearing_id} outer ring to planet gear bore",
            )
            _assembly = scad.add_fixed_constraint_rassembly(
                assembly=_assembly,
                constraint_id=f"{_bearing_id}_inner_to_carrier_pin",
                connector_a=ref(f"{_stage.stage_id}_carrier", f"planet_{_index + 1}_bearing_axis"),
                connector_b=ref(_bearing_id, "inner_axis"),
                name=f"{_bearing_id} inner ring to carrier pin",
            )
    reducer_bearing_seats = _assembly
    return (reducer_bearing_seats,)


@app.cell
def _(reducer_bearing_seats):
    compact_two_stage_planetary_reducer = scad.solve_assembly_constraints_rassembly(
        assembly=reducer_bearing_seats, strict=True
    )
    return (compact_two_stage_planetary_reducer,)


if __name__ == "__main__":
    app.run()

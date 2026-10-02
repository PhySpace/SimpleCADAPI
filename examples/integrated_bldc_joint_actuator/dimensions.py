"""Design constants for the integrated 50 mm BLDC joint actuator."""

from __future__ import annotations

from dataclasses import dataclass


PACKAGE_RADIUS = 25.0
PACKAGE_STRUCTURAL_BOTTOM_Z = -37.0
PACKAGE_TOP_Z = 40.3

MOTOR_SLOT_COUNT = 12
MOTOR_POLE_COUNT = 14
MOTOR_SHELL_INNER_RADIUS = 23.20
MOTOR_SHELL_BOTTOM_Z = -34.0
MOTOR_SHELL_TOP_Z = -6.0
MOTOR_STATOR_BOTTOM_Z = -24.5
MOTOR_STATOR_TOP_Z = -8.5
MOTOR_STATOR_OUTER_RADIUS = 23.20
MOTOR_STATOR_YOKE_INNER_RADIUS = 20.20
MOTOR_STATOR_TOOTH_INNER_RADIUS = 15.00
MOTOR_STATOR_TOOTH_WIDTH = 2.60
MOTOR_ROTOR_BOTTOM_Z = -25.0
MOTOR_ROTOR_TOP_Z = -7.5
MOTOR_ROTOR_BACKIRON_RADIUS = 13.50
MOTOR_MAGNET_OUTER_RADIUS = 14.70
MOTOR_MAGNET_TANGENTIAL_WIDTH = 5.0
MOTOR_SHAFT_RADIUS = 4.0
MOTOR_AIR_GAP = MOTOR_STATOR_TOOTH_INNER_RADIUS - MOTOR_MAGNET_OUTER_RADIUS

REAR_COVER_BOTTOM_Z = -37.0
REAR_COVER_THICKNESS = 3.0
PCB_BOTTOM_Z = -33.6
PCB_THICKNESS = 1.6
PCB_RADIUS = 22.2
PCB_CENTER_BORE_RADIUS = 5.0
PCB_STANDOFF_PCD = 33.0
PCB_MOUNT_HOLE_RADIUS = 1.10
PHASE_TERMINAL_CENTER = (-11.0, 0.0)
POWER_CAN_TERMINAL_CENTER = (11.0, 0.0)
MOSFET_CENTER_RADIUS = 13.2
MOSFET_ANGLES = (22.5, 67.5, 112.5, 202.5, 247.5, 292.5)
REAR_COLUMN_PCD = 40.6
REAR_COLUMN_RADIUS = 3.2
REAR_SPIDER_BOSS_RADIUS = 2.9
REAR_FASTENER_HOLE_RADIUS = 1.35
REAR_BEARING_CENTER_Z = -29.0
FRONT_MOTOR_BEARING_CENTER_Z = -2.5

REDUCER_HOUSING_BOTTOM_Z = -6.0
REDUCER_HOUSING_FRONT_Z = 24.3
REDUCER_HOUSING_INNER_RADIUS = 22.80
RING_INSERT_OUTER_RADIUS = 22.82
MOTOR_INTERFACE_PCD = 43.0
OUTPUT_CAP_INTERFACE_PCD = 43.0
M3_CLEARANCE_RADIUS = 1.60
HOUSING_INTERFACE_LAND_INNER_RADIUS = 18.50

PLANET_COUNT = 3
PRESSURE_ANGLE = 20.0
HELIX_ANGLE = 24.0
BACKLASH = 0.03
ADDENDUM_FACTOR = 1.0
CLEARANCE_FACTOR = 0.25
RING_RIM_THICKNESS = 1.80
RING_SUPPORT_OVERLAP = 0.30
GEAR_HEIGHT = 5.50

STAGE1_CARRIER_BOTTOM_Z = 8.20
STAGE1_CARRIER_THICKNESS = 2.50
STAGE1_PIN_RADIUS = 1.48
STAGE1_PIN_BOTTOM_Z = 2.25
STAGE1_HUB_RADIUS = 4.2
STAGE1_PAD_RADIUS = 4.0
STAGE1_ARM_WIDTH = 3.2
INTERSTAGE_SHAFT_RADIUS = 2.50

STAGE2_CARRIER_BOTTOM_Z = 20.20
STAGE2_CARRIER_THICKNESS = 3.0
STAGE2_PIN_RADIUS = 1.48
STAGE2_PIN_BOTTOM_Z = 14.25
STAGE2_HUB_RADIUS = 8.8
STAGE2_PAD_RADIUS = 4.1
STAGE2_ARM_WIDTH = 3.5
OUTPUT_SHAFT_RADIUS = 7.98

OUTPUT_CAP_BOTTOM_Z = 24.3
OUTPUT_CAP_CARTRIDGE_TOP_Z = 34.8
OUTPUT_CAP_TOP_Z = 36.3
OUTPUT_BEARING_1_CENTER_Z = 26.8
OUTPUT_BEARING_2_CENTER_Z = 31.8
OUTPUT_FLANGE_BOTTOM_Z = 35.3
OUTPUT_FLANGE_TOP_Z = 38.8
OUTPUT_FLANGE_RADIUS = 22.4
OUTPUT_LINK_HOLE_PCD = 34.0
OUTPUT_LINK_BOLT_COUNT = 6
OUTPUT_LINK_BOLT_ANGLES_DEGREES = (30.0, 90.0, 150.0, 210.0, 270.0, 330.0)
OUTPUT_LINK_TAP_RADIUS = 1.25
OUTPUT_LINK_THREAD_DEPTH = 3.0
OUTPUT_REGISTER_RADIUS = OUTPUT_SHAFT_RADIUS
OUTPUT_REGISTER_HEIGHT = PACKAGE_TOP_Z - OUTPUT_FLANGE_TOP_Z
OUTPUT_CASE_CLAMP_CENTER_Z = 20.0


@dataclass(frozen=True)
class StageSpec:
    """One fixed-ring planetary stage."""

    stage_id: str
    label: str
    module: float
    sun_teeth: int
    planet_teeth: int
    bottom_z: float

    @property
    def ring_teeth(self) -> int:
        return self.sun_teeth + 2 * self.planet_teeth

    @property
    def top_z(self) -> float:
        return self.bottom_z + GEAR_HEIGHT

    @property
    def mid_z(self) -> float:
        return self.bottom_z + GEAR_HEIGHT / 2.0

    @property
    def sun_pitch_radius(self) -> float:
        return self.module * self.sun_teeth / 2.0

    @property
    def planet_pitch_radius(self) -> float:
        return self.module * self.planet_teeth / 2.0

    @property
    def ring_pitch_radius(self) -> float:
        return self.module * self.ring_teeth / 2.0

    @property
    def planet_center_radius(self) -> float:
        return self.sun_pitch_radius + self.planet_pitch_radius

    @property
    def fixed_ring_ratio(self) -> float:
        return 1.0 + self.ring_teeth / self.sun_teeth

    @property
    def ring_outer_radius(self) -> float:
        return (
            self.ring_pitch_radius
            + self.module * (ADDENDUM_FACTOR + CLEARANCE_FACTOR)
            + RING_RIM_THICKNESS
        )


@dataclass(frozen=True)
class BearingSpec:
    """Catalog-style radial ball bearing dimensions."""

    bore_diameter: float
    outer_diameter: float
    width: float
    ball_diameter: float
    ball_count: int


STAGE_1 = StageSpec(
    stage_id="stage1",
    label="Stage 1",
    module=0.80,
    sun_teeth=15,
    planet_teeth=15,
    bottom_z=2.0,
)
STAGE_2 = StageSpec(
    stage_id="stage2",
    label="Stage 2",
    module=0.55,
    sun_teeth=18,
    planet_teeth=27,
    bottom_z=14.0,
)

REAR_MOTOR_BEARING = BearingSpec(8.0, 16.0, 5.0, 2.0, 8)
FRONT_MOTOR_BEARING = BearingSpec(8.0, 19.0, 6.0, 2.4, 9)
INTERSTAGE_BEARING = BearingSpec(5.0, 10.0, 3.0, 1.0, 8)
PLANET_BEARING = BearingSpec(3.0, 6.0, 3.0, 0.7, 8)
OUTPUT_BEARING = BearingSpec(16.0, 24.0, 5.0, 2.5, 12)
REAR_SPIDER_BOTTOM_Z = REAR_BEARING_CENTER_Z - REAR_MOTOR_BEARING.width / 2.0
INTERSTAGE_BEARING_CENTER_Z = (
    STAGE1_CARRIER_BOTTOM_Z + STAGE1_CARRIER_THICKNESS + STAGE_2.bottom_z
) / 2.0

TOTAL_REDUCTION = STAGE_1.fixed_ring_ratio * STAGE_2.fixed_ring_ratio

# Stage specs by id: the ``STAGE`` parameter of the gear family notebooks.
STAGES = {stage.stage_id: stage for stage in (STAGE_1, STAGE_2)}


def validate_design_dimensions() -> None:
    """Fail early if a packaging or minimum-ligament invariant is broken."""

    assert MOTOR_AIR_GAP >= 0.30
    assert MOTOR_STATOR_OUTER_RADIUS == MOTOR_SHELL_INNER_RADIUS
    assert abs(PACKAGE_RADIUS - MOTOR_SHELL_INNER_RADIUS - 1.80) < 1.0e-9
    assert abs(PACKAGE_RADIUS - REDUCER_HOUSING_INNER_RADIUS - 2.20) < 1.0e-9
    assert max(STAGE_1.ring_outer_radius, STAGE_2.ring_outer_radius) < RING_INSERT_OUTER_RADIUS
    assert RING_INSERT_OUTER_RADIUS > REDUCER_HOUSING_INNER_RADIUS
    assert (
        MOTOR_INTERFACE_PCD / 2.0
        - M3_CLEARANCE_RADIUS
        - HOUSING_INTERFACE_LAND_INNER_RADIUS
        >= 1.40 - 1.0e-9
    )
    assert REAR_SPIDER_BOSS_RADIUS - REAR_FASTENER_HOLE_RADIUS >= 1.50
    assert REAR_COLUMN_RADIUS > REAR_SPIDER_BOSS_RADIUS
    assert REAR_SPIDER_BOTTOM_Z > MOTOR_SHELL_BOTTOM_Z
    assert OUTPUT_FLANGE_RADIUS <= PACKAGE_RADIUS
    assert OUTPUT_LINK_HOLE_PCD / 2.0 + OUTPUT_LINK_TAP_RADIUS < OUTPUT_FLANGE_RADIUS
    assert OUTPUT_LINK_THREAD_DEPTH < OUTPUT_FLANGE_TOP_Z - OUTPUT_FLANGE_BOTTOM_Z
    assert OUTPUT_REGISTER_HEIGHT >= 1.5
    assert OUTPUT_REGISTER_RADIUS < OUTPUT_LINK_HOLE_PCD / 2.0 - OUTPUT_LINK_TAP_RADIUS
    assert REDUCER_HOUSING_BOTTOM_Z < OUTPUT_CASE_CLAMP_CENTER_Z < REDUCER_HOUSING_FRONT_Z
    assert OUTPUT_BEARING_2_CENTER_Z - OUTPUT_BEARING_1_CENTER_Z == OUTPUT_BEARING.width
    assert abs(TOTAL_REDUCTION - 20.0) < 1.0e-9
    assert (STAGE_1.sun_teeth + STAGE_1.ring_teeth) % PLANET_COUNT == 0
    assert (STAGE_2.sun_teeth + STAGE_2.ring_teeth) % PLANET_COUNT == 0
    assert (
        INTERSTAGE_BEARING_CENTER_Z - INTERSTAGE_BEARING.width / 2.0
        > STAGE1_CARRIER_BOTTOM_Z + STAGE1_CARRIER_THICKNESS
    )
    assert (
        INTERSTAGE_BEARING_CENTER_Z + INTERSTAGE_BEARING.width / 2.0
        < STAGE_2.bottom_z
    )
    print(
        "design_dimensions: "
        f"diameter={PACKAGE_RADIUS * 2.0:.1f} structural_length="
        f"{PACKAGE_TOP_Z - PACKAGE_STRUCTURAL_BOTTOM_Z:.1f} air_gap={MOTOR_AIR_GAP:.2f} "
        f"ratio={TOTAL_REDUCTION:.1f}"
    )

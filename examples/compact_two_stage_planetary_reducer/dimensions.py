"""Design constants for the compact two-stage planetary reducer.

A plain module: every part notebook imports its numbers from here, so a
change to one constant re-runs exactly the notebooks that read it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


PLANET_COUNT = 3
MODULE = 0.75
PRESSURE_ANGLE = 20.0
HELIX_ANGLE = 27.0
GEAR_HEIGHT = 4.60
ADDENDUM_FACTOR = 1.0
CLEARANCE_FACTOR = 0.25
RING_RIM_THICKNESS = 1.90
FIXED_RING_HOUSING_SUPPORT_OVERLAP = 0.30
BACKLASH = 0.02

HOUSING_OUTER_RADIUS = 29.4
# The original 50 mm reducer envelope did not leave enough radial room for real
# M3-class housing screws outside the ring gear.  The practical actuator package
# grows to about 59 mm OD so through-bolt bosses have enough wall around the head
# counterbores instead of being cosmetic pin holes.
HOUSING_BODY_OUTER_RADIUS = 24.2
HOUSING_INNER_RADIUS = 21.70
HOUSING_DATUM_INNER_RADIUS = 20.95
HOUSING_DATUM_OUTER_RADIUS = 21.85
HOUSING_BOTTOM_Z = -15.0
HOUSING_HEIGHT = 30.0

# Output/input end-cap details seen on real joint actuators.  The case fasteners
# are modeled as real through holes through the housing stack, not as cosmetic
# front-face pockets; the larger envelope is the cost of giving M3-class screws
# enough boss diameter outside the planetary ring gear.
HOUSING_FRONT_FLANGE_THICKNESS = 3.0
HOUSING_REAR_FLANGE_THICKNESS = 3.0
HOUSING_END_FLANGE_OUTER_RADIUS = 24.2

# The outer mounting structure is four continuous sector pads, each carrying
# three full-length screws.  This is closer to the reference actuator than twelve
# isolated round ears: it preserves a scalloped circular silhouette, gives each
# fastener real surrounding material, and leaves service gaps between quarters.
HOUSING_MOUNT_SECTOR_COUNT = 4
HOUSING_MOUNT_HOLES_PER_SECTOR = 3
HOUSING_MOUNT_HOLE_COUNT = HOUSING_MOUNT_SECTOR_COUNT * HOUSING_MOUNT_HOLES_PER_SECTOR
HOUSING_MOUNT_PAD_INNER_RADIUS = 23.6
HOUSING_MOUNT_PAD_OUTER_RADIUS = HOUSING_OUTER_RADIUS
HOUSING_MOUNT_SECTOR_GAP_WIDTH = 5.0
HOUSING_MOUNT_SECTOR_CENTER_OFFSET_DEGREES = 45.0
HOUSING_MOUNT_HOLE_OFFSET_DEGREES = 18.0
HOUSING_MOUNT_HOLE_CIRCLE_RADIUS = 26.4
HOUSING_MOUNT_HOLE_DIAMETER = 3.0
HOUSING_MOUNT_COUNTERBORE_DIAMETER = 5.6
HOUSING_MOUNT_COUNTERBORE_DEPTH = 1.2

# A sealed output needs a small controlled radial gap instead of the previous
# large empty annulus between the rotating flange and fixed housing.  The front
# flange bore is the fixed labyrinth lip; it is not a separate part because that
# would create a fully contained boolean feature with no extra assembly value.
OUTPUT_SEAL_BORE_RADIUS = 20.65
OUTPUT_SEAL_RUNNING_CLEARANCE = 0.30
INPUT_SEAL_RUNNING_CLEARANCE = 0.30

INPUT_FLANGE_BOTTOM_Z = -15.0
INPUT_FLANGE_THICKNESS = 2.0
INPUT_FLANGE_BOSS_HEIGHT = 1.0
INPUT_FLANGE_TOP_Z = INPUT_FLANGE_BOTTOM_Z + INPUT_FLANGE_THICKNESS + INPUT_FLANGE_BOSS_HEIGHT
INPUT_FLANGE_OUTER_DIAMETER = 23.0
INPUT_FLANGE_INNER_DIAMETER = 3.0
INPUT_FLANGE_BOSS_OUTER_DIAMETER = 8.0
INPUT_FLANGE_HOLE_DIAMETER = 1.6
INPUT_FLANGE_HOLE_CIRCLE_DIAMETER = 17.0
INPUT_FLANGE_HOLE_COUNT = 6
INPUT_FLANGE_HOLE_COUNTERBORE_DIAMETER = 3.0
INPUT_FLANGE_HOLE_COUNTERBORE_DEPTH = 0.45
INPUT_SEAL_BORE_RADIUS = INPUT_FLANGE_OUTER_DIAMETER / 2.0 + INPUT_SEAL_RUNNING_CLEARANCE

OUTPUT_FLANGE_BOTTOM_Z = 12.0
OUTPUT_FLANGE_THICKNESS = 2.4
OUTPUT_FLANGE_BOSS_HEIGHT = 0.6
OUTPUT_FLANGE_TOP_Z = OUTPUT_FLANGE_BOTTOM_Z + OUTPUT_FLANGE_THICKNESS + OUTPUT_FLANGE_BOSS_HEIGHT
OUTPUT_FLANGE_OUTER_DIAMETER = 40.7
OUTPUT_FLANGE_INNER_DIAMETER = 3.4
OUTPUT_FLANGE_BOSS_OUTER_DIAMETER = 12.8
OUTPUT_FLANGE_HOLE_DIAMETER = 2.0
OUTPUT_FLANGE_HOLE_CIRCLE_DIAMETER = 30.0
OUTPUT_FLANGE_HOLE_COUNTERBORE_DIAMETER = 3.2
OUTPUT_FLANGE_HOLE_COUNTERBORE_DEPTH = 0.45

# The raised segmented register is not decorative.  Real actuator output flanges
# often use raised islands so the mating link can have matching recesses for fast
# angular indexing and shear load location before the screws are tightened.
OUTPUT_FLANGE_REGISTER_INNER_DIAMETER = 22.0
OUTPUT_FLANGE_REGISTER_OUTER_DIAMETER = 35.0
OUTPUT_FLANGE_REGISTER_HEIGHT = 0.45
OUTPUT_FLANGE_REGISTER_PAD_COUNT = 3
OUTPUT_FLANGE_REGISTER_GAP_WIDTH = 3.1
OUTPUT_FLANGE_HOLES_PER_PAD = 2
OUTPUT_FLANGE_HOLE_OFFSET_DEGREES = 18.0
OUTPUT_FLANGE_HOLE_COUNT = OUTPUT_FLANGE_REGISTER_PAD_COUNT * OUTPUT_FLANGE_HOLES_PER_PAD
OUTPUT_FLANGE_CENTER_FASTENER_COUNT = 3
OUTPUT_FLANGE_CENTER_FASTENER_CIRCLE_DIAMETER = 10.5
OUTPUT_FLANGE_CENTER_FASTENER_DIAMETER = 1.2
OUTPUT_FLANGE_CENTER_COUNTERBORE_DIAMETER = 2.1
OUTPUT_FLANGE_CENTER_COUNTERBORE_DEPTH = 0.35

INPUT_SHAFT_RADIUS = 1.45
STAGE1_CARRIER_SHAFT_RADIUS = 1.35
OUTPUT_SHAFT_RADIUS = 1.50

INPUT_BEARING_Z = -11.0
INTERMEDIATE_BEARING_Z = 0.0
OUTPUT_BEARING_Z = 10.8


@dataclass(frozen=True)
class BearingSpec:
    """A small radial ball bearing package."""

    bore_diameter: float
    outer_diameter: float
    width: float
    ball_diameter: float
    ball_count: int
    raceway_clearance: float = 0.03
    edge_chamfer: float = 0.0


# A single reusable 3.2 x 6.6 x 2.0 mm bearing sits at all nine friction
# locations: the three coaxial shaft seats and the six planet bores.
UNIVERSAL_RADIAL_BEARING = BearingSpec(
    bore_diameter=3.2,
    outer_diameter=6.6,
    width=2.0,
    ball_diameter=0.55,
    ball_count=8,
)


@dataclass(frozen=True)
class StageSpec:
    """A tooth-count and axial-location spec for one planetary stage."""

    stage_id: str
    label: str
    sun_teeth: int
    planet_teeth: int
    bottom_z: float
    sun_helix_angle: float
    sun_bore_radius: float
    planet_bearing: BearingSpec

    @property
    def ring_teeth(self) -> int:
        return self.sun_teeth + 2 * self.planet_teeth

    @property
    def planet_helix_angle(self) -> float:
        return -self.sun_helix_angle

    @property
    def ring_helix_angle(self) -> float:
        return self.planet_helix_angle

    @property
    def gear_height(self) -> float:
        return GEAR_HEIGHT

    @property
    def top_z(self) -> float:
        return self.bottom_z + self.gear_height

    @property
    def mid_z(self) -> float:
        return self.bottom_z + self.gear_height / 2.0

    @property
    def sun_pitch_radius(self) -> float:
        return MODULE * self.sun_teeth / 2.0

    @property
    def planet_pitch_radius(self) -> float:
        return MODULE * self.planet_teeth / 2.0

    @property
    def ring_pitch_radius(self) -> float:
        return MODULE * self.ring_teeth / 2.0

    @property
    def planet_center_radius(self) -> float:
        return MODULE * (self.sun_teeth + self.planet_teeth) / 2.0

    @property
    def fixed_ring_ratio(self) -> float:
        return 1.0 + self.ring_teeth / self.sun_teeth

    @property
    def ring_outer_radius(self) -> float:
        tooth_root_allowance = MODULE * (ADDENDUM_FACTOR + CLEARANCE_FACTOR)
        return self.ring_pitch_radius + tooth_root_allowance + RING_RIM_THICKNESS

    def planet_angle(self, planet_index: int) -> float:
        """Carrier angle of one planet, in degrees."""
        return 360.0 * planet_index / PLANET_COUNT

    def planet_center(self, planet_index: int) -> tuple[float, float]:
        """XY center of one planet (and of its carrier pin)."""
        angle = math.radians(self.planet_angle(planet_index))
        return (
            self.planet_center_radius * math.cos(angle),
            self.planet_center_radius * math.sin(angle),
        )


@dataclass(frozen=True)
class CarrierSpec:
    """The plate, pins and coaxial drive shaft of one stage carrier.

    The plate sits above the stage's gear plane; the pins hang down into the
    planets, and the central shaft runs up to the next element of the power
    path (the stage 2 sun for stage 1, the output flange for stage 2).
    """

    plate_bottom_z: float
    plate_thickness: float
    pin_bottom_z: float
    pin_radius: float
    pin_land_radius: float
    hub_radius: float
    arm_width: float
    pad_radius: float
    shaft_radius: float
    shaft_top_z: float
    drive_connector_id: str
    shaft_bearing_connector_id: str
    shaft_bearing_z: float
    shaft_bearing_name: str


STAGE_1 = StageSpec(
    stage_id="stage1",
    label="Stage 1",
    sun_teeth=12,
    planet_teeth=18,
    bottom_z=-8.40,
    sun_helix_angle=HELIX_ANGLE,
    sun_bore_radius=1.56,
    planet_bearing=UNIVERSAL_RADIAL_BEARING,
)
STAGE_2 = StageSpec(
    stage_id="stage2",
    label="Stage 2",
    sun_teeth=12,
    planet_teeth=12,
    bottom_z=1.20,
    sun_helix_angle=HELIX_ANGLE,
    sun_bore_radius=1.43,
    planet_bearing=UNIVERSAL_RADIAL_BEARING,
)
# The part families (ring/sun/planet gear, carrier) take a stage key.
STAGES = {stage.stage_id: stage for stage in (STAGE_1, STAGE_2)}

CARRIERS = {
    "stage1": CarrierSpec(
        plate_bottom_z=-3.25,
        plate_thickness=1.65,
        pin_bottom_z=-8.15,
        pin_radius=1.10,
        pin_land_radius=1.18,
        hub_radius=3.40,
        arm_width=2.50,
        pad_radius=4.10,
        shaft_radius=STAGE1_CARRIER_SHAFT_RADIUS,
        shaft_top_z=STAGE_2.top_z,
        drive_connector_id="stage2_sun_axis",
        shaft_bearing_connector_id="intermediate_bearing_axis",
        shaft_bearing_z=INTERMEDIATE_BEARING_Z,
        shaft_bearing_name="Intermediate bearing shaft seat axis",
    ),
    "stage2": CarrierSpec(
        plate_bottom_z=6.45,
        plate_thickness=1.65,
        pin_bottom_z=1.45,
        pin_radius=0.82,
        pin_land_radius=0.93,
        hub_radius=3.35,
        arm_width=2.35,
        pad_radius=3.20,
        shaft_radius=OUTPUT_SHAFT_RADIUS,
        shaft_top_z=OUTPUT_FLANGE_TOP_Z,
        drive_connector_id="output_axis",
        shaft_bearing_connector_id="output_bearing_axis",
        shaft_bearing_z=OUTPUT_BEARING_Z,
        shaft_bearing_name="Output bearing shaft seat axis",
    ),
}

TOTAL_REDUCTION = STAGE_1.fixed_ring_ratio * STAGE_2.fixed_ring_ratio

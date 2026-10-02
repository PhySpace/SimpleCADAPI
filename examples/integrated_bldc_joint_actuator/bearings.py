"""Standard bearing factories and coaxial/planet placements.

A plain module (no cells): the assembly notebook calls these in its bearing
cell, and ``test/test_example_model_contract.py`` imports the factory.
"""

from __future__ import annotations

import simplecadapi as scad

from common import planet_center_xy
from dimensions import PLANET_COUNT, BearingSpec, StageSpec


def build_actuator_bearing_rassembly(*,
assembly_id: str,
spec: BearingSpec,
material: scad.Material,) -> scad.Assembly:
    """One standard ball-bearing sub-assembly with its balls fused to the outer ring.

    The rings are separate parts over the bearing's internal revolute, and
    the nested definition grounds its outer ring; the actuator fixes both
    rings to their seats, so the revolute absorbs the shaft spin.
    """

    return scad.std.bearing.build_ball_bearing(
        assembly_id=assembly_id,
        bore_diameter=spec.bore_diameter,
        outer_diameter=spec.outer_diameter,
        bearing_width=spec.width,
        ball_diameter=spec.ball_diameter,
        ball_count=spec.ball_count,
        raceway_clearance=0.0,
        edge_chamfer=0.0,
        fuse_rolling_elements=True,
        rolling_element_fuse_overlap=0.03,
        material=material,
    ).assembly


def coaxial_bearing_placement(*, center_z: float) -> scad.Placement:
    """Place a standard bearing center plane on the actuator Z axis."""

    return scad.make_placement_rplacement(origin=(0.0, 0.0, center_z))


def planet_bearing_placement(*, stage: StageSpec, index: int) -> scad.Placement:
    """Place a standard planet bearing at the gear midplane."""

    if index < 0 or index >= PLANET_COUNT:
        raise ValueError(f"planet bearing index out of range: {index}")
    center = planet_center_xy(stage=stage, index=index)
    return scad.make_placement_rplacement(
        origin=(center[0], center[1], stage.mid_z),
    )

# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "stage1_fixed_ring"
# ///
"""Replaceable fixed herringbone ring insert: a part family, one per stage.

The ``STAGE`` key (``"stage1"`` / ``"stage2"``) selects the stage spec in
``dimensions.STAGES``. The toothed ring gets a support rim out to the
housing bore, so the insert is a press fit in the reducer sleeve. Built
on z = 0; the actuator lifts it to the stage's gear plane.

    sca run examples/integrated_bldc_joint_actuator/ring_gear.py --id stage2_fixed_ring --set STAGE=stage2
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import apply_tags, make_axis_part_rpart
    from dimensions import (
        ADDENDUM_FACTOR,
        BACKLASH,
        CLEARANCE_FACTOR,
        GEAR_HEIGHT,
        HELIX_ANGLE,
        PRESSURE_ANGLE,
        RING_INSERT_OUTER_RADIUS,
        RING_RIM_THICKNESS,
        RING_SUPPORT_OVERLAP,
        STAGES,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- params: stage ----
    STAGE = "stage1"
    return (STAGE,)


@app.cell
def _(STAGE):
    # ---- feature: herringbone-ring (build) ----
    # Left-hand helix: meshes with the right-hand suns through the planets.
    _stage = STAGES[STAGE]
    _ring = scad.std.gear.make_herringbone_ring_gear_rsolid(
        n_teeth=_stage.ring_teeth,
        module=_stage.module,
        pressure_angle=PRESSURE_ANGLE,
        helix_angle=-HELIX_ANGLE,
        gear_height=GEAR_HEIGHT,
        rim_thickness=RING_RIM_THICKNESS,
        backlash=BACKLASH,
        addendum_factor=ADDENDUM_FACTOR,
        clearance_factor=CLEARANCE_FACTOR,
    )
    herringbone_ring = scad.apply_tag(
        shape=_ring, tag=f"solid.stdlib.{STAGE}.fixed.herringbone.ring.gear"
    )
    return (herringbone_ring,)


@app.cell
def _(STAGE, herringbone_ring):
    # ---- feature: support-rim (add) ----
    # An annulus from just inside the ring's outer radius to the insert OD.
    _stage = STAGES[STAGE]
    _support = scad.make_cylinder_rsolid(
        radius=RING_INSERT_OUTER_RADIUS,
        height=GEAR_HEIGHT,
        bottom_face_center=(0.0, 0.0, 0.0),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"reducer.{STAGE}.ring.support",
        result_tag=f"feature.reducer.{STAGE}.ring.support",
    )
    _support_bore = scad.make_cylinder_rsolid(
        radius=_stage.ring_outer_radius - RING_SUPPORT_OVERLAP,
        height=GEAR_HEIGHT + 2.0,
        bottom_face_center=(0.0, 0.0, -1.0),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"reducer.{STAGE}.ring.support.bore",
        result_tag=f"tool.reducer.{STAGE}.ring.support.bore",
    )
    _support = scad.cut_rsolid(_support, _support_bore, skip_non_intersecting=False)
    support_rim = scad.union_rsolid(herringbone_ring, _support, glue=False)
    return (support_rim,)


@app.cell
def _(STAGE, support_rim):
    # ---- product: ring axis ----
    fixed_ring = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=support_rim,
            tags=(f"role.{STAGE}.fixed_ring_gear", "role.ring_gear_press_fit", "group.two_stage_reducer"),
        ),
        name=f"{STAGES[STAGE].label} replaceable fixed herringbone ring insert",
        material=make_actuator_material_rmaterial(key="gear"),
        connectors=(("axis", (0.0, 0.0, GEAR_HEIGHT / 2.0), "Fixed ring axis"),),
    )
    return (fixed_ring,)


if __name__ == "__main__":
    app.run()

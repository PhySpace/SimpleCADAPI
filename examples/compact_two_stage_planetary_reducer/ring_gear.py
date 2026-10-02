# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "stage1_ring_gear"
# ///
"""Fixed internal herringbone ring gear: a part family, one member per stage.

The ``STAGE`` key (``"stage1"`` / ``"stage2"``) selects the stage spec in
``dimensions.STAGES``: tooth count, helix hand and gear plane. The ring is
grounded in the housing; an outer support annulus fills the radial gap to
the housing bore. Built on z = 0; the assembly lifts it to the stage plane.

    sca run examples/compact_two_stage_planetary_reducer/ring_gear.py --id stage2_ring_gear --set STAGE=stage2
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import AxialFace, apply_tags, make_axis_part_rpart
    from dimensions import (
        ADDENDUM_FACTOR,
        BACKLASH,
        CLEARANCE_FACTOR,
        FIXED_RING_HOUSING_SUPPORT_OVERLAP,
        GEAR_HEIGHT,
        HOUSING_INNER_RADIUS,
        MODULE,
        PRESSURE_ANGLE,
        RING_RIM_THICKNESS,
        STAGES,
    )
    from materials import make_reducer_material_rmaterial


@app.cell
def _():
    # ---- params: stage ----
    STAGE = "stage1"
    return (STAGE,)


@app.cell
def _(STAGE):
    # ---- feature: herringbone-ring (build) ----
    _stage = STAGES[STAGE]
    _ring = scad.std.gear.make_herringbone_ring_gear_rsolid(
        n_teeth=_stage.ring_teeth,
        module=MODULE,
        pressure_angle=PRESSURE_ANGLE,
        helix_angle=_stage.ring_helix_angle,
        gear_height=GEAR_HEIGHT,
        rim_thickness=RING_RIM_THICKNESS,
        backlash=BACKLASH,
        addendum_factor=ADDENDUM_FACTOR,
        clearance_factor=CLEARANCE_FACTOR,
    )
    herringbone_ring = scad.apply_tag(shape=_ring, tag=f"solid.reducer.{STAGE}.ring.gear")
    return (herringbone_ring,)


@app.cell
def _(STAGE, herringbone_ring):
    # ---- feature: housing-support (add) ----
    # The annulus overlaps the ring rim by FIXED_RING_HOUSING_SUPPORT_OVERLAP
    # so the union fuses, and reaches out to the housing bore.
    _stage = STAGES[STAGE]
    _prefix = f"reducer.{STAGE}.ring.support"
    _support = scad.cut_rsolid(
        scad.make_cylinder_rsolid(
            radius=HOUSING_INNER_RADIUS,
            height=_stage.gear_height,
            bottom_face_center=(0.0, 0.0, 0.0),
            axis=(0.0, 0.0, 1.0),
            tag_prefix=f"{_prefix}.outer",
            result_tag=f"solid.{_prefix}.outer",
        ),
        scad.make_cylinder_rsolid(
            radius=_stage.ring_outer_radius - FIXED_RING_HOUSING_SUPPORT_OVERLAP,
            height=_stage.gear_height + 2.0,
            bottom_face_center=(0.0, 0.0, -1.0),
            axis=(0.0, 0.0, 1.0),
            tag_prefix=f"{_prefix}.bore",
            result_tag=f"solid.{_prefix}.bore.cutter",
        ),
        skip_non_intersecting=False,
        tracking_policy=scad.TrackingPolicy.GRAPH,
    )
    _support = scad.apply_tag(shape=_support, tag=f"role.{STAGE}.fixed_ring_housing_support")
    housing_support = scad.union_rsolid(
        [herringbone_ring, _support],
        glue=False,
        tracking_policy=scad.TrackingPolicy.GRAPH,
    )
    return (housing_support,)


@app.cell
def _(STAGE, housing_support):
    # ---- product: top-face axis connector ----
    _body = apply_tags(housing_support, tags=(f"role.{STAGE}.fixed_ring_gear", "group.two_stage_reducer"))
    ring_gear = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        solid=_body,
        name=f"{STAGES[STAGE].label} fixed herringbone ring gear",
        material=make_reducer_material_rmaterial(key="gear"),
        faces=(AxialFace("axis", target_z=GEAR_HEIGHT, normal_z=1.0),),
    )
    return (ring_gear,)


if __name__ == "__main__":
    app.run()

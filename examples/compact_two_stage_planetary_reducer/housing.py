# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "reducer_housing"
# ///
"""Reducer housing: the fixed, through-bolted case around both gear stages.

An annular sleeve closed by two sealed end caps, thin internal datum collars
at the gear-plane faces, and a full-height outer mounting band. The band is
split into four sector pads by radial service gaps, and each pad carries
three M3-class through bolts counterbored on both ends, so the actuator can
be mounted from either side. The inner shell stays continuous: one case,
not four ears joined by fasteners.

The housing axes are design datums, not face picks (the scalloped pads make
the end faces non-simple), so every connector is a topology-free placement.

    sca run examples/compact_two_stage_planetary_reducer/housing.py
"""

import marimo

app = marimo.App()

with app.setup:
    import math

    import simplecadapi as scad

    from common import add_placement_axis_connector_rpart, apply_tags, make_annular_cylinder_rsolid
    from dimensions import (
        HOUSING_BODY_OUTER_RADIUS,
        HOUSING_BOTTOM_Z,
        HOUSING_DATUM_INNER_RADIUS,
        HOUSING_DATUM_OUTER_RADIUS,
        HOUSING_END_FLANGE_OUTER_RADIUS,
        HOUSING_FRONT_FLANGE_THICKNESS,
        HOUSING_HEIGHT,
        HOUSING_INNER_RADIUS,
        HOUSING_MOUNT_COUNTERBORE_DEPTH,
        HOUSING_MOUNT_COUNTERBORE_DIAMETER,
        HOUSING_MOUNT_HOLE_CIRCLE_RADIUS,
        HOUSING_MOUNT_HOLE_DIAMETER,
        HOUSING_MOUNT_HOLE_OFFSET_DEGREES,
        HOUSING_MOUNT_HOLES_PER_SECTOR,
        HOUSING_MOUNT_PAD_INNER_RADIUS,
        HOUSING_MOUNT_PAD_OUTER_RADIUS,
        HOUSING_MOUNT_SECTOR_CENTER_OFFSET_DEGREES,
        HOUSING_MOUNT_SECTOR_COUNT,
        HOUSING_MOUNT_SECTOR_GAP_WIDTH,
        HOUSING_REAR_FLANGE_THICKNESS,
        INPUT_BEARING_Z,
        INPUT_FLANGE_TOP_Z,
        INPUT_SEAL_BORE_RADIUS,
        INTERMEDIATE_BEARING_Z,
        OUTPUT_BEARING_Z,
        OUTPUT_FLANGE_TOP_Z,
        OUTPUT_SEAL_BORE_RADIUS,
        STAGE_1,
        STAGE_2,
    )
    from materials import make_reducer_material_rmaterial

    HOUSING_TOP_Z = HOUSING_BOTTOM_Z + HOUSING_HEIGHT


@app.function
def mount_hole_cutters(angle: float, tag_prefix: str) -> list[scad.Solid]:
    """Through hole plus front and rear counterbores for one housing screw.

    The through cutter spans the whole housing, so a real screw clears the
    rear half of the case too, not just a cosmetic front pocket.
    """
    x = HOUSING_MOUNT_HOLE_CIRCLE_RADIUS * math.cos(angle)
    y = HOUSING_MOUNT_HOLE_CIRCLE_RADIUS * math.sin(angle)
    # (radius, height, bottom z, tag) per cutter
    cards = (
        (HOUSING_MOUNT_HOLE_DIAMETER / 2.0, HOUSING_HEIGHT + 2.0, HOUSING_BOTTOM_Z - 1.0, "through"),
        (
            HOUSING_MOUNT_COUNTERBORE_DIAMETER / 2.0,
            HOUSING_MOUNT_COUNTERBORE_DEPTH + 0.4,
            HOUSING_TOP_Z - HOUSING_MOUNT_COUNTERBORE_DEPTH,
            "front.counterbore",
        ),
        (
            HOUSING_MOUNT_COUNTERBORE_DIAMETER / 2.0,
            HOUSING_MOUNT_COUNTERBORE_DEPTH + 0.4,
            HOUSING_BOTTOM_Z - 0.2,
            "rear.counterbore",
        ),
    )
    return [
        scad.make_cylinder_rsolid(
            radius=radius,
            height=height,
            bottom_face_center=(x, y, bottom_z),
            axis=(0.0, 0.0, 1.0),
            tag_prefix=f"{tag_prefix}.{tag}",
            result_tag=f"solid.{tag_prefix}.{tag}.cutter",
        )
        for radius, height, bottom_z, tag in cards
    ]


@app.cell
def _():
    # ---- feature: case-shell (build) ----
    # Sleeve, both sealed end caps, the full-height outer mounting band and
    # the internal datum collars, fused in one union.
    _sleeve = make_annular_cylinder_rsolid(
        outer_radius=HOUSING_BODY_OUTER_RADIUS,
        inner_radius=HOUSING_INNER_RADIUS,
        height=HOUSING_HEIGHT,
        bottom_z=HOUSING_BOTTOM_Z,
        tag_prefix="reducer.housing.sleeve",
        tag="role.housing_sleeve",
    )
    # The end caps are only the annular plates around the rotating flanges;
    # their bores are the fixed labyrinth seal lips.
    _front_cap = make_annular_cylinder_rsolid(
        outer_radius=HOUSING_END_FLANGE_OUTER_RADIUS,
        inner_radius=OUTPUT_SEAL_BORE_RADIUS,
        height=HOUSING_FRONT_FLANGE_THICKNESS,
        bottom_z=HOUSING_TOP_Z - HOUSING_FRONT_FLANGE_THICKNESS,
        tag_prefix="reducer.housing.front.end.cap",
        tag="role.housing_front_sealed_end_cap",
    )
    _rear_cap = make_annular_cylinder_rsolid(
        outer_radius=HOUSING_END_FLANGE_OUTER_RADIUS,
        inner_radius=INPUT_SEAL_BORE_RADIUS,
        height=HOUSING_REAR_FLANGE_THICKNESS,
        bottom_z=HOUSING_BOTTOM_Z,
        tag_prefix="reducer.housing.rear.end.cap",
        tag="role.housing_rear_sealed_end_cap",
    )
    _pad_prefix = "reducer.housing.mount.sector.pad"
    _mount_band = scad.cut_rsolid(
        scad.make_cylinder_rsolid(
            radius=HOUSING_MOUNT_PAD_OUTER_RADIUS,
            height=HOUSING_HEIGHT,
            bottom_face_center=(0.0, 0.0, HOUSING_BOTTOM_Z),
            axis=(0.0, 0.0, 1.0),
            tag_prefix=f"{_pad_prefix}.outer",
            result_tag=f"solid.{_pad_prefix}.outer",
        ),
        scad.make_cylinder_rsolid(
            radius=HOUSING_MOUNT_PAD_INNER_RADIUS,
            height=HOUSING_HEIGHT + 2.0,
            bottom_face_center=(0.0, 0.0, HOUSING_BOTTOM_Z - 1.0),
            axis=(0.0, 0.0, 1.0),
            tag_prefix=f"{_pad_prefix}.inner",
            result_tag=f"solid.{_pad_prefix}.inner.cutter",
        ),
        skip_non_intersecting=False,
    )
    _mount_band = apply_tags(
        _mount_band, tags=("role.housing_sector_mount_pads", "role.case_to_link_interface")
    )
    # Collars mark the gear-plane datums inside the sleeve. Datums that fall
    # inside an end cap are skipped: the cap already provides that seal land.
    _collars = []
    _datum_zs = (INPUT_FLANGE_TOP_Z, STAGE_1.top_z, STAGE_2.top_z, OUTPUT_FLANGE_TOP_Z)
    for _index, _z in enumerate(_datum_zs):
        if not (
            HOUSING_BOTTOM_Z + HOUSING_REAR_FLANGE_THICKNESS
            < _z
            < HOUSING_TOP_Z - HOUSING_FRONT_FLANGE_THICKNESS
        ):
            continue
        _collars.append(
            make_annular_cylinder_rsolid(
                outer_radius=HOUSING_DATUM_OUTER_RADIUS,
                inner_radius=HOUSING_DATUM_INNER_RADIUS,
                height=0.36,
                bottom_z=_z - 0.36,
                tag_prefix=f"reducer.housing.datum.collar.i{_index + 1}",
                tag=f"role.housing_axis_datum_{_index + 1}",
            )
        )
    case_shell = scad.union_rsolid([_sleeve, _front_cap, _rear_cap, _mount_band, _collars], glue=False)
    return (case_shell,)


@app.cell
def _(case_shell):
    # ---- feature: sector-gaps-and-bolt-holes (subtract) ----
    # One cut: four radial gaps through the outer band only (the sleeve stays
    # continuous), then three bolts per sector pad.
    _gap_inner_radius = HOUSING_BODY_OUTER_RADIUS + 0.15
    _gap_center_radius = (_gap_inner_radius + HOUSING_MOUNT_PAD_OUTER_RADIUS + 0.8) / 2.0
    _gaps = []
    for _index in range(HOUSING_MOUNT_SECTOR_COUNT):
        _gap = scad.make_box_rsolid(
            width=HOUSING_MOUNT_PAD_OUTER_RADIUS - _gap_inner_radius + 1.0,
            height=HOUSING_MOUNT_SECTOR_GAP_WIDTH,
            depth=HOUSING_HEIGHT + 2.0,
            bottom_face_center=(_gap_center_radius, 0.0, HOUSING_BOTTOM_Z - 1.0),
            tag_prefix=f"reducer.housing.mount.gap.i{_index + 1}",
            result_tag=f"solid.reducer.housing.mount.gap.i{_index + 1}.cutter",
        )
        _gaps.append(
            scad.rotate_shape(
                shape=_gap,
                angle=HOUSING_MOUNT_SECTOR_CENTER_OFFSET_DEGREES
                + 45.0
                + 360.0 * _index / HOUSING_MOUNT_SECTOR_COUNT,
                axis=(0.0, 0.0, 1.0),
                origin=(0.0, 0.0, 0.0),
            )
        )
    _holes = []
    _offsets = (-HOUSING_MOUNT_HOLE_OFFSET_DEGREES, 0.0, HOUSING_MOUNT_HOLE_OFFSET_DEGREES)
    for _sector in range(HOUSING_MOUNT_SECTOR_COUNT):
        _sector_degrees = (
            HOUSING_MOUNT_SECTOR_CENTER_OFFSET_DEGREES + 360.0 * _sector / HOUSING_MOUNT_SECTOR_COUNT
        )
        for _hole in range(HOUSING_MOUNT_HOLES_PER_SECTOR):
            _holes.extend(
                mount_hole_cutters(
                    math.radians(_sector_degrees + _offsets[_hole]),
                    f"reducer.housing.mount.hole.sector.i{_sector + 1}.i{_hole + 1}",
                )
            )
    sector_gaps_and_bolt_holes = scad.cut_rsolid(case_shell, [_gaps, _holes], skip_non_intersecting=False)
    return (sector_gaps_and_bolt_holes,)


@app.cell
def _(sector_gaps_and_bolt_holes):
    # ---- product: datum axes and bearing seats ----
    _body = apply_tags(
        sector_gaps_and_bolt_holes,
        tags=("role.fixed_housing", "role.case_to_link_interface", "group.two_stage_reducer"),
    )
    _part = scad.make_part_rpart(
        part_id=scad.notebook_id(),
        body=_body,
        name="Compact fixed reducer housing sleeve",
    )
    _part = scad.assign_material_rpart(part=_part, material=make_reducer_material_rmaterial(key="housing"))
    for _connector_id, _z in (
        ("input_axis", STAGE_1.top_z),
        ("stage1_axis", STAGE_1.top_z),
        ("stage2_axis", STAGE_2.top_z),
        ("output_axis", OUTPUT_FLANGE_TOP_Z),
        ("input_bearing_axis", INPUT_BEARING_Z),
        ("intermediate_bearing_axis", INTERMEDIATE_BEARING_Z),
        ("output_bearing_axis", OUTPUT_BEARING_Z),
    ):
        _part = add_placement_axis_connector_rpart(
            part=_part,
            connector_id=_connector_id,
            origin=(0.0, 0.0, _z),
            name=_connector_id.replace("_", " "),
        )
    reducer_housing = _part
    return (reducer_housing,)


if __name__ == "__main__":
    app.run()

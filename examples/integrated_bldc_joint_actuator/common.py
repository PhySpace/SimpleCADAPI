"""Shared construction, tagging, and connector helpers for the actuator notebooks.

A plain module (no cells): the notebooks import these helpers, so the
helpers' code is part of every importing notebook's dependency digest.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator

import simplecadapi as scad

from dimensions import MOSFET_ANGLES, MOSFET_CENTER_RADIUS, PLANET_COUNT, StageSpec


def apply_tags(*, shape: scad.Solid, tags: Iterable[str]) -> scad.Solid:
    """Apply semantic tags through the public functional API."""

    tagged = shape
    for tag in tags:
        tagged = scad.apply_tag(shape=tagged, tag=tag)
    return tagged


def make_annulus_rsolid(*,
outer_radius: float,
inner_radius: float,
bottom_z: float,
height: float,
tag_prefix: str,
tags: Iterable[str],) -> scad.Solid:
    """Create a strict single-solid annular cylinder."""

    outer = scad.make_cylinder_rsolid(
        radius=outer_radius,
        height=height,
        bottom_face_center=(0.0, 0.0, bottom_z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"{tag_prefix}.outer",
        result_tag=f"feature.{tag_prefix}.outer",
    )
    bore = scad.make_cylinder_rsolid(
        radius=inner_radius,
        height=height + 2.0,
        bottom_face_center=(0.0, 0.0, bottom_z - 1.0),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"{tag_prefix}.bore",
        result_tag=f"tool.{tag_prefix}.bore",
    )
    annulus = scad.cut_rsolid(outer, bore, skip_non_intersecting=False)
    return apply_tags(shape=annulus, tags=tags)


def make_axis_part_rpart(*,
part_id: str,
body: scad.Solid,
name: str,
material: scad.Material,
connectors: Iterable[tuple[str, tuple[float, float, float], str]],) -> scad.Part:
    """Create a single-body part with stable placement-based axis datums."""

    part = scad.make_part_rpart(part_id=part_id, body=body, name=name)
    part = scad.assign_material_rpart(part=part, material=material)
    for connector_id, origin, connector_name in connectors:
        connector = scad.make_placement_connector_rconnector(
            connector_id=connector_id,
            placement=scad.make_placement_rplacement(origin=origin),
            name=connector_name,
        )
        part = scad.add_connector_rpart(part=part, connector=connector)
    return part


def z_rotation_placement(*,
origin: tuple[float, float, float],
angle_degrees: float,) -> scad.Placement:
    """Return a right-handed placement rotated about Z."""

    angle = math.radians(angle_degrees)
    return scad.make_placement_rplacement(
        origin=origin,
        x_axis=(math.cos(angle), math.sin(angle), 0.0),
        y_axis=(-math.sin(angle), math.cos(angle), 0.0),
    )


def radial_centers(*,
count: int,
radius: float,
angle_offset: float = 0.0,) -> Iterator[tuple[int, float, tuple[float, float]]]:
    """Yield index, angle in degrees, and XY center on a bolt/pole circle."""

    for index in range(count):
        angle_degrees = angle_offset + 360.0 * index / count
        angle = math.radians(angle_degrees)
        yield index, angle_degrees, (radius * math.cos(angle), radius * math.sin(angle))


def planet_center_xy(*, stage: StageSpec, index: int) -> tuple[float, float]:
    """Return one equally spaced planet pitch center."""

    angle = math.radians(360.0 * index / PLANET_COUNT)
    return (
        stage.planet_center_radius * math.cos(angle),
        stage.planet_center_radius * math.sin(angle),
    )


def mosfet_center_xy(*, index: int) -> tuple[float, float]:
    """Return one power MOSFET's XY center on the controller PCB."""

    angle = math.radians(MOSFET_ANGLES[index])
    return (MOSFET_CENTER_RADIUS * math.cos(angle), MOSFET_CENTER_RADIUS * math.sin(angle))


def make_axial_hole_cutters_rsolids(*,
count: int,
pcd: float,
hole_radius: float,
bottom_z: float,
height: float,
tag_prefix: str,
angle_offset: float = 0.0,) -> list[scad.Solid]:
    """Create equally spaced axial hole cutters."""

    return [
        scad.make_cylinder_rsolid(
            radius=hole_radius,
            height=height,
            bottom_face_center=(center[0], center[1], bottom_z),
            axis=(0.0, 0.0, 1.0),
            tag_prefix=f"{tag_prefix}.hole{index + 1}",
            result_tag=f"tool.{tag_prefix}.hole{index + 1}",
        )
        for index, _angle, center in radial_centers(
            count=count,
            radius=pcd / 2.0,
            angle_offset=angle_offset,
        )
    ]


def make_carrier_body_rsolid(*,
stage: StageSpec,
plate_bottom_z: float,
plate_thickness: float,
pin_bottom_z: float,
pin_radius: float,
hub_radius: float,
arm_width: float,
pad_radius: float,) -> scad.Solid:
    """Three-arm planet carrier plate: hub, arms, planet pads, and bearing pins."""

    sid = stage.stage_id
    hub = scad.make_cylinder_rsolid(
        radius=hub_radius,
        height=plate_thickness,
        bottom_face_center=(0.0, 0.0, plate_bottom_z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"reducer.{sid}.carrier.hub",
        result_tag=f"feature.reducer.{sid}.carrier.hub",
    )
    solids: list[scad.Solid] = [hub]
    pin_height = plate_bottom_z + plate_thickness - pin_bottom_z
    arm_inner_radius = hub_radius - 1.25
    arm_outer_radius = stage.planet_center_radius + pad_radius - 0.25
    arm_length = arm_outer_radius - arm_inner_radius
    arm_center_radius = (arm_inner_radius + arm_outer_radius) / 2.0
    for index in range(PLANET_COUNT):
        center = planet_center_xy(stage=stage, index=index)
        arm = scad.make_box_rsolid(
            width=arm_length,
            height=arm_width,
            depth=plate_thickness,
            bottom_face_center=(arm_center_radius, 0.0, plate_bottom_z),
            tag_prefix=f"reducer.{sid}.carrier.arm{index + 1}",
            result_tag=f"feature.reducer.{sid}.carrier.arm{index + 1}",
        )
        solids.append(
            scad.rotate_shape(
                shape=arm,
                angle=360.0 * index / PLANET_COUNT,
                axis=(0.0, 0.0, 1.0),
                origin=(0.0, 0.0, 0.0),
            )
        )
        solids.append(
            scad.make_cylinder_rsolid(
                radius=pad_radius,
                height=plate_thickness,
                bottom_face_center=(center[0], center[1], plate_bottom_z),
                axis=(0.0, 0.0, 1.0),
                tag_prefix=f"reducer.{sid}.carrier.pad{index + 1}",
                result_tag=f"feature.reducer.{sid}.carrier.pad{index + 1}",
            )
        )
        solids.append(
            scad.make_cylinder_rsolid(
                radius=pin_radius,
                height=pin_height,
                bottom_face_center=(center[0], center[1], pin_bottom_z),
                axis=(0.0, 0.0, 1.0),
                tag_prefix=f"reducer.{sid}.carrier.pin{index + 1}",
                result_tag=f"feature.reducer.{sid}.carrier.pin{index + 1}",
            )
        )
    return scad.union_rsolid(solids, glue=False)


def planet_connectors(*,
stage: StageSpec,) -> list[tuple[str, tuple[float, float, float], str]]:
    """Per-planet spin-axis and bearing-pin datums for a carrier part."""

    connectors: list[tuple[str, tuple[float, float, float], str]] = []
    for index in range(PLANET_COUNT):
        center = planet_center_xy(stage=stage, index=index)
        connectors.extend(
            (
                (f"planet_{index + 1}_axis", (*center, stage.mid_z), f"{stage.label} planet {index + 1} axis"),
                (
                    f"planet_{index + 1}_bearing_axis",
                    (*center, stage.mid_z),
                    f"{stage.label} planet {index + 1} bearing pin",
                ),
            )
        )
    return connectors


def connector_ref(*, component_id: str, connector_id: str) -> scad.ConnectorRef:
    """Create a component-scoped connector reference."""

    return scad.make_connector_ref_rconnectorref(
        component_id=component_id,
        connector_id=connector_id,
    )

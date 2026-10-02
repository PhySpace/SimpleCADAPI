"""Shared construction helpers for the reducer part notebooks.

A plain module (no cells): the notebooks import these helpers, so the
helpers' code is part of every importing notebook's dependency digest.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import simplecadapi as scad
from simplecadapi import ql

from dimensions import GEAR_HEIGHT


@dataclass(frozen=True)
class AxialFace:
    """A face connector on the axial (+Z or -Z facing) face nearest a point.

    The face is picked by its center: the face whose normal points along
    ``normal_z`` and whose center is closest to ``(*center_xy, target_z)``,
    axial distance weighted far above radial distance.
    """

    connector_id: str
    target_z: float
    normal_z: float
    center_xy: tuple[float, float] = (0.0, 0.0)
    name: str | None = None
    flip: bool = False


def make_z_rotation_rplacement(*,
origin: tuple[float, float, float],
angle_degrees: float,) -> scad.Placement:
    """Return a placement rotated about the local Z axis."""

    angle_radians = math.radians(angle_degrees)
    cos_a = math.cos(angle_radians)
    sin_a = math.sin(angle_radians)
    return scad.make_placement_rplacement(
        origin=origin,
        x_axis=(cos_a, sin_a, 0.0),
        y_axis=(-sin_a, cos_a, 0.0),
    )


def make_annular_cylinder_rsolid(*,
outer_radius: float,
inner_radius: float,
height: float,
bottom_z: float,
tag_prefix: str,
tag: str,) -> scad.Solid:
    """Create a single hollow cylindrical solid with a through bore."""

    if inner_radius <= 0.0 or outer_radius <= inner_radius:
        raise ValueError("annular cylinder requires 0 < inner_radius < outer_radius")
    outer = scad.make_cylinder_rsolid(
        radius=outer_radius,
        height=height,
        bottom_face_center=(0.0, 0.0, bottom_z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"{tag_prefix}.outer",
        result_tag=f"solid.{tag_prefix}.outer",
    )
    bore = scad.make_cylinder_rsolid(
        radius=inner_radius,
        height=height + 2.0,
        bottom_face_center=(0.0, 0.0, bottom_z - 1.0),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"{tag_prefix}.bore",
        result_tag=f"solid.{tag_prefix}.bore.cutter",
    )
    annular = scad.cut_rsolid(outer, bore, skip_non_intersecting=False)
    return scad.apply_tag(shape=annular, tag=tag)


def make_axis_part_rpart(*,
part_id: str,
solid: scad.Solid,
name: str,
faces: Iterable[AxialFace],
material: scad.Material | None = None,) -> scad.Part:
    """Wrap a solid as a Part and attach one face connector per ``AxialFace``."""

    part = scad.make_part_rpart(part_id=part_id, body=solid, name=name)
    if material is not None:
        part = scad.assign_material_rpart(part=part, material=material)
    for spec in faces:
        part = scad.add_connector_rpart(
            part=part,
            connector=scad.make_face_connector_rconnector(
                connector_id=spec.connector_id,
                face=_axis_face(solid=solid, spec=spec),
                name=spec.name,
                flip=spec.flip,
            ),
        )
    return part


def add_placement_axis_connector_rpart(*,
part: scad.Part,
connector_id: str,
origin: tuple[float, float, float],
name: str | None = None,) -> scad.Part:
    """Attach a topology-free axis connector at an explicit local placement."""

    connector = scad.make_placement_connector_rconnector(
        connector_id=connector_id,
        placement=scad.make_placement_rplacement(origin=origin),
        name=name,
    )
    return scad.add_connector_rpart(part=part, connector=connector)


def cut_gear_bore_rsolid(*,
solid: scad.Solid,
bore_radius: float,
tag_prefix: str,
label: str,) -> scad.Solid:
    """Cut a through bore along Z into a gear blank sitting on z = 0."""

    cutter = scad.make_cylinder_rsolid(
        radius=bore_radius,
        height=GEAR_HEIGHT + 2.0,
        bottom_face_center=(0.0, 0.0, -1.0),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=tag_prefix,
        result_tag=f"solid.{tag_prefix}.cutter",
    )
    bored = scad.cut_rsolid(
        solid,
        cutter,
        skip_non_intersecting=False,
        tracking_policy=scad.TrackingPolicy.GRAPH,
    )
    return scad.apply_tag(shape=bored, tag=f"solid.cut.{label}")


def apply_tags(shape: scad.Solid, tags: Iterable[str]) -> scad.Solid:
    """Apply normalized tags through the public SimpleCAD tag API."""

    tagged = shape
    for tag in tags:
        tagged = scad.apply_tag(shape=tagged, tag=tag)
    return tagged


def _axis_face(*, solid: scad.Solid, spec: AxialFace) -> scad.Face:
    candidates = []
    for face in ql.faces().resolve(solid):
        normal = face.get_normal_at()
        if spec.normal_z > 0.0 and normal.z < 0.65:
            continue
        if spec.normal_z < 0.0 and normal.z > -0.65:
            continue
        center = face.get_center()
        xy_error = math.hypot(center.x - spec.center_xy[0], center.y - spec.center_xy[1])
        z_error = abs(center.z - spec.target_z)
        candidates.append((z_error * 1000.0 + xy_error, face))

    if not candidates:
        raise ValueError(f"no axial connector face found for {spec.connector_id}")
    return min(candidates, key=lambda item: item[0])[1]

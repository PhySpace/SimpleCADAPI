"""The bodies of a Part: its shape as one value, and the mass of each body.

A Part holds one Solid or several named bodies (see ``Part.bodies``).  Geometry consumers that do not care which body a
face belongs to (STEP, STL, MJCF meshes) read :func:`part_shape`; consumers that do (the preview, the package, mass
properties) walk ``part.bodies``.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from simplecadapi._cpp import Compound, Part, Solid, make_part_rpart

# density unit -> factor to kg/mm^3 (the model is in millimetres)
_DENSITY_TO_KG_MM3 = {
    "kg/mm^3": 1.0,
    "kg/mm3": 1.0,
    "kg/m^3": 1.0e-9,
    "kg/m3": 1.0e-9,
    "g/cm^3": 1.0e-6,
    "g/cm3": 1.0e-6,
    "g/mm^3": 1.0e-3,
    "g/mm3": 1.0e-3,
}


def part_shape(part: Part) -> Solid | Compound:
    """The Solid of a one-body Part, or a Compound of every body of a multi-body Part (in body order).

    The Compound is a geometry view: it is a new shape root and does not carry the bodies' tags.
    """

    if not isinstance(part, Part):
        raise TypeError("part must be a Part")
    if not part.multi_body:
        return part.body
    return Compound([body.solid for body in part.bodies])


@dataclass(frozen=True)
class BodyMass:
    """Volume, mass and centre of mass of one body (millimetres, kilograms)."""

    body_id: str
    name: str | None
    volume_mm3: float
    mass_kg: float | None
    centroid_mm: tuple[float, float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_id": self.body_id,
            "name": self.name,
            "volume_mm3": self.volume_mm3,
            "mass_kg": self.mass_kg,
            "centroid_mm": list(self.centroid_mm),
        }


@dataclass(frozen=True)
class MassReport:
    """Mass properties of a Part: every body, and the part as a whole."""

    part_id: str
    density_kg_mm3: float | None
    bodies: tuple[BodyMass, ...]
    volume_mm3: float
    mass_kg: float | None
    centroid_mm: tuple[float, float, float]

    def body(self, body_id: str) -> BodyMass:
        for item in self.bodies:
            if item.body_id == body_id:
                return item
        raise KeyError(f"part has no body_id {body_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "density_kg_mm3": self.density_kg_mm3,
            "bodies": [item.to_dict() for item in self.bodies],
            "volume_mm3": self.volume_mm3,
            "mass_kg": self.mass_kg,
            "centroid_mm": list(self.centroid_mm),
        }


def _density(part: Part, density: float | None, density_unit: str | None) -> float | None:
    if density is None:
        material = part.material
        if material is None or material.density is None:
            return None
        density, density_unit = float(material.density), material.density_unit
    unit = str(density_unit or "kg/m^3")
    factor = _DENSITY_TO_KG_MM3.get(unit)
    if factor is None:
        raise ValueError(f"unsupported density unit {unit!r}; use one of {', '.join(sorted(_DENSITY_TO_KG_MM3))}")
    if not float(density) > 0.0:
        raise ValueError("density must be positive")
    return float(density) * factor


def measure_part_mass_rmassreport(
    part: Part,
    *,
    density: float | None = None,
    density_unit: str | None = None,
) -> MassReport:
    """Measure the volume, mass and centre of mass of every body of a Part, and of the Part as a whole.

    Args:
        part: The Part to measure (one body or several).
        density: Density to use instead of the material's; ``None`` uses the
            Part's material, and without a material density every mass is ``None``.
        density_unit: Unit of ``density``: ``kg/m^3`` (default), ``g/cm^3``,
            ``kg/mm^3`` or ``g/mm^3``.

    Returns:
        MassReport: ``bodies`` (one ``BodyMass`` per body, in body order: ``body_id``,
        ``volume_mm3``, ``mass_kg``, ``centroid_mm``) and the totals of the part
        (``volume_mm3``, ``mass_kg``, volume-weighted ``centroid_mm``).

    Raises:
        SimpleCADError: The value is not a Part, or the density or its unit is invalid.

    Usage:
        ``scad.measure_part_mass_rmassreport(case).body("lid").mass_kg`` is the mass of
        the lid body; ``.mass_kg`` the mass of the whole part. Every body has the
        Part's material.
    """

    if not isinstance(part, Part):
        raise TypeError("part must be a Part")
    rho = _density(part, density, density_unit)
    rows: list[BodyMass] = []
    for body in part.bodies:
        volume = float(body.solid.get_volume())
        center = body.solid.get_center()  # the centre of mass of the solid
        rows.append(
            BodyMass(
                body_id=body.body_id,
                name=body.name,
                volume_mm3=volume,
                mass_kg=None if rho is None else volume * rho,
                centroid_mm=(float(center.x), float(center.y), float(center.z)),
            )
        )
    total = sum(item.volume_mm3 for item in rows)
    centroid = tuple(
        sum(item.volume_mm3 * item.centroid_mm[axis] for item in rows) / total if total > 0.0 else 0.0
        for axis in range(3)
    )
    return MassReport(
        part_id=part.part_id,
        density_kg_mm3=rho,
        bodies=tuple(rows),
        volume_mm3=total,
        mass_kg=None if rho is None else total * rho,
        centroid_mm=centroid,  # type: ignore[arg-type]
    )


class BodyOverlapWarning(UserWarning):
    """Two bodies of one Part share volume: mass counts it twice and STEP holds both copies."""


@dataclass(frozen=True)
class BodyOverlap:
    """Two bodies of a Part that share volume (mm^3)."""

    first: str
    second: str
    volume_mm3: float

    def to_dict(self) -> dict[str, Any]:
        return {"first": self.first, "second": self.second, "volume_mm3": self.volume_mm3}


def _boxes_meet(a: tuple[float, ...], b: tuple[float, ...], tol: float) -> bool:
    return all(a[axis] <= b[axis + 3] + tol and b[axis] <= a[axis + 3] + tol for axis in range(3))


def inspect_body_overlaps_rlist(part: Part, *, min_volume_mm3: float = 1e-6) -> list[BodyOverlap]:
    """List the pairs of bodies of a Part that share volume.

    Overlapping bodies are allowed (a Part does not fuse them), but mass counts the
    shared volume once per body and STEP holds both copies. Bodies that only touch
    (a face, an edge or a point in common) do not overlap.

    Args:
        part: The Part to inspect; a one-body Part has no overlaps.
        min_volume_mm3: Shared volume below which a pair is not reported.

    Returns:
        list[BodyOverlap]: ``(first, second, volume_mm3)`` per overlapping pair, in body order.

    Raises:
        SimpleCADError: The value is not a Part.

    Usage:
        ``scad.inspect_body_overlaps_rlist(case)`` before export. Building the part's
        definition (a notebook run, ``@part``, a package) warns with ``BodyOverlapWarning``
        for the same pairs.
    """

    import simplecadapi._cpp._native as native

    if not isinstance(part, Part):
        raise TypeError("part must be a Part")
    occt = native._occt
    bodies = list(part.bodies)
    boxes = [body.solid._bounds() for body in bodies]
    out: list[BodyOverlap] = []
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            if not _boxes_meet(boxes[i], boxes[j], 1e-7):
                continue
            common = occt.BRepAlgoAPI_Common(bodies[i].solid.wrapped, bodies[j].solid.wrapped).Shape()
            props = occt.GProp_GProps()
            occt.BRepGProp.VolumeProperties_s(common, props)
            volume = float(props.Mass())
            if volume > min_volume_mm3:
                out.append(BodyOverlap(bodies[i].body_id, bodies[j].body_id, volume))
    return out


def warn_body_overlaps(part: Part, *, stacklevel: int = 2) -> list[BodyOverlap]:
    """Warn (``BodyOverlapWarning``) once per overlapping pair of bodies of *part*; returns the pairs."""

    if not part.multi_body:
        return []
    overlaps = inspect_body_overlaps_rlist(part)
    for item in overlaps:
        warnings.warn(
            f"part {part.part_id!r}: bodies {item.first!r} and {item.second!r} overlap by {item.volume_mm3:.6g} mm^3 "
            "(mass counts it twice; union them, or cut one from the other, if they are one piece of material)",
            BodyOverlapWarning,
            stacklevel=stacklevel,
        )
    return overlaps


def part_from_bodies(part_id: str, bodies: Mapping[str, Solid | Sequence[Solid]], *, name: str | None = None) -> Part:
    """The Part of named solids, the way a notebook names them: one name and one Solid is a one-body Part (body id
    ``"body"``); otherwise every name is a body, and the pieces of a split cut (a list) are ``<name>_1 .. <name>_n``.

    This is the rule of an implicit product (a ``kind = "part"`` notebook without a ``make_part_rpart`` cell: its open
    bodies, by variable name) and of an editor product cell with several bodies.
    """

    items = dict(bodies)
    if not items:
        raise ValueError("a Part needs at least one body")
    if len(items) == 1:
        (value,) = items.values()
        if isinstance(value, Solid) or (isinstance(value, (list, tuple)) and len(value) == 1):
            return make_part_rpart(part_id=part_id, body=value, name=name)
    return make_part_rpart(part_id=part_id, bodies=items, name=name)


__all__ = [
    "BodyMass",
    "BodyOverlap",
    "BodyOverlapWarning",
    "MassReport",
    "inspect_body_overlaps_rlist",
    "measure_part_mass_rmassreport",
    "part_from_bodies",
    "part_shape",
    "warn_body_overlaps",
]

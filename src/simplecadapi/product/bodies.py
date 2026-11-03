"""The bodies of a Part: its shape as one value, and the mass of each body.

A Part holds one Solid or several named bodies (see ``Part.bodies``).  Geometry consumers that do not care which body a
face belongs to (STEP, STL, MJCF meshes) read :func:`part_shape`; consumers that do (the preview, the package, mass
properties) walk ``part.bodies``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simplecadapi._cpp import Compound, Part, Solid

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


__all__ = ["BodyMass", "MassReport", "measure_part_mass_rmassreport", "part_shape"]

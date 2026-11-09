"""The body of a Part: its display colour and the mass report.

A Part holds exactly one Solid (``Part.body``).  ``Part.bodies`` is that body as a one-element tuple: a ``Body`` carries
the display name, colour and opacity (``set_body_appearance_rpart``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simplecadapi._cpp import Part

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


def body_display_color(part: Part, body: Any) -> tuple[float, float, float] | None:
    """The colour a viewer shows *body* of *part* in: the body's own colour, else the Part's material colour, else
    ``None`` (the viewer's default grey).

    A body colour (``set_body_appearance_rpart``) overrides the material colour for display only.
    """

    if body.color is not None:
        return tuple(float(c) for c in body.color)  # type: ignore[return-value]
    material = part.material
    if material is not None and material.color is not None:
        return tuple(float(c) for c in material.color)  # type: ignore[return-value]
    return None


def body_appearance_fields(body: Any) -> dict[str, Any]:
    """The appearance a body sets itself, as plain data: ``color`` (RGB list) and ``opacity`` when set, else ``{}``."""

    out: dict[str, Any] = {}
    if body.color is not None:
        out["color"] = [float(c) for c in body.color]
    if body.opacity is not None:
        out["opacity"] = float(body.opacity)
    return out


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
    """Measure the volume, mass and centre of mass of a Part.

    Args:
        part: The Part to measure.
        density: Density to use instead of the material's; ``None`` uses the
            Part's material, and without a material density every mass is ``None``.
        density_unit: Unit of ``density``: ``kg/m^3`` (default), ``g/cm^3``,
            ``kg/mm^3`` or ``g/mm^3``.

    Returns:
        MassReport: ``bodies`` (the Part's one ``BodyMass``: ``body_id``, ``volume_mm3``,
        ``mass_kg``, ``centroid_mm``) and the totals of the part (``volume_mm3``,
        ``mass_kg``, ``centroid_mm``).

    Raises:
        SimpleCADError: The value is not a Part, or the density or its unit is invalid.

    Usage:
        ``scad.measure_part_mass_rmassreport(bracket).mass_kg`` is the mass of the part.
        The part's material gives the density unless ``density`` is passed.
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


__all__ = [
    "BodyMass",
    "MassReport",
    "measure_part_mass_rmassreport",
]

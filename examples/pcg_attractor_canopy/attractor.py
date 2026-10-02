"""Attractor field of the porous canopy: parameters, field and cell mapping.

Plain module, no geometry: the ``attractor_canopy.py`` notebook builds the
solid from these numbers, and ``export.py`` reports on them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

import simplecadapi as scad
from simplecadapi import ql


@dataclass(frozen=True, slots=True)
class CanopyParams:
    radius_mm: float = 55.0
    height_mm: float = 34.0
    shell_thickness_mm: float = 3.0
    rings: int = 4
    sectors: int = 12
    hole_radius_mm: float = 5.0
    attractor_x_mm: float = 18.0
    attractor_y_mm: float = 8.0
    attractor_strength: float = 0.7
    twist_degrees: float = 28.0
    material_density_kg_mm3: float = 7.85e-6

    def validate(self) -> None:
        positive = (self.radius_mm, self.height_mm, self.shell_thickness_mm, self.hole_radius_mm)
        if not all(math.isfinite(value) and value > 0.0 for value in positive):
            raise ValueError("canopy dimensions must be positive finite values")
        if self.rings < 2 or self.sectors < 8:
            raise ValueError("canopy grid is too small")
        if self.shell_thickness_mm >= self.height_mm:
            raise ValueError("shell thickness must be smaller than canopy height")
        if not -1.0 <= self.attractor_strength <= 1.0:
            raise ValueError("attractor strength must lie in [-1, 1]")


def params_dict(params: CanopyParams) -> dict[str, object]:
    return asdict(params)


def field(params: CanopyParams, x_mm: float, y_mm: float) -> float:
    """Deterministic Gaussian attractor field in [-1, 1]."""
    dx = x_mm - params.attractor_x_mm
    dy = y_mm - params.attractor_y_mm
    distance = math.hypot(dx, dy)
    influence = math.exp(-((distance / (params.radius_mm * 0.42)) ** 2))
    return max(-1.0, min(1.0, params.attractor_strength * influence))


def cell_parameters(params: CanopyParams, ring: int, sector: int) -> tuple[float, float, float, float]:
    """Map one polar cell through the field into position, radius, and twist."""
    radial = (ring + 0.5) / params.rings
    angle = 2.0 * math.pi * sector / params.sectors
    base_x = params.radius_mm * radial * math.cos(angle)
    base_y = params.radius_mm * radial * math.sin(angle)
    local_field = field(params, base_x, base_y)
    radial_shift = params.radius_mm * 0.12 * local_field * (1.0 - radial)
    x = base_x + radial_shift * math.cos(angle)
    y = base_y + radial_shift * math.sin(angle)
    hole_radius = params.hole_radius_mm * (1.0 + 0.95 * local_field) * (1.0 - 0.12 * radial)
    rotation = params.twist_degrees * local_field + 16.0 * radial
    return x, y, max(1.5, hole_radius), rotation


def report(params: CanopyParams, part: scad.Part) -> dict[str, object]:
    body = part.body
    hole_count = params.rings * params.sectors
    nominal_area = math.pi * params.radius_mm**2
    hole_area = sum(
        math.pi * cell_parameters(params, ring, sector)[2] ** 2
        for ring in range(params.rings)
        for sector in range(params.sectors)
    )
    return {
        "parameters": params_dict(params),
        "parameterization": "gaussian_attractor_driven_porous_canopy",
        "hole_count": hole_count,
        "nominal_open_area_mm2": hole_area,
        "nominal_porosity": min(1.0, hole_area / nominal_area),
        "solid_volume_mm3": body.get_volume(),
        "mass_kg": body.get_volume() * params.material_density_kg_mm3,
        "face_count": len(ql.faces().resolve(body)),
    }


def write_report(path: str | Path, payload: dict[str, object]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

"""Material definitions for the compact reducer (a plain module)."""

from __future__ import annotations

from dataclasses import dataclass

import simplecadapi as scad


@dataclass(frozen=True)
class _MaterialSpec:
    material_id: str
    name: str
    density: float
    color: tuple[float, float, float]


_MATERIAL_SPECS = {
    "housing": _MaterialSpec(
        material_id="hard_anodized_aluminum",
        name="Hard anodized aluminum",
        density=2.70e-6,
        color=(0.26, 0.28, 0.30),
    ),
    "carrier": _MaterialSpec(
        material_id="aluminum_7075",
        name="7075 aluminum carrier",
        density=2.81e-6,
        color=(0.48, 0.50, 0.52),
    ),
    "gear": _MaterialSpec(
        material_id="case_hardened_steel",
        name="Case hardened gear steel",
        density=7.85e-6,
        color=(0.68, 0.70, 0.72),
    ),
    "shaft": _MaterialSpec(
        material_id="tempered_shaft_steel",
        name="Tempered shaft steel",
        density=7.85e-6,
        color=(0.55, 0.57, 0.60),
    ),
}


def make_reducer_material_rmaterial(*, key: str) -> scad.Material:
    """Create one reducer material inside the owning feature graph."""

    try:
        spec = _MATERIAL_SPECS[key]
    except KeyError as exc:
        raise ValueError(f"unknown reducer material key: {key}") from exc
    return scad.make_material_rmaterial(
        material_id=spec.material_id,
        name=spec.name,
        density=spec.density,
        density_unit="kg/mm^3",
        color=spec.color,
    )


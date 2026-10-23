"""AP242 STEP export for validated product packages.

``ocp`` backend: XCAF through OCP (``_step_ocp.py``).  ``native`` backend: the C++
``export_step_assembly`` (same XCAF structure, written by OpenCASCADE inside the native module).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..artifacts import materialize_definition
from simplecadapi._cpp import Assembly, Part
from ..translator.package_units import (
    ProductPackageInput,
    read_product_package_translation_units,
)

@dataclass(frozen=True, slots=True)
class ProductSTEPExportReport:
    """Observed AP242 export facts and explicit semantic limitations."""

    output_path: Path
    schema: str
    definition_ids: tuple[str, ...]
    occurrence_count: int
    material_ids: tuple[str, ...]
    metadata_item_count: int
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "schema": self.schema,
            "definition_ids": list(self.definition_ids),
            "occurrence_count": self.occurrence_count,
            "material_ids": list(self.material_ids),
            "metadata_item_count": self.metadata_item_count,
            "limitations": list(self.limitations),
        }


_LIMITATIONS = (
    "Connector, constraint, grounding, revision, content-hash, and placement semantics are encoded as named AP242 descriptive property items containing deterministically sorted JSON.",
    "The evaluated BREP and product structure are transferred through STEPCAF; canonical feature history is not reconstructed as AP242 features.",
)


def _native_definitions(root_value: Part | Assembly, units: Any) -> list[dict[str, Any]]:
    """Every definition reachable from the root, in first-visit order, as plain dicts."""

    units_by_identity = {(u.definition_kind, u.definition_id): u for u in units}
    out: dict[tuple[str, str], dict[str, Any]] = {}

    def identity(value: Part | Assembly) -> tuple[str, str]:
        if isinstance(value, Assembly):
            return ("assembly", value.assembly_id)
        return ("single_solid", value.part_id)

    def visit(value: Part | Assembly) -> str:
        key = identity(value)
        kind, definition_id = key
        if key in out:
            return definition_id
        unit = units_by_identity.get(key)
        if unit is None:
            raise RuntimeError(
                f"materialized definition {kind}:{definition_id} is absent from package units"
            )
        if isinstance(value, Part):
            entry: dict[str, Any] = {
                "id": definition_id,
                "kind": kind,
                "name": value.name or value.part_id,
                "shape": value.body,
                "metadata": {
                    "record_kind": "definition",
                    "definition_id": value.part_id,
                    "definition_kind": kind,
                    "revision": unit.revision,
                    "content_hash": unit.content_hash,
                    "connectors": [c.to_dict() for c in value.connectors],
                },
            }
            material = value.material
            if material is not None:
                density = material.density
                entry["material"] = {
                    "id": material.material_id,
                    "name": material.name or material.material_id,
                    "description": material.to_dict(),
                    "density": None if density is None else float(density),
                    "density_unit": str(material.density_unit or ""),
                }
                if material.color is not None:
                    entry["color"] = tuple(float(c) for c in material.color)
            out[key] = entry
            return definition_id
        entry = {
            "id": definition_id,
            "kind": kind,
            "name": value.name or value.assembly_id,
            "metadata": {
                "record_kind": "definition",
                "definition_id": value.assembly_id,
                "definition_kind": kind,
                "revision": unit.revision,
                "content_hash": unit.content_hash,
                "public_connectors": [c.to_dict() for c in value.public_connectors],
                "constraints": [c.to_dict() for c in value.constraints],
                "grounded_component_ids": list(value.grounded_component_ids),
            },
            "components": [],
        }
        out[key] = entry
        for component in value.components:
            child_id = visit(component.item)
            child_kind = (
                "assembly" if isinstance(component.item, Assembly) else "single_solid"
            )
            placement = component.placement
            entry["components"].append(
                {
                    "id": component.component_id,
                    "name": component.name or component.component_id,
                    "definition_id": child_id,
                    "placement": {
                        "origin": tuple(placement.origin),
                        "x_axis": tuple(placement.x_axis),
                        "y_axis": tuple(placement.y_axis),
                        "z_axis": tuple(placement.z_axis),
                    },
                    "metadata": {
                        "record_kind": "occurrence",
                        "parent_definition_id": definition_id,
                        "component_id": component.component_id,
                        "definition_id": child_id,
                        "definition_kind": child_kind,
                        "name": component.name,
                        "placement": placement.to_dict(),
                    },
                }
            )
        return definition_id

    visit(root_value)
    return list(out.values())


def export_product_package_to_step(
    data: ProductPackageInput,
    output_path: str | Path,
) -> ProductSTEPExportReport:
    """Export a validated `.scadpkg` closure as XCAF-backed AP242 STEP."""

    import simplecadapi._cpp as native

    package, units = read_product_package_translation_units(data)
    root_value = materialize_definition(package.root_definition)
    destination = Path(output_path).expanduser().resolve()
    if destination.suffix.lower() not in {".step", ".stp"}:
        raise ValueError("output_path must end in .step or .stp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    definitions = _native_definitions(root_value, units)
    root_id = (
        root_value.assembly_id if isinstance(root_value, Assembly) else root_value.part_id
    )
    report = native.export_step_assembly(definitions, root_id, destination)
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RuntimeError("STEPCAF export did not create a non-empty STEP file")
    return ProductSTEPExportReport(
        output_path=destination,
        schema=report["schema"],
        definition_ids=tuple(unit.definition_id for unit in units),
        occurrence_count=int(report["occurrence_count"]),
        material_ids=tuple(report["material_ids"]),
        metadata_item_count=int(report["metadata_item_count"]),
        limitations=_LIMITATIONS,
    )


__all__ = ["ProductSTEPExportReport", "export_product_package_to_step"]

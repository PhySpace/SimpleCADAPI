# export_product_package_to_mjcf

## API Definition

```python
def export_product_package_to_mjcf(data: ProductInput, output_path: str | Path, *, mesh_directory: str | Path | None = None, mapping_path: str | Path | None = None, linear_deflection: float = 0.15, angular_deflection_degrees: float = _DEFAULT_MJCF_ANGULAR_DEFLECTION_DEGREES, default_density_kg_m3: float | None = None) -> ProductMJCFExportReport
```

*Source: exporter/mjcf.py*

## Import Surface

- exporter namespace: `from simplecadapi import exporter` then `exporter.mjcf.export_product_package_to_mjcf(...)`

## Description

Compile a validated `.scadpkg` assembly into an MJCF model.
Fixed constraints create rigid groups. Public connector declarations resolve
endpoint ownership to their leaf connectors without changing the constraint
kind. Revolute/prismatic edges form a deterministic spanning tree. Gear,
belt, and rack-pinion relations become independent fixed-tendon
equalities. Root assembly connectors and geometry names in the
``interface.*`` namespace become MJCF sites.

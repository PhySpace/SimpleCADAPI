# export_product_package_to_stl

## API Definition

```python
def export_product_package_to_stl(data: ProductInput, output_path: str | Path, *, linear_deflection: float = 0.1, angular_deflection_degrees: float = 20.0, relative: bool = False) -> ProductSTLExportReport
```

*Source: exporter/stl.py*

## Import Surface

- exporter namespace: `from simplecadapi import exporter` then `exporter.stl.export_product_package_to_stl(...)`

## Description

Export one `.scadpkg` directly from evaluated BREP as binary STL.

`linear_deflection` is the maximum chordal deviation in product units.
`angular_deflection_degrees` limits angular deviation on curved surfaces.
No remeshing or topology reconstruction is performed.

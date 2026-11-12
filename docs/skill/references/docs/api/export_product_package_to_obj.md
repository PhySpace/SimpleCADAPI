# export_product_package_to_obj

## API Definition

```python
def export_product_package_to_obj(data: ProductInput, output_path: str | Path, *, linear_deflection: float = 0.1, angular_deflection_degrees: float = 20.0, relative: bool = False) -> ProductOBJExportReport
```

*Source: exporter/obj.py*

## Import Surface

- exporter namespace: `from simplecadapi import exporter` then `exporter.obj.export_product_package_to_obj(...)`

## Description

Export one `.scadpkg` directly from evaluated BREP as triangle OBJ.

`linear_deflection` is the maximum chordal deviation in product units.
`angular_deflection_degrees` limits angular deviation on curved surfaces.
No remeshing or topology reconstruction is performed.

# export_product_package_to_step

## API Definition

```python
def export_product_package_to_step(data: ProductInput, output_path: str | Path) -> ProductSTEPExportReport
```

*Source: exporter/step.py*

## Import Surface

- exporter namespace: `from simplecadapi import exporter` then `exporter.step.export_product_package_to_step(...)`

## Description

Export a product as XCAF-backed AP242 STEP: a validated `.scadpkg` closure (package, bytes or path), or the result of
a build (``@scad.part`` / ``@scad.assemble``) or its definition, which is packaged in memory without a scene.

# measure_part_mass_rmassreport

## API Definition

```python
def measure_part_mass_rmassreport(part: 'Part', *, density: 'float | None' = None, density_unit: 'str | None' = None) -> 'MassReport'
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import measure_part_mass_rmassreport`

## Description

Measure the volume, mass and centre of mass of a Part.

``scad.measure_part_mass_rmassreport(bracket).mass_kg`` is the mass of the part.
The part's material gives the density unless ``density`` is passed.

## Parameters

### part

- **Description**: The Part to measure.

### density

- **Description**: Density to use instead of the material's; ``None`` uses the Part's material, and without a material density every mass is ``None``.

### density_unit

- **Description**: Unit of ``density``: ``kg/m^3`` (default), ``g/cm^3``, ``kg/mm^3`` or ``g/mm^3``.

## Returns

MassReport: ``bodies`` (the Part's one ``BodyMass``: ``body_id``, ``volume_mm3``,
``mass_kg``, ``centroid_mm``) and the totals of the part (``volume_mm3``,
``mass_kg``, ``centroid_mm``).

## Raises

- **SimpleCADError**: The value is not a Part, or the density or its unit is invalid.

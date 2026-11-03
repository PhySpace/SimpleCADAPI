# measure_part_mass_rmassreport

## API Definition

```python
def measure_part_mass_rmassreport(part: 'Part', *, density: 'float | None' = None, density_unit: 'str | None' = None) -> 'MassReport'
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import measure_part_mass_rmassreport`

## Description

Measure the volume, mass and centre of mass of every body of a Part, and of the Part as a whole.

``scad.measure_part_mass_rmassreport(case).body("lid").mass_kg`` is the mass of
the lid body; ``.mass_kg`` the mass of the whole part. Every body has the
Part's material.

## Parameters

### part

- **Description**: The Part to measure (one body or several).

### density

- **Description**: Density to use instead of the material's; ``None`` uses the Part's material, and without a material density every mass is ``None``.

### density_unit

- **Description**: Unit of ``density``: ``kg/m^3`` (default), ``g/cm^3``, ``kg/mm^3`` or ``g/mm^3``.

## Returns

MassReport: ``bodies`` (one ``BodyMass`` per body, in body order: ``body_id``,
``volume_mm3``, ``mass_kg``, ``centroid_mm``) and the totals of the part
(``volume_mm3``, ``mass_kg``, volume-weighted ``centroid_mm``).

## Raises

- **SimpleCADError**: The value is not a Part, or the density or its unit is invalid.

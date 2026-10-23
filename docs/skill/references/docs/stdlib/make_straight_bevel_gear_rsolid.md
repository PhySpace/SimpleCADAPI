# make_straight_bevel_gear_rsolid

## API Definition

```python
def make_straight_bevel_gear_rsolid(n_teeth, module, pitch_angle=45.0, pressure_angle=20.0, face_width=8.0, *, addendum_factor=1.0, clearance_factor=0.25, backlash=0.0)
```

*Source: std/gear.py*

## Import Surface

- standard library: `import simplecadapi as scad` then `scad.std.gear.make_straight_bevel_gear_rsolid(...)`; direct submodule import: `from simplecadapi.std.gear import make_straight_bevel_gear_rsolid`

## Description

Create a straight bevel gear with standard metric tooth proportions.

The large-end transverse section uses the same analytic involute profile as
:func:`make_spur_gear_rsolid`. A similar small-end section is located on the
requested pitch cone and joined with ruled straight tooth surfaces.

``face_width`` is measured along the pitch-cone generator. This factory
supplies nominal tooth geometry; a released pair still requires mating-gear,
mounting-distance, contact-pattern, backlash, material, heat-treatment, and
strength checks.

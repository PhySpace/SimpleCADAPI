# make_helical_gear_rsolid

## API Definition

```python
def make_helical_gear_rsolid(n_teeth, module, pressure_angle=20.0, helix_angle=30.0, gear_height=8.0, *, addendum_factor=1.0, clearance_factor=0.25, backlash=0.0)
```

*Source: std/gear.py*

## Import Surface

- standard library: `import simplecadapi as scad` then `scad.std.gear.make_helical_gear_rsolid(...)`; direct submodule import: `from simplecadapi.std.gear import make_helical_gear_rsolid`

## Description

Create an involute helical gear.

Non-zero helix angles use a continuous twisted sweep along the gear axis.
An auxiliary-spine rotation law preserves the profile while generating one
continuous side face per profile edge instead of one face per loft interval.

## Parameters

### n_teeth

- **Type**: `int`
- **Description**: Number of teeth (>= 3).

### module

- **Type**: `float`
- **Description**: Gear module in mm.

### pressure_angle

- **Type**: `float, default 20`
- **Description**: Pressure angle in degrees.

### helix_angle

- **Type**: `float, default 30`
- **Description**: Helix angle in degrees.

### gear_height

- **Type**: `float, default 8.0`
- **Description**: Gear thickness along Z in mm.

### addendum_factor

- **Type**: `float, default 1.0`
- **Description**: Tooth addendum as a multiple of module.

### clearance_factor

- **Type**: `float, default 0.25`
- **Description**: Root clearance beyond the addendum, as a multiple of module.

### backlash

- **Type**: `float, default 0.0`
- **Description**: Circumferential tooth-thickness reduction at the pitch circle in mm.

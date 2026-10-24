# make_herringbone_gear_rsolid

## API Definition

```python
def make_herringbone_gear_rsolid(n_teeth, module, pressure_angle=20.0, helix_angle=32.0, gear_height=10.0, *, addendum_factor=1.0, clearance_factor=0.25, backlash=0.0)
```

*Source: std/gear.py*

## Import Surface

- standard library: `import simplecadapi as scad` then `scad.std.gear.make_herringbone_gear_rsolid(...)`; direct submodule import: `from simplecadapi.std.gear import make_herringbone_gear_rsolid`

## Description

Create an involute herringbone (double-helical) gear.

Each half uses a continuous twisted sweep with opposite handedness. The two
halves share the rotated center profile and are fused into one solid.

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

- **Type**: `float, default 32`
- **Description**: Helix angle of each half in degrees.

### gear_height

- **Type**: `float, default 10.0`
- **Description**: Total gear thickness along Z in mm.

### addendum_factor

- **Type**: `float, default 1.0`
- **Description**: Tooth addendum as a multiple of module.

### clearance_factor

- **Type**: `float, default 0.25`
- **Description**: Root clearance beyond the addendum, as a multiple of module.

### backlash

- **Type**: `float, default 0.0`
- **Description**: Circumferential tooth-thickness reduction at the pitch circle in mm.

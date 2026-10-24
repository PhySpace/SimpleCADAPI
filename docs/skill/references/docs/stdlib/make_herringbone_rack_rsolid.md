# make_herringbone_rack_rsolid

## API Definition

```python
def make_herringbone_rack_rsolid(module, n_teeth=10, pressure_angle=20.0, helix_angle=30.0, rack_height=10.0)
```

*Source: std/gear.py*

## Import Surface

- standard library: `import simplecadapi as scad` then `scad.std.gear.make_herringbone_rack_rsolid(...)`; direct submodule import: `from simplecadapi.std.gear import make_herringbone_rack_rsolid`

## Description

Create a herringbone rack.

## Parameters

### module

- **Type**: `float`
- **Description**: Gear module in mm (tooth pitch = pi * module).

### n_teeth

- **Type**: `int, default 10`
- **Description**: Number of teeth along the rack.

### pressure_angle

- **Type**: `float, default 20`
- **Description**: Pressure angle in degrees.

### helix_angle

- **Type**: `float, default 30`
- **Description**: Helix angle of each half in degrees.

### rack_height

- **Type**: `float, default 10.0`
- **Description**: Total rack thickness along Z in mm.

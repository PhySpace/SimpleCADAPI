# make_helical_rack_rsolid

## API Definition

```python
def make_helical_rack_rsolid(module, n_teeth=10, pressure_angle=20.0, helix_angle=25.0, rack_height=8.0)
```

*Source: std/gear.py*

## Import Surface

- standard library: `import simplecadapi as scad` then `scad.std.gear.make_helical_rack_rsolid(...)`; direct submodule import: `from simplecadapi.std.gear import make_helical_rack_rsolid`

## Description

Create a helical rack.

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

- **Type**: `float, default 25`
- **Description**: Helix angle in degrees.

### rack_height

- **Type**: `float, default 8.0`
- **Description**: Rack thickness along Z in mm.

# make_herringbone_ring_gear_rsolid

## API Definition

```python
def make_herringbone_ring_gear_rsolid(n_teeth, module, pressure_angle=20.0, helix_angle=30.0, gear_height=10.0, rim_thickness=3.0, backlash=0.0, *, addendum_factor=1.0, clearance_factor=0.25)
```

*Source: std/gear.py*

## Import Surface

- standard library: `import simplecadapi as scad` then `scad.std.gear.make_herringbone_ring_gear_rsolid(...)`; direct submodule import: `from simplecadapi.std.gear import make_herringbone_ring_gear_rsolid`

## Description

Create an internal herringbone ring gear.

The multi-loop ring face is swept as two continuous twisted-sweep halves
with opposite handedness sharing the rotated center section, then fused,
mirroring the external herringbone gear construction.

## Parameters

### n_teeth

- **Type**: `int`
- **Description**: Number of internal teeth (>= 3).

### module

- **Type**: `float`
- **Description**: Gear module in mm.

### pressure_angle

- **Type**: `float, default 20`
- **Description**: Pressure angle in degrees.

### helix_angle

- **Type**: `float, default 30`
- **Description**: Helix angle of each half in degrees.

### gear_height

- **Type**: `float, default 10.0`
- **Description**: Total ring gear thickness along Z in mm.

### rim_thickness

- **Type**: `float, default 3.0`
- **Description**: Thickness of the rim beyond the tooth roots in mm.

### backlash

- **Type**: `float, default 0.0`
- **Description**: Circumferential tooth-space clearance at the pitch circle in mm.

### addendum_factor

- **Type**: `float, default 1.0`
- **Description**: Internal tooth addendum as a multiple of module.

### clearance_factor

- **Type**: `float, default 0.25`
- **Description**: Internal tooth root clearance beyond the addendum, as a multiple of module.

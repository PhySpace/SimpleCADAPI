# make_cycloidal_disc_rsolid

## API Definition

```python
def make_cycloidal_disc_rsolid(n_lobes, ring_pin_pitch_radius, roller_radius, eccentricity, gear_height=6.0, *, bore_radius=0.0, output_pin_count=0, output_pin_pitch_radius=0.0, output_pin_clearance_radius=0.0, output_pin_phase=0.0, sample_count_per_lobe=33, spline_tolerance=0.005, max_control_points=20)
```

*Source: std/gear.py*

## Import Surface

- standard library: `import simplecadapi as scad` then `scad.std.gear.make_cycloidal_disc_rsolid(...)`; direct submodule import: `from simplecadapi.std.gear import make_cycloidal_disc_rsolid`

## Description

Create a cycloidal reducer disc for a one-tooth-difference pin ring.

This is a single-disc geometric standard part. Real compact reducers often
stack two identical-lobe discs to balance output-pin side loads. In that
assembly-level pattern, separate two concepts that are easy to confuse:

- Place the two input eccentric cam centers 180 degrees apart, for example
``(+e, 0)`` and ``(-e, 0)``, so their orbit loads oppose each other.
- Tooth-index the second cycloidal profile by half a lobe, not by a full
180 degree shape rotation. For a disc with ``n_lobes`` lobes, that
geometric body phase is ``180 / n_lobes`` degrees. A 10-lobe disc rotated
by 180 degrees is exactly five full lobe pitches and is visually and
mechanically equivalent to no tooth-index phase change.

If output-pin clearance holes must stay aligned to one shared output pin
set, compensate the second disc's ``output_pin_phase`` by subtracting the
same body phase before rotating the finished disc body.

## Parameters

### n_lobes

- **Type**: `int`
- **Description**: Number of cycloidal lobes. The matching fixed pin ring has

### ``n_lobes + 1`` pins and gives a single-stage ``n_lobes

- **Description**: 1`` reduction.

### ring_pin_pitch_radius

- **Type**: `float`
- **Description**: Radius of the fixed ring pin centers in mm.

### roller_radius

- **Type**: `float`
- **Description**: Radius of the fixed ring pins or rollers used to offset the profile.

### eccentricity

- **Type**: `float`
- **Description**: Input crank eccentricity in mm.

### gear_height

- **Type**: `float, default 6.0`
- **Description**: Disc thickness / extrusion height along Z in mm.

### bore_radius

- **Type**: `float, default 0.0`
- **Description**: Optional central bore radius. Zero leaves the disc unbored.

### output_pin_count

- **Type**: `int, default 0`
- **Description**: Optional number of circular output-pin clearance holes.

### output_pin_pitch_radius

- **Type**: `float, default 0.0`
- **Description**: Radius of the output-pin clearance hole centers in mm.

### output_pin_clearance_radius

- **Type**: `float, default 0.0`
- **Description**: Radius of each output-pin clearance hole in mm.

### output_pin_phase

- **Type**: `float, default 0.0`
- **Description**: Angular phase of the first output-pin clearance hole in degrees, in the unrotated disc's local frame. When a finished disc is rotated to create a tooth-index phase in a twin-disc stack, subtract that same rotation from ``output_pin_phase`` if the clearance holes should remain aligned to the same global output pins.

### sample_count_per_lobe

- **Type**: `int, default 33`
- **Description**: Number of analytic samples fitted into each lobe B-spline segment.

### spline_tolerance

- **Type**: `float, default 0.005`
- **Description**: Cubic B-spline fit tolerance in mm.

### max_control_points

- **Type**: `int, default 20`
- **Description**: Maximum poles allowed for each fitted lobe segment.

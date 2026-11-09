# make_workplane_normal_to_curve_rworkplane

## API Definition

```python
def make_workplane_normal_to_curve_rworkplane(curve, at=0.0, *, x_dir=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_workplane_normal_to_curve_rworkplane`

## Description

Create a workplane normal to a curve: the plane of a sweep profile.

origin = the point at ``at`` (a fraction of the curve's length: 0 = start, 1 = end); normal = the direction of
travel there; x = ``x_dir`` projected onto the plane, or global Z made square to the normal (global X when the
tangent is near Z).

Recorded: the node takes the inputs as ordered references, so a model-JSON replay builds the frame again from the
geometry as it is then, and a sketch on the workplane (``plane=wp``) or an operation inside ``with wp:`` follows it.

``start = scad.make_workplane_normal_to_curve_rworkplane(path, 0)``;
``profile = ... make_sketch_rsketch("profile", plane=start) ...``; ``sweep_rsolid(profile, path)``.

## Parameters

### curve

- **Description**: An Edge or a Wire (the sweep path).

### at

- **Description**: The fraction of the length, in [0, 1].

### x_dir

- **Description**: The direction of x, projected onto the plane.

## Returns

SimpleWorkplane: a frame in world coordinates (``origin``, ``normal``, ``x_dir``, ``y_dir``, ``plane``) that is
also a context manager: ``with wp:`` makes it the current coordinate system, ``make_sketch_rsketch(plane=wp)``
draws on it. It is a value: enter it again in later code, pickle it (the notebook cell cache does).

## Raises

- **SimpleCADError**: ``at`` is outside [0, 1], the curve has no length, or ``x_dir`` is along the tangent.

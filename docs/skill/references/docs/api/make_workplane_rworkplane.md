# make_workplane_rworkplane

## API Definition

```python
def make_workplane_rworkplane(origin=(0, 0, 0), normal=(0, 0, 1), x_dir=(1, 0, 0))
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_workplane_rworkplane`

## Description

Create a recorded workplane from an origin, a normal and an x direction.

The recorded spelling of ``SimpleWorkplane(origin, normal, x_dir)``: the three vectors are read in the current
coordinate system (inside ``with other_wp:`` they are local to it). An ``x_dir`` along the normal is replaced by a
perpendicular; otherwise x is ``x_dir`` made square to the normal.

``wp = scad.make_workplane_rworkplane((0, 0, 40), (0, 1, 0))`` then ``with wp: ...`` or
``scad.make_sketch_rsketch("rib", plane=wp)``.

## Parameters

### origin

- **Description**: The origin of the plane.

### normal

- **Description**: The plane's normal (its local z axis); its length does not matter.

### x_dir

- **Description**: The direction of the local x axis, projected onto the plane.

## Returns

SimpleWorkplane: a frame in world coordinates (``origin``, ``normal``, ``x_dir``, ``y_dir``, ``plane``) that is
also a context manager: ``with wp:`` makes it the current coordinate system, ``make_sketch_rsketch(plane=wp)``
draws on it. It is a value: enter it again in later code, pickle it (the notebook cell cache does).

## Raises

- **SimpleCADError**: The normal is zero or a value is not finite.

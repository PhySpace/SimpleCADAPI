# make_workplane_from_points_rworkplane

## API Definition

```python
def make_workplane_from_points_rworkplane(a, b, c)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_workplane_from_points_rworkplane`

## Description

Create a workplane through three points: origin at ``a``, x towards ``b``, normal = (b - a) x (c - a).

Recorded: the node takes the inputs as ordered references, so a model-JSON replay builds the frame again from the
geometry as it is then, and a sketch on the workplane (``plane=wp``) or an operation inside ``with wp:`` follows it.

``scad.make_workplane_from_points_rworkplane(v0, v1, v2)`` with three picked vertices; points given as
numbers are recorded as numbers.

## Parameters

### a

- **Description**: A Vertex of the model or a point (current coordinate system): the origin.

### b

- **Description**: A Vertex or a point: x points from ``a`` towards it.

### c

- **Description**: A Vertex or a point on the positive-y side of the plane.

## Returns

SimpleWorkplane: a frame in world coordinates (``origin``, ``normal``, ``x_dir``, ``y_dir``, ``plane``) that is
also a context manager: ``with wp:`` makes it the current coordinate system, ``make_sketch_rsketch(plane=wp)``
draws on it. It is a value: enter it again in later code, pickle it (the notebook cell cache does).

## Raises

- **SimpleCADError**: The three points lie on one line or two coincide.

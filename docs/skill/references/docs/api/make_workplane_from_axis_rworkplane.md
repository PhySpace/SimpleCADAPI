# make_workplane_from_axis_rworkplane

## API Definition

```python
def make_workplane_from_axis_rworkplane(axis, angle=0.0, *, face=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_workplane_from_axis_rworkplane`

## Description

Create a workplane through an axis, turned about it by an angle.

The axis is a straight edge (from its start, along it) or a circular edge (its centre line: through the centre,
along the circle's normal). x = the axis direction. At ``angle=0`` the plane is the plane of ``face`` (a planar face
containing the axis direction, usually one the edge bounds) or, without one, the plane whose normal is global Z
(global X for an axis along Z) made square to the axis; ``angle`` turns it right-handed about the axis.

Recorded: the node takes the inputs as ordered references, so a model-JSON replay builds the frame again from the
geometry as it is then, and a sketch on the workplane (``plane=wp``) or an operation inside ``with wp:`` follows it.

``scad.make_workplane_from_axis_rworkplane(edge, 30, face=top)``: a plane hinged on an edge of the top
face, tilted 30 degrees.

## Parameters

### axis

- **Description**: A straight or circular Edge.

### angle

- **Description**: The turn about the axis, in degrees.

### face

- **Description**: The planar Face the plane starts from at angle 0.

## Returns

SimpleWorkplane: a frame in world coordinates (``origin``, ``normal``, ``x_dir``, ``y_dir``, ``plane``) that is
also a context manager: ``with wp:`` makes it the current coordinate system, ``make_sketch_rsketch(plane=wp)``
draws on it. It is a value: enter it again in later code, pickle it (the notebook cell cache does).

## Raises

- **SimpleCADError**: The edge is neither straight nor circular, the face is not planar, or the face's normal is along the axis.

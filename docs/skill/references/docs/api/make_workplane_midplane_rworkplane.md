# make_workplane_midplane_rworkplane

## API Definition

```python
def make_workplane_midplane_rworkplane(face_a, face_b)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_workplane_midplane_rworkplane`

## Description

Create the workplane halfway between two parallel planar faces (a symmetry plane).

normal and x come from ``face_a``; origin = the middle between the centre of ``face_a`` and its projection onto the
plane of ``face_b``.

Recorded: the node takes the inputs as ordered references, so a model-JSON replay builds the frame again from the
geometry as it is then, and a sketch on the workplane (``plane=wp``) or an operation inside ``with wp:`` follows it.

``mid = scad.make_workplane_midplane_rworkplane(left_wall, right_wall)``; mirror or sketch on it.

## Parameters

### face_a

- **Description**: A planar Face; it gives the normal and x.

### face_b

- **Description**: A planar Face parallel to it.

## Returns

SimpleWorkplane: a frame in world coordinates (``origin``, ``normal``, ``x_dir``, ``y_dir``, ``plane``) that is
also a context manager: ``with wp:`` makes it the current coordinate system, ``make_sketch_rsketch(plane=wp)``
draws on it. It is a value: enter it again in later code, pickle it (the notebook cell cache does).

## Raises

- **SimpleCADError**: A face is not planar or the faces are not parallel.

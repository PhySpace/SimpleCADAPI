# make_workplane_offset_rworkplane

## API Definition

```python
def make_workplane_offset_rworkplane(base='XY', offset=(0.0, 0.0, 0.0), rx=0.0, ry=0.0, rz=0.0)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_workplane_offset_rworkplane`

## Description

Create a workplane moved and turned relative to a workplane or a named plane.

The editor's move and turn handles write this operation: a plane placed by hand on a base, without any model geometry.

## Parameters

### base

- **Description**: The plane it is placed on: a workplane value (made by a ``make_workplane_*_rworkplane`` operation, recorded as this node's input so the new plane follows it when it moves) or a named plane ``"XY"`` / ``"XZ"`` / ``"YZ"`` (axes as sketches read them).

### offset

- **Description**: How far the origin moves, ``(dx, dy, dz)`` along the base's own x, y and normal.

### rx, ry, rz

- **Description**: Turns in degrees about the base's own axes, applied in that order, each about the axis as the previous turn left it (R = Rx(rx) Ry(ry) Rz(rz) in the base's frame).

## Returns

SimpleWorkplane: The new frame. Use it as a sketch plane (``plane=wp``) or as a context (``with wp:``).

## Examples

```python
>>> wp = scad.make_workplane_offset_rworkplane("XY", offset=(0, 0, 20), rx=30)
>>> lid = scad.make_workplane_offset_rworkplane(wp, offset=(0, 0, 5))   # follows wp
```

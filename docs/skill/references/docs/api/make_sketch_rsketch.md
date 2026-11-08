# make_sketch_rsketch

## API Definition

```python
def make_sketch_rsketch(name=None, *, plane='XY', sketch_id=None)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import make_sketch_rsketch`

## Description

Create an empty declarative sketch document.

Use this API, not concrete edge/wire constructors, when the intent is to
build a sketch profile with constraints.

``plane`` is ``"XY"``, ``"XZ"``, ``"YZ"`` or a frame mapping ``{origin, x_axis, y_axis}`` (read in the current
coordinate system), or a Workplane value (``make_workplane_*_rworkplane`` / ``SimpleWorkplane``), whose world frame is used
as it is. A sketch on a recorded workplane names its node: a replay takes the frame from the replayed workplane, so a
sketch on a face's workplane follows the face.

# move_curve_poles_redge

## API Definition

```python
def move_curve_poles_redge(edge, moves, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import move_curve_poles_redge`

## Description

Move some poles of an edge's B-spline curve: ``moves`` maps a 0-based pole index to its new position.

The sparse form of ``set_curve_poles_redge`` (what a control-point drag records). Only B-spline and Bezier curves are edited; a line, circle or other analytic edge is refused with a message naming ``convert_to_bspline_redge``, the explicit conversion step. Returns a new Edge; the input is not changed. Recorded: the Edge continues in the node's history, so tags and references follow.

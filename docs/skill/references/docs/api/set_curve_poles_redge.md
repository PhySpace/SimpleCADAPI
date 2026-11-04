# set_curve_poles_redge

## API Definition

```python
def set_curve_poles_redge(edge, poles, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import set_curve_poles_redge`

## Description

Set every pole of an edge's B-spline curve.

``poles`` lists exactly as many points as the curve has poles (``inspect_curve_rcurvedata``), in order, in the current coordinate system. Degree, knots and weights stay. Only B-spline and Bezier curves are edited; a line, circle or other analytic edge is refused with a message naming ``convert_to_bspline_redge``, the explicit conversion step. Returns a new Edge; the input is not changed. Recorded: the Edge continues in the node's history, so tags and references follow.

# set_curve_weights_redge

## API Definition

```python
def set_curve_weights_redge(edge, weights, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import set_curve_weights_redge`

## Description

Set the weights of an edge's B-spline curve: one positive value per pole.

A weight above 1 pulls the curve toward its pole; any weight other than 1 makes the curve rational. Only B-spline and Bezier curves are edited; a line, circle or other analytic edge is refused with a message naming ``convert_to_bspline_redge``, the explicit conversion step. Returns a new Edge; the input is not changed. Recorded: the Edge continues in the node's history, so tags and references follow.

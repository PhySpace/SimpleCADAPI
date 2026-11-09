# elevate_curve_degree_redge

## API Definition

```python
def elevate_curve_degree_redge(edge, degree, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import elevate_curve_degree_redge`

## Description

Raise the degree of an edge's B-spline curve to ``degree``.

The shape does not change; poles are added. Only B-spline and Bezier curves are edited; a line, circle or other analytic edge is refused with a message naming ``convert_to_bspline_redge``, the explicit conversion step. Returns a new Edge; the input is not changed. Recorded: the Edge continues in the node's history, so tags and references follow.

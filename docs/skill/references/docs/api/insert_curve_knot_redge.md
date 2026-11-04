# insert_curve_knot_redge

## API Definition

```python
def insert_curve_knot_redge(edge, parameter, multiplicity=1, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import insert_curve_knot_redge`

## Description

Insert a knot into an edge's B-spline curve at ``parameter`` (strictly inside the edge's parameter range).

The shape does not change; the curve gains ``multiplicity`` poles near that parameter, for finer local editing. The knot's total multiplicity may not exceed the degree. Only B-spline and Bezier curves are edited; a line, circle or other analytic edge is refused with a message naming ``convert_to_bspline_redge``, the explicit conversion step. Returns a new Edge; the input is not changed. Recorded: the Edge continues in the node's history, so tags and references follow.

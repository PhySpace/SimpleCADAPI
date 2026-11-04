# convert_to_bspline_redge

## API Definition

```python
def convert_to_bspline_redge(edge, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import convert_to_bspline_redge`

## Description

Convert an edge's curve to a B-spline, so the curve edits can work on it.

The explicit, recorded step for analytic edges (a line becomes a degree-1 B-spline, a circle or arc a rational quadratic); the shape does not change, its parameter range may. Returns a new Edge; the input is not changed. Recorded: the Edge continues in the node's history, so tags and references follow.

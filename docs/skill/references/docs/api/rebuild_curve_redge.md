# rebuild_curve_redge

## API Definition

```python
def rebuild_curve_redge(edge, degree=3, pole_count=None, *, tolerance=0.001, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import rebuild_curve_redge`

## Description

Refit an edge's curve as a B-spline of ``degree`` with ``pole_count`` poles, or with the fewest poles that keep within ``tolerance``.

A least-squares fit with uniform clamped knots in the edge's own parameter range; the end points are kept. Works on any edge, analytic ones too (the result is a B-spline). Returns a new Edge; the input is not changed. Recorded: the Edge continues in the node's history, so tags and references follow.

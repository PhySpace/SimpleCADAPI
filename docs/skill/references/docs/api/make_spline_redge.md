# make_spline_redge

## API Definition

```python
def make_spline_redge(*, control_points, degree=3, knots=None, multiplicities=None, weights=None, periodic=False)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_spline_redge`

## Description

Create an exact B-spline edge from named control-point parameters.

Pass sampled curve points through `fit_cubic_bspline_control_points(...)` first,
then pass the result fields explicitly as `control_points=...`, `knots=...`,
and `multiplicities=...`. `control_points` are poles, not interpolation
points; the curve generally does not pass through interior poles.

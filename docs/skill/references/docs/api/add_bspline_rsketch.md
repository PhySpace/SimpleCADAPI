# add_bspline_rsketch

## API Definition

```python
def add_bspline_rsketch(sketch, entity_id, start, end, control_points, degree=3, knots=None, multiplicities=None, weights=None, periodic=False, *, construction=False)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import add_bspline_rsketch`

## Description

Add a B-spline curve entity to a sketch.

The start/end point refs link the B-spline into a closed profile
loop. A closed curve may reuse one seam ref for both endpoints.
Control points may be literal 2-D coordinates or point refs. A periodic
seam links topology without replacing the periodic curve's poles.

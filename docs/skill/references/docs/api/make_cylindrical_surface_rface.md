# make_cylindrical_surface_rface

## API Definition

```python
def make_cylindrical_surface_rface(radius, u_range, v_range, origin=[0.0, 0.0, 0.0], axis=[0.0, 0.0, 1.0], x_direction=None, *, tolerance=1e-07, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_cylindrical_surface_rface`

## Description

Create a finite cylindrical carrier Face over explicit U/V ranges.

``radius``, V values, and ``tolerance`` use model length units. U values
are unitless raw radians, must increase, and may span at most one
revolution. Unit-aware angle expressions are not accepted for U because
the existing expression evaluator returns canonical angles in degrees.

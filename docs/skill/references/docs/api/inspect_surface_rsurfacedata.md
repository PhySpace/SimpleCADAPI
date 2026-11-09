# inspect_surface_rsurfacedata

## API Definition

```python
def inspect_surface_rsurfacedata(face)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import inspect_surface_rsurfacedata`

## Description

Read the NURBS data of a face's surface: what the surface edits work on.

Returns ``{type, analytic, editable, conversion, u_degree, v_degree, poles, weights, u_knots, v_knots, u_multiplicities, v_multiplicities, u_periodic, v_periodic, rational, domain, reversed, trimmed, uv_bounds}``. ``poles`` is a grid of rows along U, each row running along V (as ``make_bezier_surface_rface`` takes it), in the current coordinate system; indices are 0-based ``(row, column)``. ``domain`` is the surface's ``[u1, u2, v1, v2]``, ``uv_bounds`` the face's; ``trimmed`` says whether the face is bounded by anything but the surface's own domain. For a plane, cylinder or other analytic surface ``editable`` is false, ``conversion`` is ``"convert_to_bspline_rface"`` and the data is what that conversion would produce. Not recorded in the graph.

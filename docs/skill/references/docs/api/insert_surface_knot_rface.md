# insert_surface_knot_rface

## API Definition

```python
def insert_surface_knot_rface(face, direction, parameter, multiplicity=1, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import insert_surface_knot_rface`

## Description

Insert a U or V knot into a face's B-spline surface at ``parameter`` (strictly inside the surface's domain in that direction).

The shape does not change; the pole grid gains ``multiplicity`` rows (``"U"``) or columns (``"V"``). The face keeps its trimming exactly: its boundary loops stay where they are in the surface's (u, v) space and the 3D boundary edges are recomputed on the edited surface. Only B-spline and Bezier surfaces are edited; a plane, cylinder or other analytic face is refused with a message naming ``convert_to_bspline_rface``, the explicit conversion step. Returns a new Face; the input is not changed. Recorded: the Face and its boundary edges continue in the node's history, so tags and references follow.

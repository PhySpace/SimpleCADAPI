# set_surface_poles_rface

## API Definition

```python
def set_surface_poles_rface(face, poles, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import set_surface_poles_rface`

## Description

Set every pole of a face's B-spline surface.

``poles`` is the full grid (rows along U, each row along V), the same size as ``inspect_surface_rsurfacedata`` reports, in the current coordinate system. The face keeps its trimming exactly: its boundary loops stay where they are in the surface's (u, v) space and the 3D boundary edges are recomputed on the edited surface. Only B-spline and Bezier surfaces are edited; a plane, cylinder or other analytic face is refused with a message naming ``convert_to_bspline_rface``, the explicit conversion step. Returns a new Face; the input is not changed. Recorded: the Face and its boundary edges continue in the node's history, so tags and references follow.

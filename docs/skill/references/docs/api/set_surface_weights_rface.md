# set_surface_weights_rface

## API Definition

```python
def set_surface_weights_rface(face, weights, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import set_surface_weights_rface`

## Description

Set the weights of a face's B-spline surface: a grid of positive values, one per pole.

The face keeps its trimming exactly: its boundary loops stay where they are in the surface's (u, v) space and the 3D boundary edges are recomputed on the edited surface. Only B-spline and Bezier surfaces are edited; a plane, cylinder or other analytic face is refused with a message naming ``convert_to_bspline_rface``, the explicit conversion step. Returns a new Face; the input is not changed. Recorded: the Face and its boundary edges continue in the node's history, so tags and references follow.

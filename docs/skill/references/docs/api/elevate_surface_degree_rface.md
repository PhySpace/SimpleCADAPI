# elevate_surface_degree_rface

## API Definition

```python
def elevate_surface_degree_rface(face, u_degree=None, v_degree=None, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import elevate_surface_degree_rface`

## Description

Raise the U and/or V degree of a face's B-spline surface.

Give ``u_degree``, ``v_degree`` or both; a degree that is given is at least the current one and one of them is higher. The shape does not change; poles are added. The face keeps its trimming exactly: its boundary loops stay where they are in the surface's (u, v) space and the 3D boundary edges are recomputed on the edited surface. Only B-spline and Bezier surfaces are edited; a plane, cylinder or other analytic face is refused with a message naming ``convert_to_bspline_rface``, the explicit conversion step. Returns a new Face; the input is not changed. Recorded: the Face and its boundary edges continue in the node's history, so tags and references follow.

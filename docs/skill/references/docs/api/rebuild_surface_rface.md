# rebuild_surface_rface

## API Definition

```python
def rebuild_surface_rface(face, u_degree=3, v_degree=3, u_pole_count=None, v_pole_count=None, *, tolerance=0.001, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import rebuild_surface_rface`

## Description

Refit a face's surface as a B-spline of the given degrees and pole counts, or with the fewest poles that keep within ``tolerance``.

Give both pole counts or neither. A least-squares fit in the face's own (u, v) parametrisation (over the surface's domain for a B-spline, over the face's bounds otherwise), so the face keeps its trimming. Works on any face. Returns a new Face; the input is not changed. Recorded: the Face and its boundary edges continue in the node's history, so tags and references follow.

# trim_surface_rface

## API Definition

```python
def trim_surface_rface(carrier, outer, holes=[], *, tolerance=1e-07, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import trim_surface_rface`

## Description

Trim a carrier Face to exactly one connected Face.

Existing carrier bounds and holes are preserved by intersecting them with
the requested closed, simple outer loop and optional closed, simple holes.
Empty or disconnected intersections are rejected. Every trim curve must
lie on the carrier within ``tolerance``. Periodic carriers do not support
holes; their outer loop must fit within one seam period without crossing
the seam.

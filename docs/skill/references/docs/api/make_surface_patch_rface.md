# make_surface_patch_rface

## API Definition

```python
def make_surface_patch_rface(boundaries, *, points=[], settings=None, holes=[], tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_surface_patch_rface`

## Description

Fill a constrained boundary network into one Face, optionally with holes.

The filling kernel re-fits each boundary edge, so adjacent patches built
with this operation do not keep identical shared boundary curves. When
several patches must share exact boundary edges and sew into one closed
shell, build each patch with ``make_gordon_surface_rface`` from a shared
profile/guide edge network instead.

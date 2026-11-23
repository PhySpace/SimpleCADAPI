# make_surface_patch_rface

## API Definition

```python
def make_surface_patch_rface(boundaries, *, points=[], settings=None, holes=[], tag_prefix=None, strategy_graph_patch=False)
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

``strategy_graph_patch=True`` fills with the kernel's graph patch instead: ``boundaries`` must be one ordered closed loop of 3 to 64 edges, each an edge of its ``support`` face, with continuity C0, G1 or G2 per edge; ``points``, ``holes`` and ``settings`` are not accepted. The patch is a degree-8 variational surface trimmed by the projected boundary. It meets its supports exactly where a degree-8 graph can (planar supports); on curved supports (cylinder, sphere, B-spline) it continues the supports' own surfaces over the hole and is accepted within 1e-3 mm of the support edges, 1e-3 rad of their normals (G1) and 5% of their curvature (G2), its edge tolerances covering that gap, so the face can be sewn to its supports. Loops that cannot be represented over one plane (seen along the fitted normal) are refused with ``ValueError``. Needs a kernel built with the SDK's OCCT patch set (``fillet-robustness-4``).

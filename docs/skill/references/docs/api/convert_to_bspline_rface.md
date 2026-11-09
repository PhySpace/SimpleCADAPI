# convert_to_bspline_rface

## API Definition

```python
def convert_to_bspline_rface(face, *, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import convert_to_bspline_rface`

## Description

Convert a face's surface (and its boundary curves) to B-splines, so the surface edits can work on it.

The explicit, recorded step for analytic faces (planes, cylinders, cones, spheres, ...); the shape and the trimming do not change, the (u, v) parametrisation may. Returns a new Face; the input is not changed. Recorded: the Face and its boundary edges continue in the node's history, so tags and references follow.

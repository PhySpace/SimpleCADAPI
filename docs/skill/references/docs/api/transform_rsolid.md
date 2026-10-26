# transform_rsolid

## API Definition

```python
def transform_rsolid(solid: Solid, matrix: Sequence[Sequence[float]]) -> Solid
```

*Source: operators/deformation.py*

## Import Surface

- top-level: `from simplecadapi import transform_rsolid`

## Description

Apply a finite nonsingular 4x4 affine matrix in the current frame.

General affine transformations include shear and reflection. Perspective
matrices and singular maps cannot define a solid and are rejected.

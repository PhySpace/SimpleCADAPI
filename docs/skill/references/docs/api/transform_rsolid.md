# transform_rsolid

## API Definition

```python
def transform_rsolid(solid: Solid, matrix: Sequence[Sequence[float]]) -> Solid
```

*Source: operators/deformation.py*

## Import Surface

- top-level: `from simplecadapi import transform_rsolid`

## Description

Apply a finite nonsingular 4x4 affine matrix in the current coordinate system.

The matrix may include shear, reflection and nonuniform scale. Perspective
matrices and singular maps cannot define a solid and are rejected. The
input geometry stays unchanged. The operation is recorded as
``make_transform_rsolid`` for graph replay; topology tag lineage is partial.

## Parameters

### solid

- **Description**: The solid to transform.

### matrix

- **Description**: A 4x4 affine matrix (row-major, last row ``0 0 0 1``), finite and nonsingular, in current coordinate-system coordinates.

## Returns

The transformed solid.

## Raises

- **ValueError**: The matrix is not a finite 4x4 affine matrix, is singular or a perspective map, or the kernel could not transform the solid.

# scale_rsolid

## API Definition

```python
def scale_rsolid(solid: Solid, factors: Sequence[float], center: Sequence[float] = (0, 0, 0)) -> Solid
```

*Source: operators/transform.py*

## Import Surface

- top-level: `from simplecadapi import scale_rsolid`

## Description

Scale a solid along the current coordinate system's axes about a center.

The three factors must be finite and nonzero. A uniform scale preserves
analytic curves and surfaces; a nonuniform scale uses the CAD kernel's
general affine transform. The source solid stays unchanged. The operation
is recorded as ``make_scale_rsolid`` for graph replay; topology tag lineage
is conservatively partial.

## Parameters

### solid

- **Description**: The solid to scale.

### factors

- **Description**: Scale factors along the x, y and z axes of the current coordinate system; finite and nonzero.

### center

- **Description**: The fixed point of the scaling, in current coordinate-system coordinates.

## Returns

The scaled solid.

## Raises

- **ValueError**: A factor is zero or not finite, or the kernel could not scale the solid.

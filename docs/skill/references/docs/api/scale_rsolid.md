# scale_rsolid

## API Definition

```python
def scale_rsolid(solid: Solid, factors: Sequence[float], center: Sequence[float] = (0, 0, 0)) -> Solid
```

*Source: operators/deformation.py*

## Import Surface

- top-level: `from simplecadapi import scale_rsolid`

## Description

Scale along current coordinate-system axes about an explicit center.

Every factor must be finite and nonzero. A uniform scale preserves analytic
geometry; a nonuniform scale converts curves/surfaces where the kernel needs
it. The input is unchanged and this operation is recorded for graph replay.

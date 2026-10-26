# offset_rsolid

## API Definition

```python
def offset_rsolid(solid: Solid, amount: ScalarLike, openings: Sequence[Face] | ShapeSelector = (), *, tolerance: float = 0.0001, kind: str = 'ARC') -> Solid
```

*Source: operators/deformation.py*

## Import Surface

- top-level: `from simplecadapi import offset_rsolid`

## Description

Offset a solid outward (positive) or inward (negative).

Selected openings form an open shell. Empty openings produce the closed
offset solid. This is distinct from shell_rsolid's positive inward wall
thickness, and supports both signs and ARC/INTERSECTION joins explicitly.

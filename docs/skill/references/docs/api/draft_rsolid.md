# draft_rsolid

## API Definition

```python
def draft_rsolid(solid: Solid, faces_to_draft: Sequence[Face] | ShapeSelector, angle: ScalarLike, plane_origin: Sequence[float] = (0, 0, 0), plane_normal: Sequence[float] = (0, 0, 1)) -> Solid
```

*Source: operators/draft.py*

## Import Surface

- top-level: `from simplecadapi import draft_rsolid`

## Description

Draft planar, cylindrical or conical faces by a signed angle in degrees.

The neutral plane fixes the unchanged section. Its origin and normal are in
current coordinate-system coordinates. Face selection is checked against
the input body and retained as graph inputs for strict replay. The original
solid is preserved. Other surface families are explicitly rejected.

# draft_rsolid

## API Definition

```python
def draft_rsolid(solid: Solid, faces_to_draft: Sequence[Face] | ShapeSelector, angle: ScalarLike, plane_origin: Sequence[float] = (0, 0, 0), plane_normal: Sequence[float] = (0, 0, 1)) -> Solid
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import draft_rsolid`

## Description

Draft planar, cylindrical or conical faces by a signed angle in degrees.

The neutral plane fixes the unchanged section: the selected faces lean
toward or away from it. Its origin and normal are in current
coordinate-system coordinates. Face selection is checked against the input
body and retained as graph inputs for strict replay. The input solid is
preserved, the output must be one valid solid, and a zero angle records an
unchanged result. Other surface families are explicitly rejected.

The operation is recorded as ``make_draft_rsolid``; the body and selected
faces are ordered inputs, and the angle, neutral plane and face selection
nodes are parameters, so model JSON replay is strict.

## Parameters

### solid

- **Description**: The body to draft.

### faces_to_draft

- **Description**: Faces of ``solid``, or a QL selector that picks them.

### angle

- **Description**: Draft angle in degrees, strictly between -90 and 90.

### plane_origin

- **Description**: A point of the neutral plane.

### plane_normal

- **Description**: Normal of the neutral plane; must be nonzero.

## Returns

The drafted solid.

## Raises

- **TypeError**: ``solid`` is not a Solid.
- **ValueError**: Empty selection, a selection that is not made of faces of ``solid``, an unsupported surface family, a zero plane normal, or a nonfinite or out-of-range angle.

## Examples

```python
import simplecadapi as scad
from simplecadapi import ql
body = scad.make_box_rsolid(10, 10, 10)
right = ql.faces().where(ql.prop("geom.normal.x", ">", 0.9)).exactly(1)
drafted = scad.draft_rsolid(body, right, angle=10)
```

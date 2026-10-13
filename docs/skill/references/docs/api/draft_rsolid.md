# draft_rsolid

```python
def draft_rsolid(
    solid: Solid,
    faces_to_draft: Sequence[Face] | ShapeSelector,
    angle: ScalarLike,
    plane_origin: Sequence[float] = (0, 0, 0),
    plane_normal: Sequence[float] = (0, 0, 1),
) -> Solid
```

*Source: operators/draft.py*

Import with `from simplecadapi import draft_rsolid`.

Apply a signed draft angle in degrees to selected planar, cylindrical, or
conical faces. The neutral plane retains its original section while the selected
faces lean toward or away from it. Its origin and normal use the current
coordinate system. The input solid is preserved, and the output must be one
valid solid. A zero angle records an unchanged result.

```python
import simplecadapi as scad
from simplecadapi import ql

body = scad.make_box_rsolid(10, 10, 10)
right = ql.faces().where(ql.prop("geom.normal.x", ">", 0.9)).exactly(1)
drafted = scad.draft_rsolid(body, right, angle=10)
```

Selections may be explicit faces from the body or a QL selector. Empty
selections, faces from another body, unsupported surface families, a zero plane
normal, and nonfinite parameters are rejected. The angle must be strictly
between -90 and 90 degrees. Kernel failures and invalid topology raise errors.

The operation `make_draft_rsolid` records the body and selected faces as ordered
inputs. Parameters preserve the angle, neutral plane, and face selection nodes
for strict model JSON replay.

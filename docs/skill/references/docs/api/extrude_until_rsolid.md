# extrude_until_rsolid

```python
def extrude_until_rsolid(
    profile: Face,
    target: Solid | Sequence[Solid],
    direction: Sequence[float] = (0, 0, 1),
    until: str = "NEXT",
) -> Solid
```

*Source: operators/limited_extrusion.py*

Import with `from simplecadapi import extrude_until_rsolid`.

Extrude a planar face until it reaches an actual boundary on one or more target
solids. Planar and curved termination surfaces are supported. The direction is
interpreted in the current coordinate system and normalized before construction.

| Mode | Direction | Termination |
| --- | --- | --- |
| `NEXT` | Forward | Nearest intersecting target surface |
| `LAST` | Forward | Farthest intersecting target surface |
| `PREVIOUS` | Reverse | Nearest intersecting target surface |
| `FIRST` | Reverse | Farthest intersecting target surface |

The implementation intersects a temporary prism with the target, obtains target
boundary faces from kernel history, sews the contact faces into surfaces, and
splits the prism on the selected surface. Bounding boxes only determine a
sufficient temporary prism length; they do not define the termination surface.
Side walls parallel to the direction do not join separate near and far limits.

```python
import simplecadapi as scad

profile = scad.make_rectangle_rface(2, 2)
ceiling = scad.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 5))
near = scad.extrude_until_rsolid(profile, ceiling, until="NEXT")  # Volume 20
far = scad.extrude_until_rsolid(profile, ceiling, until="LAST")   # Volume 28

sphere = scad.make_sphere_rsolid(5, center=(0, 0, 10))
curved = scad.extrude_until_rsolid(profile, sphere)
```

Targets must cover the profile at the requested contact. Missing contact,
insufficient coverage, an invalid mode, a zero/nonfinite direction, and invalid
kernel output raise errors. An empty target sequence is rejected. A successful
result is one valid solid; inputs are preserved.

The recorded operation is `make_extrude_until_rsolid`. Its ordered inputs are the
profile followed by every target solid. Parameters retain `direction`, `until`,
and `target_count`, so model JSON replay recomputes the boundary when a target
changes. No final BRep is embedded in the feature.

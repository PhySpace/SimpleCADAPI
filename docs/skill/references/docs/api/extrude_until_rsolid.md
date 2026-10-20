# extrude_until_rsolid

## API Definition

```python
def extrude_until_rsolid(profile: Face, target: Solid | Sequence[Solid], direction: Sequence[float] = (0, 0, 1), until: str = 'NEXT') -> Solid
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import extrude_until_rsolid`

## Description

Extrude a planar face until a target surface, including curved surfaces.

The direction is interpreted in the current coordinate system and
normalized before construction. ``until`` selects the termination:
``NEXT`` (forward, nearest intersecting target surface), ``LAST`` (forward,
farthest), ``PREVIOUS`` (reverse, nearest) and ``FIRST`` (reverse,
farthest). The temporary prism is intersected with the target, the target's
boundary faces are taken from kernel history and sewn into surfaces, and
the prism is split on the selected one. Bounding boxes only size the
temporary prism; they do not define the termination surface, and side
walls parallel to the direction do not join separate near and far limits.

Targets must cover the profile at the requested contact: an uncovered,
open or disconnected output is rejected, as are a missing contact, an
invalid mode, a zero or nonfinite direction and an empty target sequence.
Inputs are preserved. The operation is recorded as
``make_extrude_until_rsolid``; its ordered inputs are the profile followed
by every target solid and its parameters keep ``direction``, ``until`` and
``target_count``, so a changed target is recomputed on replay (no final
BRep is embedded).

## Parameters

### profile

- **Description**: The planar face to extrude.

### target

- **Description**: A solid, or a sequence of solids, that bounds the extrusion.

### direction

- **Description**: Extrusion direction in current coordinate-system coordinates.

### until

- **Description**: ``"NEXT"``, ``"LAST"``, ``"PREVIOUS"`` or ``"FIRST"``.

## Returns

One valid solid.

## Raises

- **TypeError**: ``profile`` is not a Face, or ``target`` is not a Solid or a sequence of Solid.
- **ValueError**: No target, no contact, insufficient coverage, a bad mode or direction, or an invalid kernel result.

## Examples

```python
import simplecadapi as scad
profile = scad.make_rectangle_rface(2, 2)
ceiling = scad.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 5))
near = scad.extrude_until_rsolid(profile, ceiling, until="NEXT")  # volume 20
far = scad.extrude_until_rsolid(profile, ceiling, until="LAST")  # volume 28
sphere = scad.make_sphere_rsolid(5, center=(0, 0, 10))
curved = scad.extrude_until_rsolid(profile, sphere)
```

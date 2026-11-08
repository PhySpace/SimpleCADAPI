# inset_face_rsolid

## API Definition

```python
def inset_face_rsolid(solid, face, distance)
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import inset_face_rsolid`

## Description

Imprint the loops of one planar face moved a distance inside it.

The outline of the face (and the outline of each of its holes) is offset in
the face's plane by ``distance`` towards the inside, and the offset loops are
imprinted on the solid: the face becomes an inner face and the ring around it
(a ring around each hole too).  The solid keeps its shape and volume; it only
has one face more, which the next operation can pull out, push in or open, so
steps, bosses and walls are built by insetting and pulling again.

The operation is recorded as ``make_inset_face_rsolid``; the body and the face
are ordered inputs and the distance is a parameter, so model JSON replay is
strict.  The split pieces are fragments of the face (element references and
tags follow them as a split) and carry the kernel roles ``inset.inner`` and
``inset.ring``, so ``scad.ref.face(..., role="inset.inner")`` names the inner
face whatever the face was.

## Parameters

### solid

- **Description**: The body whose face is inset.

### face

- **Description**: One planar face of ``solid``, or a QL selector that picks exactly one.

### distance

- **Description**: How far inside the face the loops run, in mm; positive.

## Returns

The same solid with the face split in its inner face and ring.

## Raises

- **TypeError**: ``solid`` is not a Solid.
- **ValueError**: Not exactly one face, a face of another solid, a curved face, a non-positive distance, or a distance at which nothing of the face is left inside the loops.

## Examples

```python
import simplecadapi as scad
ql = scad.ql
box = scad.make_box_rsolid(40, 30, 20)
top = ql.faces().where(ql.prop("geom.center.z", ">=", 19.9)).exactly(1)
inset = scad.inset_face_rsolid(box, top, 3)
inner = scad.ref.face("", "make_inset_face_rsolid", role="inset.inner").one(inset)
```

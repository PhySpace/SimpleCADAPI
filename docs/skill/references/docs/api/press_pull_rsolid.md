# press_pull_rsolid

## API Definition

```python
def press_pull_rsolid(solid, face, distance)
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import press_pull_rsolid`

## Description

Pull one planar face out along its normal, or press it in.

A positive ``distance`` pulls the face out: the prism of the face along its
outward normal is joined to the solid (a boss, a step).  A negative one presses
it in: the prism into the solid is cut (a pocket, a recess; through the solid it
cuts a hole).  Zero leaves the solid as it is.  One signed number covers both, so
a parameter can be tuned across zero without changing the code.

Pair it with ``inset_face_rsolid``: inset a face, then press or pull its inner
face, to build steps, bosses and walls without a sketch.

The operation is recorded as its steps: ``make_extrude_rsolid`` of the face,
then ``make_union_rsolid`` (pull) or ``make_cut_rsolid`` (press), so the new
faces carry the extrusion's roles (``extrusion.end`` is the moved face,
``extrusion.side`` its walls) and element references follow them.

## Parameters

### solid

- **Description**: The body whose face is pressed or pulled.

### face

- **Description**: One planar face of ``solid``, or a QL selector that picks exactly one.

### distance

- **Description**: How far, in mm, along the face's outward normal: positive pulls, negative presses.

## Returns

The solid with the face pulled out or pressed in.

## Raises

- **TypeError**: ``solid`` is not a Solid.
- **ValueError**: Not exactly one face, a face of another solid, a curved face, a non-finite distance, or a press that removes the whole solid.

## Examples

```python
import simplecadapi as scad
ql = scad.ql
box = scad.make_box_rsolid(40, 30, 20)
top = ql.faces().where(ql.prop("geom.center.z", ">=", 19.9)).exactly(1)
stepped = scad.inset_face_rsolid(box, top, 3)
inner = scad.ref.faces(scad.ref.face("", "make_inset_face_rsolid", role="inset.inner"))
boss = scad.press_pull_rsolid(stepped, inner, 10)
pocket = scad.press_pull_rsolid(stepped, inner, -4)
```

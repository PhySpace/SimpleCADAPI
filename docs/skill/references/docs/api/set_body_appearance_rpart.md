# set_body_appearance_rpart

## API Definition

```python
def set_body_appearance_rpart(part, body_id='body', *, color=None, opacity=None, name=None, reset=False)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import set_body_appearance_rpart`

## Description

Set the display colour, opacity and display name of the body of a Part.

A Part is a value: the result is a new Part, the input is unchanged.  The colour is an
appearance only.  A body without a colour shows its Part's material colour
(``Material.color``), and without either it shows the default grey: the body colour
overrides the material colour for display (the live preview, the package scene, the STEP
surface colour of that solid).  Mass, density and geometry never read it.

``lid = scad.set_body_appearance_rpart(lid, color=(0.9, 0.3, 0.2), name="Lid")``
paints the part's body (a Part holds one solid, whose body id is ``"body"``). Recorded and
replayed like ``assign_material_rpart``. To name a face or an edge for people, tag it
(``scad.apply_tag_rselection`` / ``ql.tag``): a tag is the name.

## Parameters

### part

- **Description**: The Part.

### body_id

- **Description**: The body to change: the Part's one body, ``"body"`` (the default).

### color

- **Description**: Display colour as RGB floats in [0.0, 1.0], e.g. ``(0.8, 0.2, 0.2)``; linear RGB, as ``Material.color``, OpenCASCADE (so STEP) and three.js read it (the editor's colour picker converts its sRGB ``#rrggbb``). ``None`` keeps the body's colour.

### opacity

- **Description**: Display opacity in [0.0, 1.0] (1 is opaque). ``None`` keeps it. STEP export writes the colour, not the opacity.

### name

- **Description**: Display name of the body (the editor's bodies list, the scene node, the STEP solid). ``None`` keeps it. The ``body_id`` never changes.

### reset

- **Description**: Clear the colour, opacity and name first, so the body shows the material colour, opaque, under its id; then apply what is given.

## Returns

Part: The Part with the body's appearance changed; ``part.get_body(body_id).color``,
``.opacity`` and ``.name`` read it back.

## Raises

- **SimpleCADError**: The value is not a Part, the part has no such body, the colour is not three numbers in [0, 1], the opacity is outside [0, 1], or the name is empty.

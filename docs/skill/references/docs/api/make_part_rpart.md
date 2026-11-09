# make_part_rpart

## API Definition

```python
def make_part_rpart(part_id, body, name=None)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import make_part_rpart`

## Description

Wrap one Solid as a semantic Part. A Part holds exactly one solid.

``scad.make_part_rpart(part_id=scad.notebook_id(), body=bracket)``. Several solids
are not one Part: make one Part per solid and put them in an Assembly (identity
placements when they only sit together), or union / cut them into one solid first.
Solids that sit side by side while a model is built (a tool next to the body it will
cut) are ordinary notebook values, not a Part.

## Parameters

### part_id

- **Description**: Stable identifier of the part (``scad.notebook_id()`` in a notebook).

### body

- **Description**: The Solid of the Part. A ``Body`` (a solid with a display name, colour and opacity) and a list of exactly one piece of a split cut are also taken. Several solids, or a list of several pieces, are refused.

### name

- **Description**: Optional display name.

## Returns

Part: The new Part. ``part.body`` is its Solid; ``part.bodies`` is that body as a
one-element tuple.

## Raises

- **SimpleCADError**: The body is not a Solid, more than one solid was given (a ValueError that says to make one Part per solid in an Assembly, or to union / cut them to one solid), or the part_id is already used.

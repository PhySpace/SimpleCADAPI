# Part

## Class Definition

```python
class Part(part_id, body, name=None, material=None, connectors=())
```

*Source: product/part.py*

## Import Surface

- top-level: `from simplecadapi import Part`

## Description

Product item holding exactly one Solid (``body``).

A Part is the unit an Assembly places, mates and gives connectors to, so it is one
solid. ``part.body`` is its Solid; ``part.bodies`` is that body as a one-element tuple
of ``Body`` values (a ``Body`` carries the display name, colour and opacity,
``set_body_appearance_rpart``). ``body`` also takes a ``Body``. Several solids are
refused (ValueError): make one Part per solid in an Assembly, or union / cut them
into one solid first.

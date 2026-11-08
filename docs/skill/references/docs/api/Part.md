# Part

## Class Definition

```python
class Part(part_id, body=None, name=None, material=None, connectors=(), bodies=None)
```

*Source: product/part.py*

## Import Surface

- top-level: `from simplecadapi import Part`

## Description

Product item holding one Solid (``body``) or several named bodies (``bodies``).

A one-body Part is the common case: ``part.body`` is its Solid. A multi-body
Part keeps several solids apart inside one product item (a case and its lid
modelled side by side, the pieces of a split cut): ``part.bodies`` lists them
as ``Body`` values in order, ``part.get_body(body_id)`` finds one, and
``part.body`` raises ``TypeError``. Bodies of one Part are never placed
relative to each other and carry no joints; use an Assembly for that.

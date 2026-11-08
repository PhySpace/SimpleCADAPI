# Body

## Class Definition

```python
class Body(body_id, solid, name=None, color=None, opacity=None)
```

*Source: product/part.py*

## Import Surface

- top-level: `from simplecadapi import Body`

## Description

One named solid of a Part.

``Body(body_id, solid, name=None, color=None, opacity=None)``: ``body_id`` is an
identifier unique within the part, ``solid`` the body's Solid, ``name`` an optional
display name, ``color`` an optional display colour (RGB floats in [0, 1]) and
``opacity`` an optional display opacity in [0, 1]. A one-body Part has one Body with
the id ``"body"``. The colour overrides the Part's material colour for display only;
set it on an existing Part with ``set_body_appearance_rpart``.

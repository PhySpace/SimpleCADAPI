# Body

## Class Definition

```python
class Body(body_id, solid, name=None, color=None, opacity=None)
```

*Source: product/part.py*

## Import Surface

- top-level: `from simplecadapi import Body`

## Description

The solid of a Part, with its display name, colour and opacity.

``Body(body_id, solid, name=None, color=None, opacity=None)``: ``body_id`` is an
identifier (``"body"`` for the body of a Part), ``solid`` the body's Solid, ``name`` an optional
display name, ``color`` an optional display colour (RGB floats in [0, 1]) and
``opacity`` an optional display opacity in [0, 1]. A one-body Part has one Body with
the id ``"body"``. The colour overrides the Part's material colour for display only;
set it on an existing Part with ``set_body_appearance_rpart``.

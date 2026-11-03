# Body

## Class Definition

```python
class Body(body_id, solid, name=None)
```

*Source: product/part.py*

## Import Surface

- top-level: `from simplecadapi import Body`

## Description

One named solid of a Part.

``Body(body_id, solid, name=None)``: ``body_id`` is an identifier unique within
the part, ``solid`` the body's Solid, ``name`` an optional display name. A
one-body Part has one Body with the id ``"body"``.

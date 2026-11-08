# ElementRefError

## Class Definition

```python
class ElementRefError(resolved: Resolution)
```

*Source: topology/element_ref.py*

## Import Surface

- top-level: `from simplecadapi import ElementRefError`

## Description

A reference that does not name exactly one entity: ``split`` (choose a piece) or ``lost``.

``status`` and ``candidates`` say which and what to choose from; ``resolved`` is the whole :class:`Resolution`.

# ElementRef

## Class Definition

```python
class ElementRef(kind: str, feature: str = '', op: str = '', role: Optional[str] = None, ordinal: int = 0, topo: Optional[str] = None, between: Optional[Tuple[Union[str, 'ElementRef'], Union[str, 'ElementRef']]] = None, occurrence: int = 0, slot: int = 0, piece: Optional[int] = None, follow: str = 'identity', guard: Optional[Guard] = None, digest: Optional[str] = None, naming: int = 1)
```

*Source: ref.py*

## Import Surface

- top-level: `from simplecadapi import ElementRef`

## Description

A stable reference to one face, edge or vertex; ``repr()`` is the code that makes it.

Fields: ``kind``; ``feature`` and ``op`` (where the entity was born); then exactly one of ``role`` (its kernel
role, with ``ordinal`` saying which of the entities with that role), ``topo`` (its position in that output, for an
entity without a role; give a ``guard`` with it) or, for an edge, ``between`` (the two faces it lies between: role
names of faces of the same ``op``, or face references); ``occurrence`` (which of the feature's ``op`` nodes
upstream of the shape); ``slot`` (the output of that node); ``piece`` (the chosen piece when the entity has been
split); ``follow`` (``"identity"``, or ``"derived"`` to also follow into what it generated: an edge into its fillet
patch); ``guard``; ``digest`` (the parameters of the node, only when two nodes share its name); ``naming`` (the
naming version).

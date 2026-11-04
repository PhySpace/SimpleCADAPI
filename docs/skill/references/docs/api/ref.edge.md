# ref.edge

## API Definition

```python
def ref.edge(feature: Optional[str] = None, op: Optional[str] = None, *, role: Optional[str] = None, ordinal: int = 0, topo: Optional[str] = None, between: Optional[Tuple[Union[str, ElementRef], Union[str, ElementRef]]] = None, occurrence: int = 0, slot: int = 0, piece: Optional[int] = None, follow: Follow = 'identity', guard: Optional[Guard] = None, digest: Optional[str] = None, naming: int = 1) -> ElementRef
```

*Source: ref.py*

## Import Surface

- stable references: `import simplecadapi as scad` then `scad.ref.edge(...)`

## Description

A reference to an edge: born in *feature* by *op*, or lying ``between`` two faces.

An edge is best named by the two faces it lies between: the faces' history is recorded by every operation, so the
edge is found again after booleans, blends and copies, and the name reads as what it is.  ``between`` holds two
role names of faces made by *op* in *feature* (``("box.top", "box.front")``), or two face references (then
*feature* and *op* may be left out).  The other arguments are :func:`face`'s (``guard`` size = length).

## Examples

```python
>>> rim = scad.ref.edge("base", "make_box_rsolid", between=("box.top", "box.front"))
>>> lip = scad.ref.edge(between=(scad.ref.face("base", "make_box_rsolid", role="box.top"),
...                              scad.ref.face("bore", "make_cylinder_rsolid", role="cylinder.side")))
>>> rounded = scad.fillet_rsolid(part, scad.ref.edges(rim, lip), 1.0)
```

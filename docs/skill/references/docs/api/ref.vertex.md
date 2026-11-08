# ref.vertex

## API Definition

```python
def ref.vertex(feature: str, op: str, *, role: Optional[str] = None, ordinal: int = 0, topo: Optional[str] = None, occurrence: int = 0, slot: int = 0, piece: Optional[int] = None, guard: Optional[Guard] = None, digest: Optional[str] = None, naming: int = 1) -> ElementRef
```

*Source: ref.py*

## Import Surface

- stable references: `import simplecadapi as scad` then `scad.ref.vertex(...)`

## Description

A reference to a vertex born in *feature* by *op* (the arguments are :func:`face`'s).

# DimDecl

## Class Definition

```python
class DimDecl(kind: str, view: str, semantic: str, caption: str, value: float | None = None, of: object = None, between: tuple | None = None, axis: str | None = None, extent: str | None = None, tol: tuple | None = None, fit: str = '', count: int = 0, p1: tuple | None = None, p2: tuple | None = None, center: tuple | None = None, radius: float | None = None, at: float | None = None, datum: str | None = None, side: str | None = None, row: int = 0, out: float = 8.0, dec: int | None = None, prefix: str = '', covers: list = field(default_factory=list), name: str = '')
```

*Source: dxf_engine/model.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import DimDecl`

## Description

One dimension declaration. A position dimension (kind=position) must reference a declared datum in `datum`.

Say what is measured with exactly one of: `of` (diameter/radius: a circular edge, a cylinder face, or a selector of
one), `between` (linear: two references), `extent` (linear: "x" or "y", the overall size of the view), or the typed
forms `p1`/`p2` and `center`/`radius`. The number on the sheet is always the one measured from that geometry;
`value`, when given, is what you expect it to be and a difference is reported (DIM_VALUE_MISMATCH).

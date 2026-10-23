# DimDecl

## Class Definition

```python
class DimDecl(kind: str, view: str, semantic: str, caption: str, value: float | None = None, p1: tuple | None = None, p2: tuple | None = None, center: tuple | None = None, radius: float | None = None, at: float | None = None, datum: str | None = None, side: str | None = None, row: int = 0, out: float = 8.0, dec: int = 0, prefix: str = '', covers: list = field(default_factory=list), name: str = '')
```

*Source: dxf_engine/model.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import DimDecl`

## Description

One dimension declaration. A position dimension (kind=position) must reference a declared datum in `datum`.

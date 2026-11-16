# RoughDecl

## Class Definition

```python
class RoughDecl(view: str, on: object, text: str = 'Ra 3.2', name: str = '')
```

*Source: dxf_engine/model.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import RoughDecl`

## Description

Surface-texture symbol (GB/T 131, material removal required) standing on a surface line of a view.

`on` is a reference to the surface as the view shows it (a plane face seen edge-on, a straight edge) or a view-local
point; `text` is what stands above the symbol ("Ra 3.2").

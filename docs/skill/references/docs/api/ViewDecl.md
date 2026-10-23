# ViewDecl

## Class Definition

```python
class ViewDecl(name: str, shape: object, n: tuple, xd: tuple, align: dict = field(default_factory=dict), anchor: tuple | None = None)
```

*Source: dxf_engine/model.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import ViewDecl`

## Description

An HLR projected view. n = viewing direction, xd = screen-right direction in the projection plane; align defines the layout constraint.

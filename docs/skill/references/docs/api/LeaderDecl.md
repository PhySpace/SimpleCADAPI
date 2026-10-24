# LeaderDecl

## Class Definition

```python
class LeaderDecl(view: str, anchor: tuple, lines: list, off: tuple = (30.0, -18.0), alt_offs: list = field(default_factory=list), dx_dir: float = 1.0, name: str = '')
```

*Source: dxf_engine/model.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import LeaderDecl`

## Description

Leader declaration: a polyline from anchor to the note text.

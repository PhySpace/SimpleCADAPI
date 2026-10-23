# Resolved

## Class Definition

```python
class Resolved(kind: str, name: str, view: str, requested: str, resolved: str, adjust: list = field(default_factory=list), draw: dict = field(default_factory=dict), rule: str = '')
```

*Source: dxf_engine/planner.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import Resolved`

## Description

The solved result of one annotation element on the sheet: requested (declared value) → resolved (actual position) +
adjust (record of the minimum adjustments) + draw (precomputed geometry for rendering) + rules (the rules that fired).

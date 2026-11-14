# Issue

## Class Definition

```python
class Issue(code: str, severity: str, element: str, message: str, hint: str = '', view: str = '', data: dict = field(default_factory=dict))
```

*Source: dxf_engine/checks.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import Issue`

## Description

One finding. severity: error (the sheet is wrong) | warning (it reads badly or something is missing) | info.

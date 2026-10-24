# Var

## Class Definition

```python
class Var(name, default, comment=None, expr_id='', tolerance=None, unit=None, tolerance_unit=None, *, ui=None, control=None, min=None, max=None, step=None, label=None, group=None)
```

*Source: params/expr.py*

## Import Surface

- top-level: `from simplecadapi import Var`

## Description

Named scalar parameter with optional physical-unit and tolerance intent.

``default`` and ``tolerance`` remain in their declared units. Evaluation,
geometry parameters, and tolerance propagation convert them to SimpleCAD's
canonical CAD units: millimeters for length and degrees for angle.

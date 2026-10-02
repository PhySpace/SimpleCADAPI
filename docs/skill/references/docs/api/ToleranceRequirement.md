# ToleranceRequirement

## Class Definition

```python
class ToleranceRequirement(requirement_id: str, target_expr_id: str, tolerance: DimensionTolerance, method: ToleranceMethod = 'worst_case', name: str = '', tolerance_unit: Unit | None = None, target_dimension: Dimension | None = None, target: ScalarExpr | None = field(default=None, compare=False, repr=False))
```

*Source: params/tolerance.py*

## Import Surface

- top-level: `from simplecadapi import ToleranceRequirement`

## Description

Permitted result deviations for one derived dimension.

# DimensionTolerance

## Class Definition

```python
class DimensionTolerance(lower_deviation, upper_deviation)
```

*Source: params/expr.py*

## Import Surface

- top-level: `from simplecadapi import DimensionTolerance`

## Description

Permitted lower and upper deviations from a nominal dimension.

Deviations are signed: the lower deviation must be less than or equal to
zero and the upper deviation must be greater than or equal to zero.

# BSplineFitResult

## Class Definition

```python
class BSplineFitResult()
```

*Source: math.py*

## Import Surface

- top-level: `from simplecadapi import BSplineFitResult`

## Description

Result from fitting a cubic B-spline to sampled curve points.

The result stores a complete, normalized B-spline definition suitable for
passing into the exact B-spline edge/wire APIs: cubic degree, control
points, and a full clamped knot vector.

# fit_cubic_bspline_control_points

## API Definition

```python
def fit_cubic_bspline_control_points(sample_points, *, tolerance=0.001, max_control_points=None, fairing=1e-06, duplicate_tolerance=1e-12, knot_tolerance=1e-09, raise_on_failure=True)
```

*Source: math.py*

## Import Surface

- top-level: `from simplecadapi import fit_cubic_bspline_control_points`

## Description

Fit a minimal cubic B-spline control polygon to sampled curve points.

Uses chord-length parameterization, cubic clamped B-spline least squares,
second-difference fairing regularization, and adaptive simple knot insertion
until the maximum sample error is within `tolerance`. Only simple interior
knots are inserted, so a cubic result remains C2-continuous at every interior
knot.

## Parameters

### sample_points

- **Description**: Ordered 2D or 3D points sampled along the intended curve. Consecutive duplicate points within `duplicate_tolerance` are ignored.

### tolerance

- **Description**: Maximum allowed Euclidean fitting error at the input samples.

### max_control_points

- **Description**: Upper bound for fitted control points. Defaults to the cleaned sample count, with a cubic minimum of four controls.

### fairing

- **Description**: Non-negative second-difference regularization weight. Larger values prefer smoother control polygons while still respecting the error tolerance when possible.

### duplicate_tolerance

- **Description**: Distance threshold for removing consecutive duplicate sample points before chord-length parameterization.

### knot_tolerance

- **Description**: Normalized parameter spacing threshold used to avoid duplicate or near-boundary interior knots.

### raise_on_failure

- **Description**: Raise `ValueError` when the tolerance cannot be reached within `max_control_points`. If false, return the best non-converged result instead.

## Returns

`BSplineFitResult` containing cubic degree, control points, a full clamped
knot vector, knot multiplicities, sample parameters, and fitting error.

## Raises

- **ValueError**: If inputs are invalid, or if the tolerance cannot be met and `raise_on_failure=True`.

## Examples

### Example 1
```python
```python
from simplecadapi.math import fit_cubic_bspline_control_points
```

### Example 2
```python
samples = [(0.0, 0.0, 0.0), (1.0, 0.4, 0.0), (2.0, 0.0, 0.0)]
fit = fit_cubic_bspline_control_points(samples, tolerance=0.01)
print(fit.control_points)
print(fit.knots, fit.multiplicities)
```
```

# Dimension Tolerance Chains

SimpleCADAPI can attach units and manufacturing tolerances to declared dimension
variables, infer dimensions through the expression DAG, propagate source
variation, and verify derived dimensions against design requirements.

This feature is separate from sketch-solver residual tolerances, boolean fuzzy tolerances, mesh resolution, and geometric fitting tolerances. A dimension tolerance describes permitted manufacturing variation around a nominal design value; it never changes a CAD operation's numerical robustness settings.

## Declare Source Dimensions

Every variable that participates in a tolerance chain must declare a tolerance:

```python
import simplecadapi as scad

width = scad.var("width", 10.0, unit="mm", tolerance=0.1)
shaft = scad.var(
    "shaft",
    0.315,
    unit="in",
    tolerance=(-0.05, 0.0),
    tolerance_unit="mm",
)
```

A scalar tolerance is symmetric. `tolerance=0.1` means `-0.1/+0.1`
around the nominal value. A two-value sequence contains signed
`(lower_deviation, upper_deviation)` values. The lower deviation must be at most
zero, the upper deviation must be at least zero, and all values must be finite.

`tolerance_unit` defaults to `unit`. It may differ from the nominal unit, but the
dimensions must match. Geometry and tolerance propagation use canonical
millimeters for length and degrees for angle. Declaration-space values remain on
the `Var` for display and serialization.

The same values can be represented explicitly:

```python
tolerance = scad.DimensionTolerance(
    lower_deviation=-0.05,
    upper_deviation=0.0,
)
shaft = scad.var("shaft", 8.0, unit="mm", tolerance=tolerance)
```

Tolerance identity follows `expr_id`, not the human-readable variable name. Two variables with the same name remain separate tolerance sources.

## Propagate A Chain

```python
housing = scad.var("housing", 100.0, unit="mm", tolerance=0.15)
bearing = scad.var(
    "bearing", 2.0, unit="cm", tolerance=(-0.04, 0.05), tolerance_unit="mm"
)
spacer = scad.var("spacer", 79.4, unit="mm", tolerance=0.05)
clearance = housing - bearing - spacer

result = scad.analyze_tolerance(clearance, method="worst_case")

print(result.nominal)
print(result.lower_bound, result.upper_bound)
print(result.lower_deviation, result.upper_deviation)
for contribution in result.contributions:
    print(contribution.variable_name, contribution.lower_deviation, contribution.upper_deviation)
```

`ToleranceAnalysis` contains absolute bounds, deviations from nominal, inferred
`dimension`, canonical `unit`, and one contribution record per source variable.
Each contribution reports its nominal and source tolerance in canonical units.

The unit system validates the expression before propagation. This permits
physically meaningful nonlinear chains such as:

```python
width = scad.var("width", 30.0, unit="mm", tolerance=0.1)
height = scad.var("height", 40.0, unit="mm", tolerance=0.2)
diagonal = scad.sqrt(width**2 + height**2)

analysis = scad.analyze_tolerance(diagonal)
assert analysis.dimension == scad.LENGTH
assert analysis.unit == scad.MM
```

Area and volume expressions can be inferred and analyzed. Persisted manufacturing
requirements currently accept final Length and Angle results only.

## Propagation Methods

### Worst Case

`method="worst_case"` is the default and the safety-oriented validation method.

- Affine chains preserve variable identity and combine coefficients exactly. Repeated use is not treated as an independent source, so `x - x` has zero propagated tolerance.
- Nonlinear chains use conservative interval propagation.
- Multiplication and division consider all endpoint sign combinations.
- Integer, negative, fractional, and varying powers validate their mathematical domains.
- `sin` and `cos` include interior extrema; `tan` rejects intervals crossing a discontinuity.
- `sqrt`, `asin`, and `acos` validate the entire input interval.
- Division rejects denominator intervals containing zero.
- `atan2` rejects tolerance regions containing its undefined origin.

Conservative interval propagation can intentionally overestimate a strongly correlated nonlinear expression. It must not underestimate a safety bound.

### RSS

`method="rss"` uses first-order analytic sensitivities and root-sum-square combination:

```python
result = scad.analyze_tolerance(clearance, method="rss")
```

Distinct variables are assumed independent. Repeated occurrences of the same variable are merged before RSS, so `x - x` still has zero sensitivity and `x + x` has twice the sensitivity of `x`.

RSS validates the full declared tolerance interval before calculating the first-order estimate. A nominal point cannot hide a division singularity, trigonometric discontinuity, or invalid function domain elsewhere in the source range.

Covariance matrices, correlation groups, probability distributions, and Monte Carlo analysis are not represented by the current API. Use `worst_case` when the independence assumption is unavailable or when a guaranteed envelope is required.

## Check One Requirement

`check_tolerance()` returns a result without raising when the derived tolerance exceeds the permitted deviations:

```python
check = scad.check_tolerance(
    clearance,
    tolerance=(-0.25, 0.24),
    method="worst_case",
    name="axial_clearance",
    tolerance_unit="mm",
)

print(check.passed)
print(check.lower_margin, check.upper_margin)
```

A non-negative lower and upper margin means the requirement passes, subject to a
small floating-point comparison epsilon. Requirement deviations are converted
from `tolerance_unit` to the target's canonical unit before comparison.

## Session Requirements And Automatic Validation

Use `GraphSession.require_tolerance()` for design requirements that must travel with the model:

```python
with scad.GraphSession() as session:
    body = scad.make_box_rsolid(housing, 10.0, 10.0)
    session.require_tolerance(
        clearance,
        (-0.25, 0.24),
        method="worst_case",
        name="axial_clearance",
        requirement_id="req.axial_clearance",
        tolerance_unit="mm",
    )

report = session.validate_tolerances(raise_on_failure=True)
model_json = scad.export_model_json(session)
```

Automatic validation occurs when:

1. `validate_tolerances(raise_on_failure=True)` is called.
2. A session or model JSON payload is exported.
3. A model JSON payload is imported or replayed.

A failed requirement raises `ToleranceValidationError` at the tolerance layer. Model import, export, and replay expose it through the existing structured `SimpleCADError` harness where applicable.

Declaring a requirement validates that the chain is complete and mathematically defined, but it still records a failing requirement so callers can inspect its margins. Export and replay are the enforcement boundaries.

## Serialization

Variable tolerances are stored on variable nodes in `expression_graph`:

```json
{
  "expr_id": "var_width",
  "kind": "var",
  "name": "width",
  "default": 1.0,
  "unit": "in",
  "tolerance": {
    "lower_deviation": -0.1,
    "upper_deviation": 0.1
  },
  "tolerance_unit": "mm"
}
```

Design requirements and their latest validation evidence are stored in the top-level `tolerance_graph`:

```json
{
  "requirements": [
    {
      "requirement_id": "req.axial_clearance",
      "target_expr_id": "expr_clearance",
      "tolerance": {
        "lower_deviation": -0.25,
        "upper_deviation": 0.24
      },
      "method": "worst_case",
      "name": "axial_clearance",
      "tolerance_unit": "mm",
      "target_dimension": {
        "length": 1,
        "angle": 0
      }
    }
  ],
  "validation": {
    "passed": true,
    "checks": []
  }
}
```

Validation evidence is recomputed during import; serialized evidence is not
trusted as an authority. The target expression dimension is inferred again and
must match `target_dimension`; `tolerance_unit` must have the same dimension.
Payloads created before units or `tolerance_graph` existed remain valid as legacy
unitless expressions and import with an empty tolerance graph when it is absent.

Nominal geometry replay still uses the numeric snapshots in operation-node `params`. Tolerance validation does not sample or regenerate worst-case geometry.

## Failure Conditions

Tolerance analysis fails explicitly for:

- a source variable without a declared tolerance
- non-finite nominal values or deviations
- malformed signed lower/upper deviations
- unknown, malformed, non-finite, incompatible, overflowing, or underflowing units
- addition/subtraction or `atan2` with incompatible dimensions
- invalid powers, square roots, or trigonometric dimensions
- mixing unit-declared and legacy variables in one expression
- a requirement unit or persisted target dimension that disagrees with the target
- an Area, Volume, Dimensionless, or compound-dimension requirement target
- duplicate requirement IDs
- unknown or dangling expression references
- malformed, cyclic, duplicate-ID, or unsupported expression nodes
- an undefined expression anywhere in the declared tolerance interval
- an RSS derivative at a non-differentiable nominal point
- an unsupported propagation method

See [Physical Units And Dimension Inference](physical-units.md) for the complete
unit registry, dimension algebra, custom-unit payload, and legacy behavior.

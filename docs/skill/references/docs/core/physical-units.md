# Physical Units And Dimension Inference

SimpleCADAPI attaches physical meaning at `Var` declarations and infers the
dimension of every derived scalar expression. This catches invalid formulas before
they reach geometry, tolerance analysis, model export, or replay.

## Canonical CAD Units

Declaration values are preserved on each `Var`, but evaluation converts them to a
single CAD coordinate system:

| Dimension | Canonical unit |
| --- | --- |
| Dimensionless | `1` |
| Length | `mm` |
| Area | `mm^2` |
| Volume | `mm^3` |
| Angle | `deg` |

Degrees are canonical because existing SimpleCAD rotation and angular APIs use
degrees. Trigonometric evaluation converts to radians internally and converts
inverse-trigonometric results back to degrees.

```python
import math
import simplecadapi as scad

width = scad.var("width", 1.0, unit="in")
angle = scad.var("angle", math.pi / 2, unit="rad")

assert width.default == 1.0
assert width.evaluate() == 25.4
assert angle.evaluate() == 90.0
assert math.isclose(scad.sin(angle).evaluate(), 1.0)
```

Bindings use the variable's declaration unit. `width.evaluate({"width": 2.0})`
therefore returns `50.8` millimeters for an inch-declared variable.

## Declaring Units And Tolerances

```python
width = scad.var(
    "width",
    1.0,
    unit="in",
    tolerance=(-0.1, 0.2),
    tolerance_unit="mm",
)
```

- `default` is in `unit`.
- `tolerance` is in `tolerance_unit`.
- `tolerance_unit` defaults to `unit` when a tolerance is present.
- Nominal and tolerance units may differ, but their dimensions must match.
- A `tolerance_unit` requires both `unit` and `tolerance`.
- Values must be finite and representable after canonical conversion.

`width.default` and `width.tolerance` preserve declaration-space values.
`width.canonical_default` and `width.canonical_tolerance` expose values used by
geometry and tolerance propagation.

## Built-In Units

| Dimension | Symbols |
| --- | --- |
| Dimensionless | `1`, `%` |
| Length | `mm`, `cm`, `m`, `in`, `ft` |
| Area | `mm^2`, `cm^2`, `m^2`, `in^2`, `ft^2` |
| Volume | `mm^3`, `cm^3`, `m^3`, `in^3`, `ft^3` |
| Angle | `deg`, `rad` |

Common singular/plural names are accepted by `get_unit()`, including
`millimeters`, `inches`, `feet`, `degrees`, `radians`, `square feet`, and
`cubic inches`. `ml` aliases `cm^3`.

Use constants such as `MM`, `INCH`, `DEGREE`, `RADIAN`, `LENGTH`, and `ANGLE`, or
resolve strings:

```python
assert scad.get_unit("inch") == scad.INCH
assert scad.convert_value(1.0, "in", "mm") == 25.4
assert math.isclose(scad.convert_value(180.0, "deg", "rad"), math.pi)
```

Incompatible conversion raises `UnitValidationError`.

## Dimension Algebra

`Dimension` stores integer exponents for length and angle. Named dimensions are:

- `DIMENSIONLESS = Dimension()`
- `LENGTH = Dimension(length=1)`
- `AREA = Dimension(length=2)`
- `VOLUME = Dimension(length=3)`
- `ANGLE = Dimension(angle=1)`

`infer_dimension(expression)` applies these rules:

| Operation | Rule |
| --- | --- |
| `a + b`, `a - b` | dimensions must match |
| `a * b` | add dimension exponents |
| `a / b` | subtract dimension exponents |
| `a ** n` | multiply exponents by constant integer `n` |
| `sqrt(a)` or `a ** 0.5` | every exponent must be even |
| unary `-a`, `abs(a)` | preserve dimension |
| `sin`, `cos`, `tan` | input must be Angle; result is Dimensionless |
| `asin`, `acos`, `atan` | input must be Dimensionless; result is Angle |
| `atan2(y, x)` | inputs must have the same dimension; result is Angle |

Arbitrary and varying powers are permitted for dimensionless bases. A dimensioned
base requires a constant integer exponent, except `0.5` is accepted when all base
exponents are even.

```python
width = scad.var("width", 30.0, unit="mm")
height = scad.var("height", 40.0, unit="mm")

area = width * height
diagonal = scad.sqrt(width**2 + height**2)

assert scad.infer_dimension(area) == scad.AREA
assert scad.infer_dimension(diagonal) == scad.LENGTH
assert diagonal.evaluate() == 50.0
```

## Numeric Constants

Numeric literals are dimensionless coefficients in multiplication and division.
For addition and subtraction, a literal adopts the other operand's dimension as a
contextual offset:

```python
length = scad.var("length", 10.0, unit="mm")
assert scad.infer_dimension(length * 2.0) == scad.LENGTH
assert scad.infer_dimension(length + 2.0) == scad.LENGTH
```

The literal is already expressed in the canonical result unit. `length + 2.0`
therefore means two millimeters, not two units of `length.unit`. Prefer explicit
variables when declaration-unit intent must be retained.

## Legacy Unitless Expressions

Variables without `unit` retain the previous behavior:

- `infer_dimension()` returns `None`.
- Trigonometric inputs and results use radians.
- Existing arbitrary expression and tolerance behavior remains available.
- A legacy variable cannot be mixed with a unit-declared variable in one
  expression because no safe physical meaning can be inferred.

Pure numeric constant expressions infer `Dimensionless`.

## Custom Units

Custom linear-scale units use the same canonical system:

```python
thou = scad.Unit("thou", scad.LENGTH, 0.0254)
width = scad.var("width", 1000.0, unit=thou)
assert width.evaluate() == 25.4
```

Built-in units serialize as symbols. Custom units serialize a definition:

```json
{
  "symbol": "thou",
  "dimension": {"length": 1, "angle": 0},
  "scale_to_canonical": 0.0254
}
```

Units are scale-only. Offset units such as Celsius/Fahrenheit are not represented.

## Validation Boundaries

Unit and dimension validation runs when:

1. A `Var`, `Dimension`, or `Unit` is created.
2. An expression is directly evaluated.
3. An expression is registered or imported through `ExpressionGraph`.
4. A tolerance is analyzed or a requirement is declared.
5. Session/model JSON is imported, exported, or replayed.

Malformed units, cyclic graphs, duplicate expression IDs, mixed legacy/typed
variables, incompatible dimensions, invalid roots, and invalid trigonometric inputs
are rejected before graph mutation or geometry replay.

## Manufacturing Requirement Scope

Area, volume, inverse length, and other compound dimensions can be inferred and
analyzed. Manufacturing requirements created by `check_tolerance()` or
`GraphSession.require_tolerance()` currently accept final `Length` and `Angle`
results only. This prevents an area or volume variation from being presented as a
linear dimension requirement without explicit engineering semantics.

See [Dimension Tolerance Chains](dimension-tolerance-chains.md) for propagation,
RSS assumptions, enforcement boundaries, and serialized requirement fields.

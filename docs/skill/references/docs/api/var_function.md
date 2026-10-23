# var

## API Definition

```python
def var(name, default, comment=None, tolerance=None, *, unit=None, tolerance_unit=None, ui=None, control=None, min=None, max=None, step=None, label=None, group=None)
```

*Source: params/expr.py*

## Import Surface

- top-level: `from simplecadapi import var`

## Description

Create a physical or legacy scalar variable.

``tolerance=0.1`` declares a symmetric ``+/-0.1`` tolerance. Use a
``(lower_deviation, upper_deviation)`` pair for an asymmetric tolerance.
``tolerance_unit`` defaults to ``unit`` when a nominal unit is declared.
Values are converted to canonical CAD units only when evaluated, so the
declaration and serialized expression node preserve the user's units.

Variables without ``unit`` retain legacy unitless behavior. A unit-aware
expression cannot mix declared-unit variables with legacy variables.

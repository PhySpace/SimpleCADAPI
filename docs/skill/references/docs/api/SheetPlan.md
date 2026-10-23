# SheetPlan

## Class Definition

```python
class SheetPlan(decl: SheetDecl)
```

*Source: dxf_engine/planner.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import SheetPlan`

## Description

The dimensioning-plan solver: SheetDecl → solve() → resolved/accepted/report() → render().

Solving: view layout (first-angle projection, align) → datum placement → linear dimensions
(ordered by view/side/row, large outside, small inside) → diameter/radius dimensions → leaders → parameter-coverage check.
Every conflict follows "minimum adjustment": candidate positions are shifted first and recorded in Resolved.adjust;
when nothing fits it is recorded as an R1 warning, never silently dropped.

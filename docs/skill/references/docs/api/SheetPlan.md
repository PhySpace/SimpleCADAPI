# SheetPlan

## Class Definition

```python
class SheetPlan(decl: SheetDecl)
```

*Source: dxf_engine/planner.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import SheetPlan`

## Description

The dimensioning-plan solver: SheetDecl → solve() → resolved/issues()/report() → render().

Solving: views (projection, scale, arrangement, centre lines, section marks) → linear dimensions
(per view and side, small inside, large outside) → diameter/radius dimensions → datum symbols → surface texture → leaders →
parameter coverage. What a dimension measures is taken from the model (`bind`); every conflict follows "minimum
adjustment": candidate positions are tried in order and recorded in Resolved.adjust; when nothing fits, the
least-conflicted position is drawn and reported, never silently dropped.

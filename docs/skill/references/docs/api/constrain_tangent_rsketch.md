# constrain_tangent_rsketch

## API Definition

```python
def constrain_tangent_rsketch(sketch, a, b, *, at_a=None, at_b=None, mode='external', constraint_id=None)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import constrain_tangent_rsketch`

## Description

Constrain supported curves to be tangent on an explicit branch.

``at_a``/``at_b`` select ``"start"`` or ``"end"`` for arc and
B-spline endpoint tangency. Circle-circle tangency accepts
``mode="external"`` or ``mode="internal"``.

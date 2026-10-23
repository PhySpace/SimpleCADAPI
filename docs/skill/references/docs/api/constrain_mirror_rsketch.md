# constrain_mirror_rsketch

## API Definition

```python
def constrain_mirror_rsketch(sketch, a, axis, b, *, constraint_id=None)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import constrain_mirror_rsketch`

## Description

Constrain two same-kind entities to be mirror images about a line.

Lines match endpoints by nearest initial position; circles match centers;
arcs match endpoints and centers.

# constrain_line_distance_rsketch

## API Definition

```python
def constrain_line_distance_rsketch(sketch, a, b, value, *, constraint_id=None, driving=True)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import constrain_line_distance_rsketch`

## Description

Add a driving minimum-distance constraint between two sketch lines.

The constraint drives the distance from line ``a``'s start point to line
``b``; for parallel lines this is exactly the minimum distance between
them. The solved point keeps its initial side of line ``b``.

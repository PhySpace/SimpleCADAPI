# add_ellipse_rsketch

## API Definition

```python
def add_ellipse_rsketch(sketch, entity_id, center, major_point, minor_point, *, construction=False)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import add_ellipse_rsketch`

## Description

Add an ellipse entity derived from three solving points.

The ellipse shape is a pure function of the center, major-axis, and
minor-axis points; radius constraints therefore solve natively.

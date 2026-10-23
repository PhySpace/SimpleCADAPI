# make_ellipse_redge

## API Definition

```python
def make_ellipse_redge(center, major_radius, minor_radius, normal=(0, 0, 1), *, major_direction=None, tag_prefix=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_ellipse_redge`

## Description

Create a full ellipse edge.

``major_direction`` orients the major axis in the ellipse plane; when
omitted the plane basis derived from ``normal`` picks it.

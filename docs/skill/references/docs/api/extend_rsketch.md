# extend_rsketch

## API Definition

```python
def extend_rsketch(sketch, entity, end, *, to=None)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import extend_rsketch`

## Description

Lengthen a sketch line or B-spline at ``end`` ('start' or 'end') until it meets ``to`` (default: the nearest entity ahead).

The sketch is solved first; the end point moves onto the other entity (a line, circle, arc, ellipse or B-spline)
and is tied to it with a point_on constraint. A line goes straight on. A B-spline grows curvature-continuously
(GeomLib.ExtendCurveToPoint) towards where its end tangent meets the target and stops at the first crossing: its
first part keeps its shape, its control points change near the moved end (unmoved ones keep their ids, the others
are new points) and a cubic Bezier chain stays one. A closed B-spline has no end to extend. Refused when the end
point is shared with another entity. The length dimension of the entity, dimensions or fix on the moved point, and
for a B-spline its fix and its tangent at the moved end, no longer hold and are dropped.

# trim_rsketch

## API Definition

```python
def trim_rsketch(sketch, entity, at, *, against=None)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import trim_rsketch`

## Description

Remove the part of a line, circle, arc or B-spline that contains ``at``, between the nearest cuts.

A cut is a crossing with another non-construction line, circle, arc, ellipse or B-spline (``against`` limits
which ones) or an end of the entity; a tangent touch is one cut. ``at`` is a point (x, y) in sketch coordinates
or a point id. Lines, arcs and open B-splines keep the pieces on either side; a circle keeps the arc left over and
a closed B-spline (periodic, or starting and ending on one point) the piece left over (both need two cuts); an
entity nothing crosses is removed whole. A B-spline piece is a new B-spline (ids s1, s2, ...) of the same curve:
its first and last control points are its end points, its inner control points are sketch points (an original
control point the piece keeps unmoved keeps its id, the others are new points p1, p2, ...), and its knots are no
longer uniform. Cut points are tied to the cutter with point_on; line pieces inherit horizontal/vertical;
constraints on an end point stay with the piece that keeps that point, a tangent at a B-spline end (at_a/at_b)
moves to the piece that keeps that end, other constraints that name the removed entity are removed, and so are
the original control points no piece uses, with their constraints. Use diff_sketch_rsketchdiff(before, after) to
see what changed.

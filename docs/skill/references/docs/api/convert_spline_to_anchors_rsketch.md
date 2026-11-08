# convert_spline_to_anchors_rsketch

## API Definition

```python
def convert_spline_to_anchors_rsketch(sketch, spline)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import convert_spline_to_anchors_rsketch`

## Description

Write a B-spline in anchor form (Bezier spans: anchors on the curve, a handle on each side).

A non-rational B-spline of degree 3 or less keeps its exact shape (degree elevation and knot insertion); a rational one
or one of a higher degree is approximated within 1e-4 and the notes of metadata ``last_edit`` say how close. The end
points keep their ids; an inner control point that does not move keeps its id, the others are new points ``p<n>``, and
control points no entity uses any more are deleted with their constraints. A B-spline already in anchor form is left
as it is (a note says so). Refused for a periodic B-spline. See ``insert_spline_anchor_rsketch`` for the form.

# remove_spline_anchor_rsketch

## API Definition

```python
def remove_spline_anchor_rsketch(sketch, spline, anchor)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import remove_spline_anchor_rsketch`

## Description

Remove an inner anchor (and its two handles) from a B-spline in anchor form.

``anchor`` is the point id of an anchor that is not an end. The spans on either side become one span: its handles are
the outer handles of the two spans, which keep their ids and directions and get the lengths that fit the old curve best
(least squares, never reversed), so removing an anchor that ``insert_spline_anchor_rsketch`` made gives back the curve
it split. A handle that a constraint or another entity holds keeps its place. The removed points are deleted unless
another entity uses them, and the constraints on deleted points are dropped (the notes of metadata ``last_edit`` name
them). Refused for an end anchor, a handle, a point that is not on the spline, and a B-spline not in anchor form.

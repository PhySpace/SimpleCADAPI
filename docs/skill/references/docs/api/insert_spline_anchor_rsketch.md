# insert_spline_anchor_rsketch

## API Definition

```python
def insert_spline_anchor_rsketch(sketch, spline, at)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import insert_spline_anchor_rsketch`

## Description

Insert an anchor into a B-spline in anchor form, at the curve point nearest ``at``, without changing the curve.

The anchor form is a pen tool's curve: anchors on the curve, each with an in-handle and an out-handle. It is a cubic
B-spline whose control points are ``[A0, out0, in1, A1, out1, in2, A2, ...]`` (every one a sketch point) and whose
inner knots have multiplicity 3, so every span is a cubic Bezier from one anchor to the next; the editor's spline tool
draws them, ``convert_spline_to_anchors_rsketch`` turns another B-spline into one. Moving an anchor or a handle is
moving its point (the solver moves every control point of such a spline).

The span under ``at`` is split at that place (de Casteljau), so the curve is the same: the span's two handles get
shorter (they keep their ids; a dimension or fix on them no longer holds and is dropped, see the notes) and the new
anchor and its two handles are new points ``p<n>`` (the lowest free numbers). The new knot is the curve parameter of
the place, with multiplicity 3. ``at`` is a point (x, y) in sketch coordinates or a point id. The sketch is solved
first. Refused for a B-spline that is not in anchor form and at an existing anchor. Metadata ``last_edit`` notes name
the new anchor and its handles; ``diff_sketch_rsketchdiff(before, after)`` lists them too.

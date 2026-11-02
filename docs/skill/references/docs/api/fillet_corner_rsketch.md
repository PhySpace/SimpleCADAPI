# fillet_corner_rsketch

## API Definition

```python
def fillet_corner_rsketch(sketch, a, b, radius)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import fillet_corner_rsketch`

## Description

Round the corner where lines ``a`` and ``b`` meet with an arc of ``radius``.

The lines must share an end point (the corner). The sketch is solved first; both lines are shortened to the
tangent points and the arc (counter-clockwise from its start to its end around its centre) is tied to each line
with a tangent constraint and to ``radius`` with a driving radius dimension, so the result survives a re-solve.
The corner point goes away unless a constraint or another entity uses it (then it stays as the sharp corner and
the cut-off parts of the lines stay as construction lines). horizontal/vertical and the other constraints that
hold for a shorter line stay; lengths and other dimensions of the lines are dropped (see
diff_sketch_rsketchdiff). Refused: parallel lines, lines that share no point, a radius too large for the
shorter line (the message names the largest radius). New ids: points ``p<n>``, arc ``a<n>``, legs ``l<n>``,
constraints ``c_<kind>_<n>``.

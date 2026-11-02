# trim_rsketch

## API Definition

```python
def trim_rsketch(sketch, entity, at, *, against=None)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import trim_rsketch`

## Description

Remove the part of a line, circle or arc that contains ``at``, between the nearest cuts.

A cut is a crossing with another non-construction entity (``against`` limits which ones) or an end of the
entity. ``at`` is a point (x, y) in sketch coordinates or a point id. Lines and arcs keep the pieces on either
side, a circle keeps the arc left over (it needs two cuts), an entity nothing crosses is removed whole. Cut
points are tied to the cutter with point_on; line pieces inherit horizontal/vertical; constraints that name
the removed entity are removed. Use diff_sketch_rsketchdiff(before, after) to see what changed.

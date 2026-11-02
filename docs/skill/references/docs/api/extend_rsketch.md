# extend_rsketch

## API Definition

```python
def extend_rsketch(sketch, entity, end, *, to=None)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import extend_rsketch`

## Description

Lengthen a sketch line at ``end`` ('start' or 'end') until it meets ``to`` (default: the nearest entity ahead).

The sketch is solved first; the end point moves onto the other entity and is tied to it with a point_on
constraint. Refused when the end point is shared with another entity. The length dimension of the line, and
dimensions or fix on the moved point, no longer hold and are dropped.

# chamfer_corner_rsketch

## API Definition

```python
def chamfer_corner_rsketch(sketch, a, b, distance)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import chamfer_corner_rsketch`

## Description

Cut the corner where lines ``a`` and ``b`` meet with a straight line ``distance`` from the corner along each line.

Same rules as fillet_corner_rsketch: the lines must share an end point, both are shortened, the corner point goes
away unless something else uses it. The new line ``l<n>`` joins the two points, with a driving length (its chord)
and a driving angle to ``a``. ``distance`` must be shorter than the shorter line (the message names it).

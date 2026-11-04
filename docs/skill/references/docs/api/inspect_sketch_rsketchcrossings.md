# inspect_sketch_rsketchcrossings

## API Definition

```python
def inspect_sketch_rsketchcrossings(sketch)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import inspect_sketch_rsketchcrossings`

## Description

List where the non-construction lines, circles, arcs, ellipses and B-splines of the solved sketch cross, away from every point of the sketch.

Returns ``[{"at": [x, y], "entities": [a, b]}]`` in sketch coordinates: the same crossings ``trim_rsketch`` cuts at (a tangent touch is one crossing). A crossing that is already a point of the sketch (a shared end) is not listed. A conflicting sketch is solved as far as it goes. Not recorded in the graph.

# sample_curve_rcurvature

## API Definition

```python
def sample_curve_rcurvature(edge, count=64)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import sample_curve_rcurvature`

## Description

Sample an edge for a curvature comb: ``count`` points evenly in its parameter range.

Returns ``{parameters, points, tangents, normals, curvatures, max_curvature}`` in the current coordinate system; a normal points to the centre of curvature and is zero where the curve is straight. Not recorded in the graph.

# sample_surface_risocurves

## API Definition

```python
def sample_surface_risocurves(face, u_count=5, v_count=5, samples=48)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import sample_surface_risocurves`

## Description

Sample isocurves of a face, clipped to its trimming.

``u_count`` lines of constant u and ``v_count`` of constant v, evenly inside the face's (u, v) bounds, each sampled at ``samples`` points. Returns ``{u: [{parameter, segments}], v: [...], uv_bounds}``; ``segments`` are the runs of points that lie on the face. Not recorded in the graph.

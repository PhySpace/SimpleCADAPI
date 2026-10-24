# make_face_from_sketch_rface

## API Definition

```python
def make_face_from_sketch_rface(sketch, profile=0, *, inner_profiles=[], require_fully_constrained=False, strict=True, tolerance=1e-07, max_iterations=80)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import make_face_from_sketch_rface`

## Description

Promote one outer and optional inner sketch profiles to a face.

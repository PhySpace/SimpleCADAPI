# make_wire_from_sketch_rwire

## API Definition

```python
def make_wire_from_sketch_rwire(sketch, profile=0, *, require_fully_constrained=False, strict=True, tolerance=1e-07, max_iterations=80)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import make_wire_from_sketch_rwire`

## Description

Promote a sketch profile (closed loop or open chain) to a concrete wire, solving internally.

# add_bspline_rsketch

## API Definition

```python
def add_bspline_rsketch(sketch: Sketch, entity_id: str, start: Union[SketchRef, str], end: Union[SketchRef, str], control_points: Sequence[Any], degree: int = 3, knots: Optional[Sequence[float]] = None, multiplicities: Optional[Sequence[int]] = None, weights: Optional[Sequence[float]] = None, periodic: bool = False, *, construction: bool = False) -> Sketch
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import add_bspline_rsketch`

## Description

Add a B-spline curve entity to a sketch.

The start/end point refs link the B-spline into a closed profile
loop. A closed curve may reuse one seam ref for both endpoints.
Control points may be literal 2-D coordinates or point refs. A periodic
seam links topology without replacing the periodic curve's poles.

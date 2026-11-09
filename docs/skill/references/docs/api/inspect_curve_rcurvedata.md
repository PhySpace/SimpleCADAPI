# inspect_curve_rcurvedata

## API Definition

```python
def inspect_curve_rcurvedata(edge)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import inspect_curve_rcurvedata`

## Description

Read the NURBS data of an edge's curve: what the curve edits work on.

Returns ``{type, analytic, editable, conversion, degree, poles, weights, knots, multiplicities, periodic, rational, closed, domain, reversed, parameter_range}``. ``poles`` are points in the current coordinate system, indices are 0-based (the ``moves`` of ``move_curve_poles_redge``); ``parameter_range`` is the edge's own range (where ``insert_curve_knot_redge`` may insert). For a line, circle or other analytic curve ``editable`` is false, ``conversion`` is ``"convert_to_bspline_redge"`` and the data is what that conversion would produce. Not recorded in the graph.

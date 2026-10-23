# DrawingMeasurements

## Class Definition

```python
class DrawingMeasurements(measurement_count: int, scale_mm_per_pt: float | None, measurements: list[dict[str, Any]])
```

*Source: inspect/drawing/calibrate.py*

## Import Surface

- drawing-inspection namespace: `from simplecadapi.inspect import drawing` then `drawing.DrawingMeasurements(...)`; unavailable inside GraphSession

## Description

Point-pair and stroke-length measurements with optional mm conversion.

Every entry keeps its native ``length_pt``; ``length_mm`` is populated
only when a calibration is supplied. Millimetre values derived here are
"inferred"-grade claims: they must be cross-checked against annotated
dimensions before they harden into facts.

# preflight_loft

## API Definition

```python
def preflight_loft(sections: Sequence[Union[Wire, Vertex]], *, result_kind: str = "solid", ruled: bool = False, boundary_conditions: Optional[Mapping[str, object]] = None) -> Dict[str, object]
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import preflight_loft`
- surface namespace: `from simplecadapi.surface import preflight_loft`

## Description

Inspect loft sections without constructing geometry. The JSON-safe report checks section types, endpoint Vertex placement, closedness, BREP validity, duplicate or reversing stations, approximate planar orientation consistency, and predicted side-face complexity. For smooth lofts it also reports `smooth_overshoot_risk` when an interior section is a clear local size extremum; reconstruction should then require STEP roundtrip and bounding-box comparison.

The current `BRepOffsetAPI_ThruSections` backend does not portably enforce endpoint tangent, draft-angle, curvature, or magnitude conditions. Supplying a non-free `boundary_conditions` request therefore produces the explicit `boundary_condition_unsupported` error instead of silently ignoring it.

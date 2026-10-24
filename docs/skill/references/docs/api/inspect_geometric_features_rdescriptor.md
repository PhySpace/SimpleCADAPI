# inspect_geometric_features_rdescriptor

## API Definition

```python
def inspect_geometric_features_rdescriptor(model_or_path: ModelInput, *, feature_kinds: Sequence[str] = FEATURE_CATEGORIES, tolerance: float | None = None, angular_tolerance_degrees: float = 0.5, max_features: int = 500) -> dict[str, Any]
```

*Source: inspect/brep/feature_catalog.py*

## Import Surface

- inspection namespace: `from simplecadapi.inspect import brep` then `brep.inspect_geometric_features_rdescriptor(...)`; unavailable inside GraphSession

## Description

Return the normalized v4 catalog for final-BREP geometric candidates.

``extrusion`` means extrusion-style geometry; ``whole_body_prism`` is only
one subtype. ``revolution`` covers whole and local, full and partial-angle
geometry. Circular and non-circular closed negative spaces remain under the
``hole`` category. Values describe final geometry, not original CAD history
or manufacturing intent. ``coverage`` lists every face that no returned
feature owns; those faces belong in the unresolved-region list.

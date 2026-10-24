# inspect_manufacturing_hints_rdescriptor

## API Definition

```python
def inspect_manufacturing_hints_rdescriptor(model_or_path: ModelInput, *, feature_kinds: Sequence[str] = FEATURE_KINDS, tolerance: float | None = None, angular_tolerance_degrees: float = 0.5, max_hints: int = 500) -> dict[str, Any]
```

*Source: inspect/brep/manufacturing.py*

## Import Surface

- inspection namespace: `from simplecadapi.inspect import brep` then `brep.inspect_manufacturing_hints_rdescriptor(...)`; unavailable inside GraphSession

## Description

Return deterministic, highlightable manufacturing-feature candidates.

Fillet and chamfer hints require supported analytic carrier evidence.
Sheet-metal hints require opposed constant-thickness skins, a thin-body
ratio, and a matching thickness-times-midsurface volume model. Hole and
non-circular holes, local or whole-body extrusion/revolution geometry, and
loft/sweep geometry are available only when their category is explicitly
included in ``feature_kinds``; they describe
geometric explanations and do not recover the original feature history.
Every hint includes stable entity IDs, measurements, evidence, and
non-probabilistic confidence. The result describes final BREP geometry only;
it does not infer process choice, bend allowance, tooling, or manufacturing
intent.

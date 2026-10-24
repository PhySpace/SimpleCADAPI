# render_manufacturing_hints_rpath

## API Definition

```python
def render_manufacturing_hints_rpath(model_or_path: ModelInput, output_path: str | Path, *, feature_kinds: Sequence[str] = FEATURE_KINDS, tolerance: float | None = None, angular_tolerance_degrees: float = 0.5, max_hints: int = 500, views: Sequence[tuple[float, float, str]] | None = None, image_size: tuple[float, float] = (18.0, 12.0), dpi: int = 180, linear_deflection: float = 0.12, angular_deflection: float = 0.18) -> Path
```

*Source: inspect/brep/manufacturing.py*

## Import Surface

- inspection namespace: `from simplecadapi.inspect import brep` then `brep.render_manufacturing_hints_rpath(...)`; unavailable inside GraphSession

## Description

Render manufacturing hints as deterministic category-colored overlays.

Sheet-metal skins are blue, bends are orange, extrusion geometry is green,
revolution geometry is cyan, lofts are pink, sweeps are indigo, holes are
purple, fillets are red, and chamfers are yellow. Hole, extrusion,
revolution, loft, and sweep candidates must be explicitly enabled. They
explain final geometry rather than original
feature history. Analysis always runs against the current model so entity
IDs cannot be reused across different BREP instances.

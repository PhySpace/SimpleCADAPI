# render_geometric_features_rpath

## API Definition

```python
def render_geometric_features_rpath(model_or_path: ModelInput, feature_report: Mapping[str, Any] | str | Path, output_path: str | Path, *, views: Sequence[tuple[float, float, str]] | None = None, image_size: tuple[float, float] = (18.0, 12.0), dpi: int = 180, linear_deflection: float = 0.12, angular_deflection: float = 0.18) -> Path
```

*Source: inspect/brep/feature_visualization.py*

## Import Surface

- inspection namespace: `from simplecadapi.inspect import brep` then `brep.render_geometric_features_rpath(...)`; unavailable inside GraphSession

## Description

Render the supplied feature report with the approved category palette.

The function consumes a report dictionary or saved ``feature-index.json``.
It never invokes feature recognition. It verifies the target hash and every
highlighted entity ID before rendering so the image cannot silently drift
from the authoritative per-instance catalog.

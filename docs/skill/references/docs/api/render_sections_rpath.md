# render_sections_rpath

## API Definition

```python
def render_sections_rpath(*, sections: Sequence[Mapping[str, Any]], output_path: str | Path, titles: Sequence[str] | None = None, columns: int = 3, image_size_per_panel: tuple[float, float] = (6.0, 5.0), dpi: int = 180) -> Path
```

*Source: inspect/brep/slices.py*

## Import Surface

- inspection namespace: `from simplecadapi.inspect import brep` then `brep.render_sections_rpath(...)`; unavailable inside GraphSession

## Description

Render detailed section descriptors as a local-coordinate 2D atlas.

``sections`` must contain non-compact results from
``inspect_section_rdescriptor``. The renderer consumes each contour's
existing ``samples_2d`` values and never recalculates or projects BREP
geometry.

## Parameters

### sections

- **Description**: Detailed section descriptors in the desired panel order.

### output_path

- **Description**: Destination image path. Missing parent directories are created.

### titles

- **Description**: Optional panel titles in the same order as ``sections``.

### columns

- **Description**: Positive number of atlas columns.

### image_size_per_panel

- **Description**: Positive panel width and height in inches.

### dpi

- **Description**: Positive output resolution in dots per inch.

## Returns

-------
Path
The image path that was written.

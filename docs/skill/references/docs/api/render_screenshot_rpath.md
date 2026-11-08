# render_screenshot_rpath

## API Definition

```python
def render_screenshot_rpath(shapes: 'Solid | Sequence[Solid]', output_path: 'str | PathLike[str]', highlight_tags: 'Sequence[str] | None' = None, tag_labels: 'dict[str, str] | None' = None, image_size: 'tuple[int, int]' = (1400, 900), view: "Literal['auto', 'iso', 'isometric', 'top', 'bottom', 'front', 'back', 'left', 'right', 'front_right', 'front_left', 'rear_right', 'rear_left'] | tuple[Angle, Angle] | None" = 'auto', views: 'Sequence[tuple[Angle, Angle, str]] | None' = None, show_axes: 'bool' = True, show_legend: 'bool' = True, zoom: 'float' = 4.0, show_callouts: 'bool' = True, linear_deflection: 'Length | None' = None, angular_deflection: 'float | None' = None, style: "Literal['studio', 'standard']" = 'studio', edge_width_scale: 'float | None' = None, view_up: 'Direction3 | None' = None, supersample: 'int' = 2, highlight_edges: 'Sequence[AnyShape] | None' = None, highlight_edge_width: 'float' = 4.5) -> 'str'
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import render_screenshot_rpath`

## Description

Render solids or raw TopoDS shapes through the one OCCT/VTK pipeline.

``shapes`` accepts SDK ``Solid`` objects (with full tag highlight,
callout and legend support) or raw ``TopoDS_Shape`` entries from the
STEP inspection family (same engine, same edge ink and supersampling,
no tag features).

``highlight_edges`` draws the given edges (SDK ``Edge`` objects or raw
``TopoDS_Edge``) as crisp orange highlight lines exactly on the edge —
the failure-marking channel used by the blend diagnostics.

There is exactly one output form: a multi-view grid of one to four
panels, each carrying annotations. ``view="auto"`` (default) uses the
standard four-view set; an explicit preset name or ``(elevation,
azimuth)`` pair renders a single full-frame panel; ``views`` accepts
up to four explicit ``(elevation, azimuth, label)`` triples.
``zoom`` applies to single-panel renders only.

``supersample (default 2) renders at an integer multiple and
downsamples with LANCZOS for deterministic crisp edges; 1 renders 1:1.
``style="studio"`` turns the single-view path into a product shot
(gradient backdrop, three-point lighting, bold tubed BRep edges);
``linear_deflection``/``angular_deflection`` tighten the tessellation
for high-resolution exports. ``edge_width_scale`` tunes the studio edge
tube radius as a fraction of model span (default 0.0026; use ~0.001 for
exploded stacks so the ink does not swamp small parts).

The prepare half (validation + tessellation) runs on the calling
thread; the GL work runs in a crash-isolated worker subprocess, so a
native VTK crash can never take the caller down.

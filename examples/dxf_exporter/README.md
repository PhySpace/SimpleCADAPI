# Single-part DXF drawing

Install `simplecadapi[drawing]`. Use `simplecadapi[drawing,verify]` for the
optional polygonal hidden-line projection on spline-heavy geometry.

```sh
sca drawing --notebook examples/dxf_exporter/stepped_mount.py \
  --primary-view top --no-section --sheet A3 \
  --out examples/dxf_exporter/out/base.dxf
sca drawing --notebook examples/dxf_exporter/stepped_mount.py \
  --set HOLE_DIAMETER=8 --set HOLE_PITCH=36 \
  --primary-view top --no-section --sheet A3 \
  --out examples/dxf_exporter/out/variant.dxf
sca drawing --step examples/dxf_exporter/out/variant.model.step \
  --mode engineering --drawing-json examples/dxf_exporter/out/variant.drawing.json \
  --out examples/dxf_exporter/out/replay.dxf --pdf
```

The base drawing carries a 31 mm spacing, a diameter 6 H7 hole and an 8 mm
ledge with +0.10/-0.05 deviations. The variant changes the first two marks to
36 mm and diameter 8 H7. Verify the named parameters, measurements and unbound
construction variables in `design_intent` inside each `*.plan.json`.

The notebook gives geometric selectors for two cylinder axes and two planar
faces. The SDK derives the actual values from geometry and reads the native DXF
dimensions back. The notebook supplies the expected values and requirements.
Changing only the expected pitch blocks a new DXF export.

For STEP without a notebook, `sca drawing --step part.step --out part.dxf`
proposes the drawing, and `--plan-only` exposes the plan for agent review.
`--templates` lists metric single-part drafting presets and review prompts.
See [the drawing workflow](../../docs/skill/references/workflows/engineering-drawing.md).

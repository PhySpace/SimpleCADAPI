# render_plan

## API Definition

```python
def render_plan(plan, dxf_path, png_path)
```

*Source: dxf_engine/render.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import render_plan`

## Description

Render the solved SheetPlan as a GB-layer DXF + PNG pair.

The DXF goes through ezdxf (hand-made primitives: thin solid dimension/extension lines, solid arrows, rotation-normalised text,
GB layers 01_THICK_SOLID/08_DASHED/05_CENTER/DIMENSION/TEXT); the PNG is produced from the DXF through PyMuPdf
for multimodal cross-checking. A text action log that diffs well between versions is written too.

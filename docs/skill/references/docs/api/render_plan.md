# render_plan

## API Definition

```python
def render_plan(plan, dxf_path, png_path)
```

*Source: dxf_engine/render.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import render_plan`

## Description

Render the solved SheetPlan as a GB-layer DXF + PNG pair, then read the DXF back and verify its dimensions.

The DXF goes through ezdxf (GB layers 01_THICK_SOLID/08_DASHED/05_CENTER/DIMENSION/TEXT, native DIMENSION
entities in style "GB"); the PNG is produced from the DXF through PyMuPdf for multimodal cross-checking.
Returns {"dxf", "png", "entities", "dimensions", "issues"}; the issues also enter `plan.issues()` and `report()`.

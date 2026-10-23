# SheetDecl

## Class Definition

```python
class SheetDecl(title: str, dwg_no: str, scale: float, front: str, anchor: tuple, views: list, datums: list = field(default_factory=list), dims: list = field(default_factory=list), centers: list = field(default_factory=list), leaders: list = field(default_factory=list), notes: list = field(default_factory=list), params: dict = field(default_factory=dict), material: str = 'PLA-CF / PAHT', notes_zone: tuple = (25.0, 5.0, 232.0, 90.0), diag_png: str = '')
```

*Source: dxf_engine/model.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import SheetDecl`

## Description

The complete declaration of one sheet: sheet information + views + datums + dimensions + centre lines + leaders + parameter table.

The caller declares only "what to express" and no sheet coordinate; the layout and the annotation positions are
solved by SheetPlan.solve(). front/anchor anchors the main view, the other views align to it through
ViewDecl.align (first-angle projection, length-aligned / height-aligned).

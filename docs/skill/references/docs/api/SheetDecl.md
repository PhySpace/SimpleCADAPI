# SheetDecl

## Class Definition

```python
class SheetDecl(title: str, dwg_no: str, scale: float | None, front: str, anchor: tuple | None, views: list, datums: list = field(default_factory=list), dims: list = field(default_factory=list), centers: list = field(default_factory=list), leaders: list = field(default_factory=list), notes: list = field(default_factory=list), params: dict = field(default_factory=dict), material: str = '', designer: str = '', revision: str = '1.0', sheet: str = 'A3', roughs: list = field(default_factory=list), general_rough: str = '', show_captions: bool = False, auto_centers: bool = True, notes_zone: tuple | None = None, diag_png: str = '')
```

*Source: dxf_engine/model.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import SheetDecl`

## Description

The complete declaration of one sheet: sheet information + views + datums + dimensions + centre lines + leaders + parameter table.

The caller declares only "what to express" and no sheet coordinate; the layout and the annotation positions are
solved by SheetPlan.solve(). front/anchor anchors the main view, the other views align to it through
ViewDecl.align (first-angle projection, length-aligned / height-aligned).

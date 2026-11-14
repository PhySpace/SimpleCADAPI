# ViewDecl

## Class Definition

```python
class ViewDecl(name: str, shape: object, n: tuple, xd: tuple, align: dict = field(default_factory=dict), anchor: tuple | None = None, section: tuple | None = None, label: str = '', mark_in: str | None = None)
```

*Source: dxf_engine/model.py*

## Import Surface

- drawing namespace: `from simplecadapi.dxf_engine import ViewDecl`

## Description

An HLR projected view. n = viewing direction, xd = screen-right direction in the projection plane; align defines the layout constraint.

shape is the solid itself (so that selector references resolve against it) or its OCCT shape (`part.wrapped`).
section=(x, y, z) makes it a section view: the part is cut by the plane through that point square to n, the half
towards the viewer is removed and the cut faces are hatched; `label` names it ("A" → title "A-A") and `mark_in`
names the view that shows where the cut is (cutting-plane symbol).

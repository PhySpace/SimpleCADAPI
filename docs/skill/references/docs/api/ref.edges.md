# ref.edges

## API Definition

```python
def ref.edges(*refs: Union[ElementRef, Sequence[ElementRef]]) -> Any
```

*Source: ref.py*

## Import Surface

- stable references: `import simplecadapi as scad` then `scad.ref.edges(...)`

## Description

The selection of the edges the references name (see :func:`faces`).

## Examples

```python
>>> rims = scad.ref.edges(scad.ref.edge("base", "make_box_rsolid", topo="edge_1", guard=("LINE", (-20, 0, 10), 20)))
>>> rounded = scad.fillet_rsolid(base, rims, 1.0)
```

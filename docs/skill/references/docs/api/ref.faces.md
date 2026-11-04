# ref.faces

## API Definition

```python
def ref.faces(*refs: Union[ElementRef, Sequence[ElementRef]]) -> Any
```

*Source: ref.py*

## Import Surface

- stable references: `import simplecadapi as scad` then `scad.ref.faces(...)`

## Description

The selection of the faces the references name: ``ql.faces().where(ql.ref(r1) | ql.ref(r2) ...)``.

Pass it where an operation takes faces (``shell_rsolid(faces_to_remove=...)``, ``apply_tag_rselection``): the
operation resolves it in the shape it receives, and each reference raises ``ElementRefError`` there if it is split
(without ``piece``) or lost.

## Examples

```python
>>> opening = scad.ref.faces(scad.ref.face("base", "make_box_rsolid", role="box.top"))
>>> cup = scad.shell_rsolid(base, faces_to_remove=opening, thickness=1.0)
```

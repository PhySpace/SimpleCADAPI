# ql.ref

## API Definition

```python
def ql.ref(reference: 'Union[ElementRef, Mapping[str, Any], str]') -> 'Any'
```

*Source: ql.py*

## Import Surface

- submodule: `from simplecadapi.ql import ref` or `simplecadapi.ql.ref`

## Description

A stable reference as a ``ql`` predicate (``scad.ql.ref``): keeps the entities it names in the scope.

The reference is resolved through the recorded history of the shape the selector is resolved against, once per
query run; a split reference (without ``piece``) or a lost one raises ``ElementRefError`` there, it never
matches nothing silently.  The predicate stores the reference as data, so the selector serialises and replays.

## Parameters

### reference

- **Description**: An :class:`ElementRef`, its record (``to_dict()``) or its code (``'scad.ref.face(...)'``).

## Returns

SerializablePredicate: Use it in ``where(...)`` of a selector resolved against one shape.

## Examples

```python
>>> top = scad.ref.face("base", "make_box_rsolid", role="box.top")
>>> scad.ql.faces().where(scad.ql.ref(top)).exactly(1).resolve(part)
```

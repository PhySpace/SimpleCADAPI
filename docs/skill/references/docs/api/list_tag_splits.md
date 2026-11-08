# list_tag_splits

## API Definition

```python
def list_tag_splits(shape)
```

*Source: operators/selection.py*

## Import Surface

- top-level: `from simplecadapi import list_tag_splits`

## Description

The tagged entities that the operations behind a shape split into pieces.

A tag follows its entity the way a reference does: while the entity stays one entity it keeps the tag; when an
operation splits it (a slot cut across a tagged face, a cut through a tagged body), the tag does not go to every
piece. Each piece carries ``<tag>.split1`` .. ``<tag>.split<n>`` instead, numbered as the operation recorded them (by
centre, then size), and ``ql.tag("<tag>")`` finds none of them. Name the pieces you mean with tags of your own after the
split, or select them with ``ql.tag("<tag>.split1")`` / ``ql.tag("<tag>.*")``.

## Parameters

### shape

- **Description**: A shape made in a recording session (its history is read).

## Returns

list[dict]: One row per split, upstream first: ``tag`` (the tag the entity had), ``into`` (the tags of the pieces,
in piece order), ``node_id`` and ``op`` (the operation that split it), ``source_topo_id`` and ``pieces``
(``output_slot``, ``kind``, ``topo_id`` of each piece in that operation's output). Empty for a shape without
recorded history.

## Examples

```python
>>> top = scad.apply_tag_rselection(box, scad.ql.faces().where(scad.ql.prop("geom.center.z", ">=", 9.9)), "mount.top")
>>> halves = scad.cut_rsolid(top, slot)              # the slot splits the top face (and the body)
>>> [row["into"] for row in scad.list_tag_splits(halves[0])]
[['mount.top.split1', 'mount.top.split2']]
```

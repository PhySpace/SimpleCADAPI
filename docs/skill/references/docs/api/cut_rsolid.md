# cut_rsolid

## API Definition

```python
def cut_rsolid(*solids, skip_non_intersecting=True, tracking_policy='full', on_split='pieces')
```

*Source: operators/boolean.py*

## Import Surface

- top-level: `from simplecadapi import cut_rsolid`

## Description

Compute the boolean difference of solids.

Accepts a base solid followed by one or more tool solids, including nested
sequences, and returns a single `Solid`.

## Parameters

### solids

- **Description**: One or more Solid objects or sequences of Solid. Nested sequences are flattened before processing; the first solid is the base, the rest are subtracted in order.

### skip_non_intersecting

- **Description**: When True, tools with no meaningful intersection are ignored for interactive convenience. Graph replay records this flag and should use False for strict diagnostic workflows.

### tracking_policy

- **Description**: FULL computes topology history and lineage. GRAPH keeps the replayable operation node without computing a TopoDelta.

### on_split

- **Description**: What a cut that splits the body (a slot through a bar) returns.

### ``"pieces"``

- **Type**: `default`
- **Description**: every piece, as ``list[Solid]`` ordered by centroid

### (x, then y, then z), recorded like ``cut_rsolid_list``. ``"error"``

- **Description**: raise, for code that needs exactly one Solid.

## Returns

Solid: The cut result solid, when the result is one piece.
list[Solid]: The pieces (a ``scad.Pieces``), when the cut split the body
(``on_split="pieces"``). Operations that take one shape run on every piece
(``cut_rsolid(pieces, tool)``, ``translate_shape(pieces, ...)``) and return
``Pieces``; a selector's cardinality is checked over all pieces. They are notebook values: a Part holds exactly one solid, so make one Part of each piece
(an Assembly of them is the several-piece result), not ``make_part_rpart(body=pieces)``.

## Raises

- **SimpleCADError**: The cut produced no solid, or (``on_split="error"``) split the body. Use ``cut_rsolid_list`` to always get a list.

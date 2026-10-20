# boolean_rsolidlist

## API Definition

```python
def boolean_rsolidlist(left: Sequence[Solid], right: Sequence[Solid], operation: str) -> list[Solid]
```

*Source: operators/boolean.py*

## Import Surface

- top-level: `from simplecadapi import boolean_rsolidlist`

## Description

Apply a set boolean to two body groups, retaining every result solid.

Members of each group are a geometric set. Unlike single-solid booleans,
a cut or intersection may return several solids or an empty list.
Topology lineage is partial; the ordered inputs and all output slots are
recorded so downstream features can replay the same geometry.

## Parameters

### left

- **Description**: The first group of solids.

### right

- **Description**: The second group of solids.

### operation

- **Description**: ``"cut"``, ``"intersect"`` or ``"union"``.

## Returns

The result solids, possibly several or none.

## Raises

- **TypeError**: A group contains something that is not a Solid.
- **ValueError**: ``operation`` is unknown, or a member is invalid or empty.

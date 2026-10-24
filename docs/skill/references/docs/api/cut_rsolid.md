# cut_rsolid

## API Definition

```python
def cut_rsolid(*solids, skip_non_intersecting=True, tracking_policy='full')
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

## Returns

Solid: The cut result solid.

## Raises

- **SimpleCADError**: The cut produced no solid, or split the body into several (a slot through a bar). Use ``cut_rsolid_list`` to keep every piece.

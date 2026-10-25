# cut_rsolid_list

## API Definition

```python
def cut_rsolid_list(*solids, skip_non_intersecting=True, tracking_policy='full')
```

*Source: operators/boolean.py*

## Import Surface

- top-level: `from simplecadapi import cut_rsolid_list`

## Description

Compute the boolean difference of solids and keep every piece.

A cut can split the body (a slot through a bar leaves two parts) or consume it
(a tool that encloses the whole body leaves nothing). ``cut_rsolid`` refuses
such a result because it returns exactly one ``Solid``; this operator returns
them all. A tool is cut from every piece it meets, so several tools may split
a body into several parts.

``pieces = cut_rsolid_list(bar, slot)`` returns both halves of a bar cut by
a through slot. Use ``cut_rsolid`` when the result must be one solid.

## Parameters

### solids

- **Description**: One or more Solid objects or sequences of Solid. Nested sequences are flattened before processing; the first solid is the base, the rest are subtracted in order.

### skip_non_intersecting

- **Description**: When True, a tool that meets none of the current pieces is ignored; when False it raises.

### tracking_policy

- **Description**: FULL computes topology history and lineage. GRAPH keeps the replayable operation node without computing a TopoDelta.

## Returns

list[Solid]: Every piece of the cut, in kernel order; empty when the tools
consume the base.

## Raises

- **SimpleCADError**: An input is not a valid Solid, or the kernel could not compute the cut.

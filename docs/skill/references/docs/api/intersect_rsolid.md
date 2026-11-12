# intersect_rsolid

## API Definition

```python
def intersect_rsolid(*solids, clean=True)
```

*Source: operators/boolean.py*

## Import Surface

- top-level: `from simplecadapi import intersect_rsolid`

## Description

Compute the boolean intersection of solids.

Accepts one or more solids, including nested sequences, and returns a single
`Solid`. If the inputs do not overlap meaningfully, the API raises a clear
error instead of returning an empty list.

## Parameters

### solids

- **Description**: One or more Solid objects or sequences of Solid. Nested sequences are flattened before processing.

### clean

- **Description**: When True (the default) the faces and edges the intersection leaves split are unified, as union does: a cylinder wall cut along its seam stays one face, so a later fillet or chamfer of its edges works. False keeps the raw kernel result.

## Returns

Solid: The overlap region as a single solid.

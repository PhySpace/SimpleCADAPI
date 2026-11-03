# inspect_body_overlaps_rlist

## API Definition

```python
def inspect_body_overlaps_rlist(part: 'Part', *, min_volume_mm3: 'float' = 1e-06) -> 'list[BodyOverlap]'
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import inspect_body_overlaps_rlist`

## Description

List the pairs of bodies of a Part that share volume.

Overlapping bodies are allowed (a Part does not fuse them), but mass counts the
shared volume once per body and STEP holds both copies. Bodies that only touch
(a face, an edge or a point in common) do not overlap.

``scad.inspect_body_overlaps_rlist(case)`` before export. Building the part's
definition (a notebook run, ``@part``, a package) warns with ``BodyOverlapWarning``
for the same pairs.

## Parameters

### part

- **Description**: The Part to inspect; a one-body Part has no overlaps.

### min_volume_mm3

- **Description**: Shared volume below which a pair is not reported.

## Returns

list[BodyOverlap]: ``(first, second, volume_mm3)`` per overlapping pair, in body order.

## Raises

- **SimpleCADError**: The value is not a Part.

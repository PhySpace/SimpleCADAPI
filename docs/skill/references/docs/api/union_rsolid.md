# union_rsolid

## API Definition

```python
def union_rsolid(*solids, clean=True, glue=False, tol=None, tracking_policy='full')
```

*Source: operators/boolean.py*

## Import Surface

- top-level: `from simplecadapi import union_rsolid`

## Description

Compute the boolean union and return one manifold solid.

Face-area contact and positive-volume overlap can produce one solid without
artificial embedding. Edge-only, vertex-only, and point/curve tangencies
are non-manifold connections and cannot satisfy the one-Solid contract.

``glue`` is an OCC optimization for compatible touching or coincident
topology, not a geometry repair switch. If the optimized pass does not
return one solid, SimpleCAD automatically retries the normal fuse algorithm.

Accepts standalone `Solid` objects, lists of `Solid`, and nested sequences,
but always returns exactly one `Solid`. If the kernel cannot produce
exactly one solid result, the API raises a clear error instead of
returning multiple pieces.

## Parameters

### solids

- **Description**: One or more Solid objects or sequences of Solid. Nested sequences are flattened before processing.

### clean

- **Description**: Unify same-domain faces and remove splitter edges when possible.

### glue

- **Description**: Try OCC glue optimization first, then fall back to normal fuse if necessary. Defaults to False.

### tol

- **Type**: `Optional finite non-negative fuzzy-boolean tolerance used by OCC. It`
- **Description**: may intentionally bridge a small gap but cannot make a non-manifold point or edge contact into a valid solid.

### tracking_policy

- **Description**: FULL computes topology history and lineage. GRAPH keeps the replayable operation node without computing a TopoDelta.

## Returns

Solid: The merged union result.

## Examples

```python
body = make_box_rsolid(10, 4, 4, bottom_face_center=(0, 0, 0))
rib = make_box_rsolid(2, 4, 4, bottom_face_center=(4, 0, 0))
merged = union_rsolid(body, rib)
print(merged.get_volume())
```

# offset_rsolid

## API Definition

```python
def offset_rsolid(solid: Solid, amount: ScalarLike, openings: Sequence[Face] | ShapeSelector = (), *, tolerance: float = 0.0001, kind: str = 'ARC') -> Solid
```

*Source: operators/deformation.py*

## Import Surface

- top-level: `from simplecadapi import offset_rsolid`

## Description

Offset a solid outward (positive) or inward (negative).

The amount must be finite and nonzero. Faces passed as ``openings`` form an
open shell; with no openings the result is the closed offset solid. The
join ``kind`` is ``ARC`` or ``INTERSECTION``. Invalid kernel results raise
an error. The operation is recorded as ``make_offset_rsolid`` with explicit
face selections; topology tag lineage is conservatively partial.
``shell_rsolid`` keeps its own contract (a positive inward wall thickness);
this one supports both signs.

## Parameters

### solid

- **Description**: The solid to offset.

### amount

- **Description**: Offset distance; positive outward, negative inward.

### openings

- **Description**: Faces of ``solid`` (or a QL selector) left open.

### tolerance

- **Description**: Kernel tolerance of the offset.

### kind

- **Description**: Join type, ``"ARC"`` or ``"INTERSECTION"``.

## Returns

The offset solid.

## Raises

- **ValueError**: ``amount`` is zero or not finite, ``tolerance`` is not finite and positive, ``kind`` is unknown, ``openings`` do not select faces, or the kernel produced an invalid result.

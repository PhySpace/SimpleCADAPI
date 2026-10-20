# sweep_multisection_rsolid

## API Definition

```python
def sweep_multisection_rsolid(profiles: Sequence[Face | Wire], path: Wire, is_frenet: bool = False, binormal: Sequence[float] | Wire | None = None) -> Solid
```

*Source: operators/section_features.py*

## Import Surface

- top-level: `from simplecadapi import sweep_multisection_rsolid`

## Description

Sweep through explicit ordered sections along a continuous path.

At least two ordered sections are needed. Face sections supply their outer
wire, matching build123d's multi-section sweep contract. ``binormal`` is an
optional direction vector or an auxiliary spine. The kernel must produce
one valid solid. Every section and the path are recorded as inputs of
``make_sweep_multisection_rsolid``, so model JSON preserves the
construction.

## Parameters

### profiles

- **Description**: Ordered section faces or wires (at least two).

### path

- **Description**: The continuous path wire.

### is_frenet

- **Description**: Use the Frenet frame along the path.

### binormal

- **Description**: A direction, or an auxiliary spine wire, that fixes the section orientation.

## Returns

The swept solid.

## Raises

- **TypeError**: A section is neither a Face nor a Wire.
- **ValueError**: Fewer than two sections, a zero ``binormal`` direction, or the kernel could not make a solid.

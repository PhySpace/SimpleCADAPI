# extrude_taper_rsolid

## API Definition

```python
def extrude_taper_rsolid(profile: Face, vector: Sequence[float], taper: float, flip_inner: bool = True) -> Solid
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import extrude_taper_rsolid`

## Description

Extrude a planar sketch face by a vector, with a taper in degrees.

The vector is nonzero and in current coordinate-system coordinates. The
finite taper angle lies strictly between -90 and 90; a positive taper
shrinks the outer section, and inner loops taper the opposite way when
``flip_inner`` is true. An analytic draft prism is used where applicable
and exact offset sections with lofts otherwise. Collapsed loops and invalid
topology raise errors. The operation is recorded as
``make_extrude_taper_rsolid`` for replay.

## Parameters

### profile

- **Description**: The planar face to extrude.

### vector

- **Description**: Extrusion vector (nonzero).

### taper

- **Description**: Taper angle in degrees, strictly between -90 and 90.

### flip_inner

- **Description**: Taper inner loops in the opposite direction.

## Returns

The tapered solid.

## Raises

- **ValueError**: A zero vector, an out-of-range taper, a nonplanar profile, collapsed loops or an invalid result.

# extrude_taper_rsolid

## API Definition

```python
def extrude_taper_rsolid(profile: Face, vector: Sequence[float], taper: float, flip_inner: bool = True) -> Solid
```

*Source: operators/section_features.py*

## Import Surface

- top-level: `from simplecadapi import extrude_taper_rsolid`

## Description

Extrude a planar face by a vector, with a taper in degrees.

Positive taper shrinks the outer section. Inner loops optionally taper in
the opposite direction. Analytic draft prisms are retained where valid;
other orientations/holes use exact offset wire sections and solid lofts.

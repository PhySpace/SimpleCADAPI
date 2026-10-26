# loft_multisection_rsolid

## API Definition

```python
def loft_multisection_rsolid(profiles: Sequence[Face | Wire], path: Wire, is_frenet: bool = False, binormal: Sequence[float] | Wire | None = None) -> Solid
```

*Source: operators/section_features.py*

## Import Surface

- top-level: `from simplecadapi import loft_multisection_rsolid`

## Description

Loft ordered, varying sections along a continuous path.

Face sections use their outer boundary. Binormal may be a direction vector
or one auxiliary spine. Explicit endpoint continuity and multiple boundary
rails are not supported. Each supplied section, path, and auxiliary spine
remains a graph input for replay.

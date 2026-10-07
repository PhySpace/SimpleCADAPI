# sweep_multisection_rsolid

```python
def sweep_multisection_rsolid(profiles: Sequence[Face | Wire], path: Wire,
    is_frenet: bool = False, binormal: Sequence[float] | Wire | None = None) -> Solid
```

Sweep through at least two ordered sections along a continuous path. Face
sections supply their outer wire, matching build123d's multi-section sweep
contract. Binormal is an optional direction or auxiliary spine. The kernel
must produce one valid solid. Every section and path is recorded as an input
of `make_sweep_multisection_rsolid`, so model JSON preserves the construction.

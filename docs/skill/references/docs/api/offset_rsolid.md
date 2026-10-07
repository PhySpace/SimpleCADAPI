# offset_rsolid

```python
def offset_rsolid(solid: Solid, amount: ScalarLike,
    openings: Sequence[Face] | ShapeSelector = (), *,
    tolerance: float = 1e-4, kind: str = "ARC") -> Solid
```

Positive `amount` offsets outward; negative offsets inward. The amount must
be finite and nonzero. QL-selected `openings` form an open shell. With no
openings, produce a closed offset solid. Join `kind` is `ARC` or
`INTERSECTION`. Invalid kernel results raise an error. Records a replayable
`make_offset_rsolid` node with explicit face selections; topology tag lineage
is conservatively partial. `shell_rsolid` retains its existing positive
inward wall-thickness contract.

# scale_rsolid

```python
def scale_rsolid(solid: Solid, factors: Sequence[float], center: Sequence[float] = (0, 0, 0)) -> Solid
```

Scale a solid along the current coordinate system's axes about `center`.
The three factors must be finite and nonzero. Uniform scaling preserves
analytic curves and surfaces; nonuniform scaling uses the CAD kernel's
general affine transform. The source stays unchanged. Records a replayable
`make_scale_rsolid` operation. Topology tag lineage is conservatively partial.

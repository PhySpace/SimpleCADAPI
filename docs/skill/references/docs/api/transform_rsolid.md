# transform_rsolid

```python
def transform_rsolid(solid: Solid, matrix: Sequence[Sequence[float]]) -> Solid
```

Apply a finite nonsingular 4x4 affine matrix in the current coordinate system,
including shear, reflection and nonuniform scale. Reject perspective and
singular matrices. Input geometry stays unchanged. Records a replayable
`make_transform_rsolid` operation; topology tag lineage is partial.

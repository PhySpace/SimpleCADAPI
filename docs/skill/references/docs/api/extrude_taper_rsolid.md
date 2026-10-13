# extrude_taper_rsolid

```python
def extrude_taper_rsolid(profile: Face, vector: Sequence[float],
    taper: float, flip_inner: bool = True) -> Solid
```

Extrude a planar sketch face by a nonzero vector, in current coordinate-system
coordinates. The finite taper angle is in degrees and must lie strictly between
-90 and 90. Positive taper shrinks the outer section; inner loops taper in the
opposite direction when `flip_inner=True`. Uses an analytic draft prism where
applicable and exact offset sections with lofts otherwise. Raises on collapsed
loops or invalid topology. Records `make_extrude_taper_rsolid` for replay.

# make_faces_from_sketch_rfacelist

## API Definition

```python
def make_faces_from_sketch_rfacelist(sketch, profiles=None, *, require_fully_constrained=False, strict=True, tolerance=1e-07, max_iterations=80)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import make_faces_from_sketch_rfacelist`

## Description

Make one face per region of the sketch: a closed outer loop minus the loops directly inside it.

Holes come by themselves: a loop inside an outer loop is a hole of that region, and a loop inside a hole is the
outer loop of another region (``inspect_sketch_rsketchprofiles`` reports each closed profile's ``parent`` and
``depth`` and the ``regions`` as ``{"outer": i, "holes": [...]}``). ``profiles`` names the regions to make by their
outer profile (an index of ``inspect_sketch_rsketchprofiles`` or a profile id); leave it out for every region, in
profile order. An open chain, a hole or an unknown profile is refused by name.

Returns the faces as ``scad.Pieces`` (a list) in that order: a one-shape operation such as ``extrude_rsolid`` runs on
every face and returns ``Pieces`` (one solid per region; ``union_rsolid`` joins them, ``make_part_rpart`` makes them
bodies). Each face is recorded as ``make_face_from_sketch_rface(sketch, outer, inner_profiles=holes)`` and replays
from model JSON.

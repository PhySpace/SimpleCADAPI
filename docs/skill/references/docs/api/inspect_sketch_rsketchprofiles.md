# inspect_sketch_rsketchprofiles

## API Definition

```python
def inspect_sketch_rsketchprofiles(sketch, *, strict=True, tolerance=1e-07, max_iterations=80)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import inspect_sketch_rsketchprofiles`

## Description

List the profiles a sketch offers: the indices ``make_face_from_sketch_rface`` and ``make_wire_from_sketch_rwire`` take.

Returns ``{"profiles": [...], "unusable": [...]}``. Each profile is ``{index, id, kind, closed, entity_ids, point_ids, reversed}``: ``kind`` is ``circle``, ``edge_loop`` or ``edge_chain``; ``entity_ids`` are in walking order and ``reversed`` says which edges are walked from end to start. ``unusable`` words why an edge set is no profile (a branch point carrying more than two edges, for one). A free circle is a profile; a loop is a connected set of edges whose points each carry exactly two. Not recorded in the graph; pass ``strict=False`` for a sketch that does not solve cleanly.

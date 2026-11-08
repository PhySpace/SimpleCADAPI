# diff_sketch_rsketchdiff

## API Definition

```python
def diff_sketch_rsketchdiff(before, after)
```

*Source: operators/sketch.py*

## Import Surface

- top-level: `from simplecadapi import diff_sketch_rsketchdiff`

## Description

Report what an edit did: entity and constraint ids created, removed or changed between two sketches.

Returns a dict with ``created``, ``removed``, ``changed`` (entity ids, points included) and
``created_constraints``, ``removed_constraints``, ``changed_constraints``. Not recorded in the graph.

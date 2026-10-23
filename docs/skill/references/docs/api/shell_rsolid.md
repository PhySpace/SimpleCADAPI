# shell_rsolid

## API Definition

```python
def shell_rsolid(solid, faces_to_remove, thickness, *, result_tag=None, body_faces_tag=None, offset_faces_tag=None, closing_faces_tag=None, wall_edges_tag=None)
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import shell_rsolid`

## Description

Shell a solid, with optional kernel-role-based face tags.

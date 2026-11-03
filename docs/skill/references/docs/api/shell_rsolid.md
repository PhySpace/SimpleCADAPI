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

The kernel roles are ``shell.body_face`` (a face of the input that stays in
the result), ``shell.offset_face`` (the inner face it generates),
``shell.closing_descendant`` (what is left of a removed face: the rim) and
``shell.wall`` (the edges that become the walls of an opening).
``body_faces_tag``, ``offset_faces_tag``, ``closing_faces_tag`` and
``wall_edges_tag`` tag exactly the entities with those roles.

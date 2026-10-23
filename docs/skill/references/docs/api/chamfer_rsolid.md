# chamfer_rsolid

## API Definition

```python
def chamfer_rsolid(solid, edges, distance, *, angle=None, reference_direction=None, result_tag=None, generated_faces_tag=None)
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import chamfer_rsolid`

## Description

Apply chamfers, with optional tagging of kernel-proven patch faces.

Without ``angle`` the chamfer is symmetric (both legs equal
``distance``). With ``angle`` — measured in degrees between the chamfer
face and the reference face — the chamfer is asymmetric with the second
leg at ``distance * tan(angle)`` on the non-reference side;
``reference_direction`` picks, per edge, the adjacent face whose outward
normal best matches it as the reference face.

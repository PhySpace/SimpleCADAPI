# twisted_sweep_rsolid

## API Definition

```python
def twisted_sweep_rsolid(profile, distance, twist_angle, axis=(0, 0, 1), origin=(0, 0, 0), *, guide_radius=1.0, tag_prefix=None, result_tag=None, start_face_tag=None, end_face_tag=None, side_faces_tag=None)
```

*Source: operators/features.py*

## Import Surface

- top-level: `from simplecadapi import twisted_sweep_rsolid`

## Description

Sweep a planar profile along a straight axis with linear rotation.

``twist_angle`` is the signed total rotation in degrees. The operation uses
a cylindrical auxiliary spine to define a continuous rotation law, yielding
one continuous side face per profile edge instead of a segmented ruled loft.

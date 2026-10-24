# make_cylinder_rsolid

## API Definition

```python
def make_cylinder_rsolid(radius, height, bottom_face_center=(0, 0, 0), axis=(0, 0, 1), *, tag_prefix=None, result_tag=None, start_face_tag=None, end_face_tag=None, side_face_tag=None, start_edge_tag=None, end_edge_tag=None, seam_edge_tag=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_cylinder_rsolid`

## Description

Create a cylinder with native kernel-backed Face and Edge topology tags.

The cylinder extends ``height`` along ``axis`` from the bottom face.

## Parameters

### radius

- **Description**: Cylinder radius.

### height

- **Description**: Cylinder length along ``axis``.

### bottom_face_center

- **Description**: Geometric center of the cylinder's bottom (start) face in the current coordinate system; the solid extends the full ``height`` along ``axis`` from this point.

### axis

- **Description**: Direction of the cylinder axis in the current coordinate system.

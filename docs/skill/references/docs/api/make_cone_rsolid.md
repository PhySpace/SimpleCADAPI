# make_cone_rsolid

## API Definition

```python
def make_cone_rsolid(bottom_radius, height, top_radius=0.0, bottom_face_center=(0, 0, 0), axis=(0, 0, 1), *, tag_prefix=None, result_tag=None, start_face_tag=None, end_face_tag=None, side_face_tag=None, start_edge_tag=None, end_edge_tag=None, seam_edge_tag=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_cone_rsolid`

## Description

Create a cone or frustum with native kernel-backed topology tags.

The solid extends ``height`` along ``axis`` from the bottom face,
tapering from ``bottom_radius`` to ``top_radius`` (a cone when
``top_radius`` is 0).

## Parameters

### bottom_radius

- **Description**: Radius of the bottom (start) face.

### height

- **Description**: Frustum length along ``axis``.

### top_radius

- **Description**: Radius of the top face; 0 produces a cone.

### bottom_face_center

- **Description**: Geometric center of the bottom (start) face in the current coordinate system; the solid extends the full ``height`` along ``axis`` from this point.

### axis

- **Description**: Direction of the frustum axis in the current coordinate system.

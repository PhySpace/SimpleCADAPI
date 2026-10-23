# make_box_rsolid

## API Definition

```python
def make_box_rsolid(width, height, depth, bottom_face_center=(0, 0, 0), *, tag_prefix=None, result_tag=None, bottom_face_tag=None, top_face_tag=None, front_face_tag=None, back_face_tag=None, left_face_tag=None, right_face_tag=None)
```

*Source: operators/geometry.py*

## Import Surface

- top-level: `from simplecadapi import make_box_rsolid`

## Description

Create a box with native kernel-backed Face topology tags.

The box extends ``depth`` along the current coordinate-system z_axis
starting at the bottom face; ``width`` spans the x_axis and ``height``
spans the y_axis.

## Parameters

### width

- **Description**: Box size along the current coordinate-system x_axis.

### height

- **Description**: Box size along the current coordinate-system y_axis.

### depth

- **Description**: Box size along the current coordinate-system z_axis.

### bottom_face_center

- **Description**: Geometric center of the box's bottom face in the current coordinate system. The box is centered on this point along x and y (it spans width/2 and height/2 to each side) and extends the full ``depth`` upward along the z_axis from this point's height. It is not a corner; to build a box occupying x in [0, w], pass ``bottom_face_center=(w/2, h/2, z0)``.

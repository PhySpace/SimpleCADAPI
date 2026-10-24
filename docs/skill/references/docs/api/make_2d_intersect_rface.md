# make_2d_intersect_rface

## API Definition

```python
def make_2d_intersect_rface(face_a, face_b)
```

*Source: operators/boolean.py*

## Import Surface

- top-level: `from simplecadapi import make_2d_intersect_rface`

## Description

Compute the boolean intersection of two 2D faces.

## Parameters

### face_a

- **Type**: `Face`
- **Description**: First face.

### face_b

- **Type**: `Face`
- **Description**: Second face.

## Returns

-------
Face
The overlapping region of the two faces.

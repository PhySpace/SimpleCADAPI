# make_2d_union_rface

## API Definition

```python
def make_2d_union_rface(face_a, face_b)
```

*Source: operators/boolean.py*

## Import Surface

- top-level: `from simplecadapi import make_2d_union_rface`

## Description

Compute the boolean union of two 2D faces.

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
The merged face.  Both inputs must overlap or touch so that the
result is a single connected face.

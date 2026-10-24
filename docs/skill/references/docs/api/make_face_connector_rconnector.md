# make_face_connector_rconnector

## API Definition

```python
def make_face_connector_rconnector(connector_id, face, name=None, flip=False)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import make_face_connector_rconnector`

## Description

Create a connector anchored to a Face.

Z axis follows the face normal; origin is the face center.
Set flip=True to negate the Z axis (point it opposite to the normal).

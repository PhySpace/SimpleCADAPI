# GeometryRef

## Class Definition

```python
class GeometryRef(kind, source_node_id, geo_selector, flip=False)
```

*Source: product/connector.py*

## Import Surface

- top-level: `from simplecadapi import GeometryRef`

## Description

Serializable reference to a sub-shape selected via QL.

Wraps the geo_selector fingerprint + source graph node id so the
exact sub-element (Face/Edge/Vertex) can be re-resolved at translation
time or during constraint solving. When flip is True, the derived
placement Z axis is negated.

# make_placement_connector_rconnector

## API Definition

```python
def make_placement_connector_rconnector(connector_id, placement, name=None)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import make_placement_connector_rconnector`

## Description

Create a connector anchored to an explicit local placement frame.

Use this when a datum should be defined by a stable coordinate frame
instead of a selected BREP face, edge, or vertex.

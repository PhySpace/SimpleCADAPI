# make_edge_connector_rconnector

## API Definition

```python
def make_edge_connector_rconnector(connector_id, edge, name=None, flip=False)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import make_edge_connector_rconnector`

## Description

Create a connector anchored to an Edge.

Z axis follows the edge direction (start->end); origin is the edge midpoint.
Set flip=True to negate the Z axis.

# make_vertex_connector_rconnector

## API Definition

```python
def make_vertex_connector_rconnector(connector_id, vertex, name=None, flip=False)
```

*Source: operators/product.py*

## Import Surface

- top-level: `from simplecadapi import make_vertex_connector_rconnector`

## Description

Create a connector anchored to a Vertex.

Origin is the vertex point; axes are identity.
flip has no effect on vertex connectors (no direction).

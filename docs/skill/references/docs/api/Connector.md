# Connector

## Class Definition

```python
class Connector(connector_id, geometry_ref=None, name=None, anchor=None)
```

*Source: product/connector.py*

## Import Surface

- top-level: `from simplecadapi import Connector`

## Description

Semantic datum frame anchored by geometry or an explicit placement.

Assembly public interfaces reference existing component connectors instead
of cloning connectors into the Assembly.

# register_property_resolver

## API Definition

```python
def register_property_resolver(prefix: object, resolver: object) -> None
```

*Source: ql.py*

## Import Surface

- submodule: `from simplecadapi.ql import register_property_resolver` or `simplecadapi.ql.register_property_resolver`

## Description

Answer property paths that start with `prefix`: resolver(shape, path) returns a value or ql.MISSING.

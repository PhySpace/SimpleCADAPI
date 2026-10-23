# value

## API Definition

```python
def value(path, default=None)
```

*Source: ql.py*

## Import Surface

- submodule: `from simplecadapi.ql import value` or `simplecadapi.ql.value`

## Description

Build a value key extractor for ordering and projection in QL.

## Parameters

### path

- **Description**: Property or metadata path to resolve.

### default

- **Description**: Fallback value when the path is missing.

## Returns

Serializable key function for `Query.order_by(...)`.

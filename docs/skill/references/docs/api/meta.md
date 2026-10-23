# meta

## API Definition

```python
def meta(path, op, value_)
```

*Source: ql.py*

## Import Surface

- submodule: `from simplecadapi.ql import meta` or `simplecadapi.ql.meta`

## Description

Build a metadata comparison predicate for QL filtering.

## Parameters

### path

- **Description**: Dot-separated metadata path.

### op

- **Description**: Comparison operator such as `==`, `!=`, `>`, `>=`, `<`, or `<=`.

### value_

- **Description**: Comparison value.

## Returns

Serializable predicate that compares metadata values.

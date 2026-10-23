# tag

## API Definition

```python
def tag(pattern, scope='effective')
```

*Source: ql.py*

## Import Surface

- submodule: `from simplecadapi.ql import tag` or `simplecadapi.ql.tag`

## Description

Build a tag predicate for QL filtering.

## Parameters

### pattern

- **Description**: Exact tag string or a trailing `*` prefix match.

### scope

- **Description**: One of ``local``, ``inherited``, ``effective``, or ``lineage``.

## Returns

Serializable predicate that can be used in `Query.where(...)`.

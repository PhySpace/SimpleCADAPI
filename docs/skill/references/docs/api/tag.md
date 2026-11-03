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

Tags are a view over the recorded history: a tag assigned in a
``GraphSession`` reaches every entity its target became through later
operations (a face cut in two keeps it on both pieces), as its lineage
policy allows. ``local`` is what the entity itself stores, ``inherited``
what containing entities pass down, ``lineage`` what the history carries,
and ``effective`` (the default) all three.

## Parameters

### pattern

- **Description**: Exact tag string or a trailing `*` prefix match.

### scope

- **Description**: One of ``local``, ``inherited``, ``effective``, or ``lineage``.

## Returns

Serializable predicate that can be used in `Query.where(...)`.

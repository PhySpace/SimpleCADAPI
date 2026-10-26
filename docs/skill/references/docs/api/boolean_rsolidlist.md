# boolean_rsolidlist

## API Definition

```python
def boolean_rsolidlist(left: Sequence[Solid], right: Sequence[Solid], operation: str) -> list[Solid]
```

*Source: operators/deformation.py*

## Import Surface

- top-level: `from simplecadapi import boolean_rsolidlist`

## Description

Apply a set boolean to two body groups, retaining every result solid.

Members of each group are a geometric set. Unlike single-solid booleans,
a cut or intersection may return several solids or an empty list.
Topology lineage is partial; the ordered inputs and all output slots are
recorded so downstream features can replay the same geometry.

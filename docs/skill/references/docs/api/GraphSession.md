# GraphSession

## Class Definition

```python
class GraphSession(graph_id: Optional[str] = None, *, allow_external_definitions: bool = False, namespace: Optional[str] = None, shared_lineage: bool = False)
```

*Source: recording/graph.py*

## Import Surface

- top-level: `from simplecadapi import GraphSession`

## Description

Context manager that records CAD operations into a DAG.

with GraphSession() as session:
n1 = record_operation(
"make_line_redge", {"start": (0, 0, 0), "end": (1, 0, 0)}
)
n2 = record_operation(
"make_line_redge", {"start": (1, 0, 0), "end": (1, 1, 0)}
)
record_operation(
"make_wire_from_edges_rwire", {"edge_count": 2}, inputs=[n1, n2]
)

# Access the graph after the session
print(session.graph.topological_order())

## Parameters

### graph_id

- **Description**: Id of the recorded graph (random when omitted).

### allow_external_definitions

- **Description**: Let built ``Part``/``Assembly`` values that carry their own definition enter as ``reference_definition`` nodes instead of being rejected.

### namespace

- **Description**: Prefix for every node and object id this session allocates, as in ``OperationGraph(namespace=...)``.

### shared_lineage

- **Description**: Accept values recorded by other sessions with the same ``graph_id`` by adopting their nodes, as in ``OperationGraph.adopt``. Notebook cell sessions use this; every other session only accepts nodes its own graph owns.

"""The operation nodes behind a cell's values, kept next to its cache entry (native backend).

A Python value carries the nodes it was recorded by; pickling it takes the
nodes along.  A native value carries only the id of its node, so the nodes of
a cell are written beside the cell's entry (``lineage.<cell key>``) and put
back into the process-wide node registry when the cell is restored.  Cells
restore in dependency order, so the nodes a cell's own nodes are built on are
registered by then.

A record belongs to one cache *entry* of the cell, not to the cell: one cell has an entry for every combination of the
values it reads (a child notebook run with other overrides, a parameter changed in the editor), all under one digest
directory, and the nodes of two entries carry the same ids (the ids count from the cell's code) with other contents.
The record is named by the entry's key, so restoring an entry registers the nodes that entry's values name.
"""

from __future__ import annotations

import pickle
import zlib
from pathlib import Path
from typing import Any

_PREFIX = "lineage."
_EXTERNAL = "ref_"


def _own(node_id: str, namespace: str) -> bool:
    return node_id.startswith(namespace + "_") or node_id.startswith(_EXTERNAL)


def _record(directory: Path, cell_id: str, key: str | None) -> Path:
    return directory / (f"{_PREFIX}{cell_id}" if key is None else f"{_PREFIX}{cell_id}.{key}")


def save(directory: Path, cell_id: str, session: Any, key: str | None = None) -> None:
    """Write the nodes *session* recorded (not the ones it adopted) beside the cell's entry *key*."""

    namespace = session.graph.namespace
    payload = session.graph.to_dict()
    nodes = [node for node in payload["nodes"] if _own(node["node_id"], namespace)]
    kept = {node["node_id"] for node in nodes}
    document = {
        "graph_id": payload["graph_id"],
        "nodes": nodes,
        "edges": [edge for edge in payload["edges"] if edge[0] in kept and edge[1] in kept],
        "expressions": session.expression_graph.to_dict(),
        "frames": session.frame_graph.to_dict(),
    }
    directory.mkdir(parents=True, exist_ok=True)
    target = _record(directory, cell_id, key)
    partial = target.with_suffix(".part")
    partial.write_bytes(zlib.compress(pickle.dumps(document, protocol=5), 1))
    partial.replace(target)


def load(directory: Path, cell_id: str, graph_id: str | None = None, key: str | None = None) -> bool:
    """Register the nodes saved for the cell's entry *key*; ``False`` when there is no record.

    With *graph_id*, a record of another graph is no entry either: its nodes would be registered under that graph,
    and the values restored beside it (which name their nodes by this run's graph) would find none.
    """

    import simplecadapi._cpp as native

    target = _record(directory, cell_id, key)
    try:
        document = pickle.loads(zlib.decompress(target.read_bytes()))
    except OSError:
        return False
    if graph_id is not None and document.get("graph_id") != graph_id:
        return False
    graph = native.OperationGraph.from_dict(
        {
            "graph_id": document["graph_id"],
            "nodes": document["nodes"],
            "edges": document["edges"],
        },
        strict=False,
        expression_graph=native.ExpressionGraph.from_dict(document["expressions"]),
        frame_graph=native.FrameGraph.from_dict(document["frames"]),
    )
    native.register_graph_nodes(graph)
    return True

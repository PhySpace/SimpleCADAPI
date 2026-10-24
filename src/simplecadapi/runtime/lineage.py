"""The operation nodes behind a cell's values, kept next to its cache entry (native backend).

A Python value carries the nodes it was recorded by; pickling it takes the
nodes along.  A native value carries only the id of its node, so the nodes of
a cell are written beside the cell's entry (``lineage.<cell key>``) and put
back into the process-wide node registry when the cell is restored.  Cells
restore in dependency order, so the nodes a cell's own nodes are built on are
registered by then.
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


def save(directory: Path, cell_id: str, session: Any) -> None:
    """Write the nodes *session* recorded (not the ones it adopted) beside the cell's entry."""

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
    target = directory / f"{_PREFIX}{cell_id}"
    partial = target.with_suffix(".part")
    partial.write_bytes(zlib.compress(pickle.dumps(document, protocol=5), 1))
    partial.replace(target)


def load(directory: Path, cell_id: str) -> bool:
    """Register the nodes saved for the cell; ``False`` when there is no entry."""

    import simplecadapi._cpp as native

    target = directory / f"{_PREFIX}{cell_id}"
    try:
        document = pickle.loads(zlib.decompress(target.read_bytes()))
    except OSError:
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

"""``OperationNode`` on the native backend: the dataclass behaviour the notebook runtime relies on.

The node is a C++ value.  What Python code does with it besides reading it -- build one by hand,
``dataclasses.replace`` it, pickle it (marimo pickles every cell variable separately), deep-copy it -- is
written here against the node's own fields, as the SDK's frozen dataclass does:

* pickling and deep copy walk the upstream closure iteratively (a modelling history is thousands of nodes
  deep: recursion would overflow) and write each node as one flat record that names its inputs by id;
* nodes restored from pickles are shared by ``(graph_id, node_id)``: two variables that shared a node before
  pickling share one object after loading, and a node whose input was replaced by a newer version is a new
  node (stale lineage).
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any, Dict, Optional, Tuple

# The SDK dataclass's fields, in its order.
_FIELD_NAMES: Tuple[str, ...] = (
    "node_id",
    "op",
    "params",
    "param_exprs",
    "inputs",
    "context",
    "output_count",
    "semantic_delta",
    "topo_delta",
    "tags",
    "graph_id",
    "source",
    "expressions",
    "frame",
)


@dataclasses.dataclass(frozen=True)
class _Fields:
    """Only for its ``__dataclass_fields__`` (``dataclasses.replace`` and ``fields`` read them off the class)."""

    node_id: str
    op: str
    params: Any = None
    param_exprs: Any = None
    inputs: Any = ()
    context: Any = None
    output_count: int = 1
    semantic_delta: Any = None
    topo_delta: Any = None
    tags: Any = frozenset()
    graph_id: Optional[str] = None
    source: Any = None
    expressions: Any = dataclasses.field(default=(), compare=False, repr=False)
    frame: Any = dataclasses.field(default=None, compare=False, repr=False)


def install(nat: Any) -> None:
    node_class = nat.OperationNode
    original_init = node_class.__init__

    def build(
        self: Any,
        node_id: str,
        op: str,
        params: Any = None,
        param_exprs: Any = None,
        inputs: Any = None,
        context: Any = None,
        output_count: int = 1,
        semantic_delta: Any = None,
        topo_delta: Any = None,
        tags: Any = None,
        graph_id: Any = None,
        source: Any = None,
        expressions: Any = None,
        frame: Any = None,
    ) -> None:
        if topo_delta is not None and not isinstance(topo_delta, dict):
            from ..topology.model import topo_delta_to_dict

            topo_delta = topo_delta_to_dict(topo_delta)
        original_init(
            self, node_id, op, params, param_exprs, inputs, context, output_count, semantic_delta, topo_delta,
            tags, graph_id, source, expressions, frame,
        )

    node_class.__init__ = build
    node_class.__dataclass_fields__ = _Fields.__dataclass_fields__
    node_class.__dataclass_params__ = _Fields.__dataclass_params__
    node_class.__match_args__ = _FIELD_NAMES

    def input_ids(node: Any) -> Tuple[str, ...]:
        return tuple(item.node_id for item in node.inputs)

    def closure(root: Any, stop: Any = None) -> list:
        """The node and everything upstream of it, inputs first (iterative; one entry per id)."""

        order: list = []
        seen: Dict[str, Any] = {}
        stack = [(root, False)]
        while stack:
            node, inputs_done = stack.pop()
            if inputs_done:
                order.append(node)
                continue
            known = seen.get(node.node_id)
            if known is not None:
                if not nat.same_node_content(known, node):
                    raise nat.StaleLineageError(node.node_id) if hasattr(nat, "StaleLineageError") else ValueError(
                        f"node '{node.node_id}' exists in two different versions (stale lineage)"
                    )
                continue
            if stop is not None and stop(node):
                continue
            seen[node.node_id] = node
            stack.append((node, True))
            stack.extend((item, False) for item in reversed(node.inputs))
        return order

    def record(node: Any) -> Tuple[Any, ...]:
        return tuple(input_ids(node) if name == "inputs" else getattr(node, name) for name in _FIELD_NAMES)

    def reduce(self: Any) -> Tuple[Any, ...]:
        return (_restore, (_FIELD_NAMES, tuple(record(node) for node in closure(self))))

    def deepcopy(self: Any, memo: Dict[int, Any]) -> Any:
        copies: Dict[str, Any] = {}

        def copied(node: Any) -> Any:
            done = memo.get(id(node))
            return done if done is not None else copies[node.node_id]

        for node in closure(self, stop=lambda item: id(item) in memo):
            state = {
                name: (tuple(copied(item) for item in node.inputs) if name == "inputs"
                       else copy.deepcopy(getattr(node, name), memo))
                for name in _FIELD_NAMES
            }
            duplicate = node_class(**state)
            memo[id(node)] = copies[node.node_id] = duplicate
        return memo[id(self)]

    node_class.__reduce__ = reduce
    node_class.__deepcopy__ = deepcopy
    _install_restore(nat)
    _install_graph(nat, deepcopy)
    _install_small_values(nat)


def _install_graph(nat: Any, node_deepcopy: Any) -> None:
    """``OperationGraph`` pickles and deep-copies as its graph id, namespace and nodes (inputs first)."""

    graph_class = nat.OperationGraph

    def graph_reduce(self: Any) -> Tuple[Any, ...]:
        return (_restore_graph, (self.graph_id, self.namespace, tuple(self.topological_order())))

    def graph_deepcopy(self: Any, memo: Dict[int, Any]) -> Any:
        duplicate = graph_class(self.graph_id, namespace=self.namespace)
        memo[id(self)] = duplicate
        for node in self.topological_order():
            duplicate.adopt(node_deepcopy(node, memo) if id(node) not in memo else memo[id(node)])
        return duplicate

    graph_class.__reduce__ = graph_reduce
    graph_class.__deepcopy__ = graph_deepcopy


def _restore_graph(graph_id: Optional[str], namespace: Optional[str], nodes: Tuple[Any, ...]) -> Any:
    graph = _graph_class(graph_id, namespace=namespace)
    for node in nodes:
        graph.adopt(node)
    return graph


def _install_restore(nat: Any) -> None:
    global _node_class, _graph_class
    _node_class = nat.OperationNode
    _graph_class = nat.OperationGraph


_node_class: Any = None
_graph_class: Any = None


def _share(node: Any) -> Any:
    """The live restored twin of *node*, or *node* registered as one (the registry is the C++ one)."""

    return _node_class._share_restored(node)


def _restore(field_names: Tuple[str, ...], records: Tuple[Tuple[Any, ...], ...]) -> Any:
    restored: Dict[str, Any] = {}
    node = None
    for entry in records:
        state = dict(zip(field_names, entry))
        state["inputs"] = tuple(restored[node_id] for node_id in state["inputs"])
        node = _share(_node_class(**state))
        restored[node.node_id] = node
    if node is None:
        raise ValueError("an operation node pickle holds no records")
    return node


def share_node(node: Any) -> Any:
    """The live twin of a node that came back from a pickle (or the node itself)."""

    return _share(node)


def _install_small_values(nat: Any) -> None:
    """Pickle of the values a node record holds besides plain data: rebuilt from their constructor arguments."""

    ref = nat.SemanticRef
    ref.__reduce__ = lambda self: (ref, (self.graph_id, self.node_id, self.entity_type, self.entity_id))

    delta = nat.SemanticDelta
    delta.__reduce__ = lambda self: (
        delta,
        (tuple(self.created), tuple(self.modified), tuple(self.deleted), dict(self.metadata)),
    )

    frame = nat.FrameNode
    frame.__reduce__ = lambda self: (
        frame,
        (self.frame_id, tuple(self.origin), tuple(self.x_axis), tuple(self.y_axis), tuple(self.z_axis),
         self.parent_frame_id, dict(self.metadata)),
    )

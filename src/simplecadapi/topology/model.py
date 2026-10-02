"""Topology tracking data models for recording CAD operations and their lineage.

These models form the foundation for:
- Tracking how topological entities (vertex/edge/wire/face/solid) change through operations
- Recording an operation DAG that can be serialized and replayed
- Providing stable references for auto-tagging and query-language integration
"""

from __future__ import annotations

import uuid
import weakref
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field, fields, replace
from enum import Enum, auto
from importlib import metadata as importlib_metadata
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
)

from ..recording.source_mapping import canonical_source_payload

if TYPE_CHECKING:
    from ..params.expr import ScalarExpr
    from ..params.frame import FrameNode

GRAPH_SCHEMA_VERSION = "2.0"


def _producer_version() -> str:
    try:
        return importlib_metadata.version("simplecadapi")
    except importlib_metadata.PackageNotFoundError:
        return "0+unknown"


def graph_capabilities_payload() -> Dict[str, Any]:
    return {
        "selection_ref_strategies": True,
        "geo_select_nodes": True,
        "selector_hint_fallback": True,
        "display_payload": True,
        "sketch_constraints": True,
        "sketch_solve_snapshots": True,
        "product_semantics": True,
        "assembly_graph": True,
        "topology_delta_summary": False,
        "topology_delta_entries": True,
        "durable_topology_parent_refs": True,
        "operation_output_roles": True,
        "scalar_field_graph": False,
        "expression_graph": True,
        "semantic_tag_bindings": True,
        "tag_binding_schema": "1.0",
        "source_mapping": True,
        "source_mapping_schema": "1.0",
    }


class TopoKind(Enum):
    """Type of topological entity."""

    VERTEX = auto()
    EDGE = auto()
    WIRE = auto()
    FACE = auto()
    SHELL = auto()
    SOLID = auto()
    COMPOUND = auto()


class TopoEvent(Enum):
    """What happened to a subshape during an operation."""

    PRESERVED = auto()  # Unchanged through the operation
    MODIFIED = auto()  # Modified (split, trimmed, re-faceted, etc.)
    GENERATED = auto()  # Newly created by the operation
    DELETED = auto()  # Removed from the result


@dataclass(frozen=True)
class TopoRef:
    """Stable reference to a subshape within a specific graph + node.

    Attributes:
        graph_id: Identifier of the parent graph this ref belongs to.
        node_id:  Identifier of the operation node that produced this subshape.
        output_slot: Index into the node's output list (0 for single-output ops).
        kind:     The topological kind (vertex/edge/wire/face/solid).
        topo_id:  An opaque string that identifies this particular subshape
                  within the node's output.  Exact format is implementation-
                  defined; it may be a sequential integer, a hash, etc.
    """

    graph_id: str
    node_id: str
    output_slot: int
    kind: TopoKind
    topo_id: str


@dataclass(frozen=True)
class SemanticRef:
    """Stable reference to a semantic model entity in the recorded graph."""

    graph_id: str
    node_id: str
    entity_type: str
    entity_id: str


def semantic_ref_to_dict(ref: SemanticRef) -> Dict[str, Any]:
    return {
        "graph_id": ref.graph_id,
        "node_id": ref.node_id,
        "entity_type": ref.entity_type,
        "entity_id": ref.entity_id,
    }


def semantic_ref_from_dict(data: Dict[str, Any]) -> SemanticRef:
    return SemanticRef(
        graph_id=str(data["graph_id"]),
        node_id=str(data["node_id"]),
        entity_type=str(data["entity_type"]),
        entity_id=str(data["entity_id"]),
    )


def semantic_delta_to_dict(delta: SemanticDelta) -> Dict[str, Any]:
    return {
        "created": [semantic_ref_to_dict(ref) for ref in delta.created],
        "modified": [semantic_ref_to_dict(ref) for ref in delta.modified],
        "deleted": [semantic_ref_to_dict(ref) for ref in delta.deleted],
        "metadata": dict(delta.metadata),
    }


def semantic_delta_from_dict(data: Dict[str, Any]) -> SemanticDelta:
    return SemanticDelta(
        created=tuple(semantic_ref_from_dict(item) for item in data.get("created", [])),
        modified=tuple(
            semantic_ref_from_dict(item) for item in data.get("modified", [])
        ),
        deleted=tuple(semantic_ref_from_dict(item) for item in data.get("deleted", [])),
        metadata=dict(data.get("metadata", {})),
    )


def topo_ref_to_dict(ref: TopoRef) -> Dict[str, Any]:
    """Serialize a TopoRef into a JSON-compatible dictionary."""

    return {
        "graph_id": ref.graph_id,
        "node_id": ref.node_id,
        "output_slot": ref.output_slot,
        "kind": ref.kind.name,
        "topo_id": ref.topo_id,
    }


def topo_ref_from_dict(data: Dict[str, Any]) -> TopoRef:
    """Reconstruct a TopoRef from serialized data."""

    return TopoRef(
        graph_id=str(data["graph_id"]),
        node_id=str(data["node_id"]),
        output_slot=int(data.get("output_slot", 0)),
        kind=TopoKind[str(data["kind"])],
        topo_id=str(data["topo_id"]),
    )


def topo_entry_to_dict(entry: "TopoEntry") -> Dict[str, Any]:
    return {
        "ref": topo_ref_to_dict(entry.ref),
        "event": entry.event.name,
        "origin_role": entry.origin_role,
        "parent_refs": [topo_ref_to_dict(ref) for ref in entry.parent_refs],
        "metadata": dict(entry.metadata),
    }


def topo_entry_from_dict(data: Dict[str, Any]) -> "TopoEntry":
    return TopoEntry(
        ref=topo_ref_from_dict(data["ref"]),
        event=TopoEvent[str(data["event"])],
        origin_role=(
            str(data["origin_role"]) if data.get("origin_role") is not None else None
        ),
        parent_refs=tuple(
            topo_ref_from_dict(item) for item in data.get("parent_refs", [])
        ),
        metadata=dict(data.get("metadata", {})),
    )


def topo_role_entry_to_dict(entry: "TopoRoleEntry") -> Dict[str, Any]:
    return {
        "ref": topo_ref_to_dict(entry.ref),
        "role": entry.role,
        "origin_role": entry.origin_role,
        "parent_refs": [topo_ref_to_dict(ref) for ref in entry.parent_refs],
        "metadata": dict(entry.metadata),
    }


def topo_role_entry_from_dict(data: Dict[str, Any]) -> "TopoRoleEntry":
    return TopoRoleEntry(
        ref=topo_ref_from_dict(data["ref"]),
        role=str(data["role"]),
        origin_role=(
            str(data["origin_role"]) if data.get("origin_role") is not None else None
        ),
        parent_refs=tuple(
            topo_ref_from_dict(item) for item in data.get("parent_refs", [])
        ),
        metadata=dict(data.get("metadata", {})),
    )


def topo_delta_to_dict(delta: "TopoDelta") -> Dict[str, Any]:
    return {
        "preserved": [topo_ref_to_dict(ref) for ref in delta.preserved],
        "modified": [topo_ref_to_dict(ref) for ref in delta.modified],
        "generated": [topo_ref_to_dict(ref) for ref in delta.generated],
        "deleted": [topo_ref_to_dict(ref) for ref in delta.deleted],
        "section_edges": [topo_ref_to_dict(ref) for ref in delta.section_edges],
        "entries": [topo_entry_to_dict(entry) for entry in delta.entries],
        "roles": [topo_role_entry_to_dict(entry) for entry in delta.roles],
        "raw_event": dict(delta.raw_event),
    }


def topo_delta_from_dict(data: Dict[str, Any]) -> "TopoDelta":
    return TopoDelta(
        preserved=tuple(topo_ref_from_dict(item) for item in data.get("preserved", [])),
        modified=tuple(topo_ref_from_dict(item) for item in data.get("modified", [])),
        generated=tuple(topo_ref_from_dict(item) for item in data.get("generated", [])),
        deleted=tuple(topo_ref_from_dict(item) for item in data.get("deleted", [])),
        section_edges=tuple(
            topo_ref_from_dict(item) for item in data.get("section_edges", [])
        ),
        entries=tuple(topo_entry_from_dict(item) for item in data.get("entries", [])),
        roles=tuple(topo_role_entry_from_dict(item) for item in data.get("roles", [])),
        raw_event=dict(data.get("raw_event", {})),
    )


@dataclass(frozen=True)
class TopoEntry:
    """Record for one topological entity after an operation.

    Attributes:
        ref:         Reference to this entity.
        event:       What happened to it (preserved / modified / generated / deleted).
        origin_role: Semantic role of the input that produced this entity
                     (e.g. ``"body"`` or ``"tool"``).  ``None`` if not applicable.
        parent_refs: References to upstream entities that were the ancestors.
        metadata:    Arbitrary key-value metadata for extensibility.
    """

    ref: TopoRef
    event: TopoEvent
    origin_role: Optional[str] = None
    parent_refs: Tuple[TopoRef, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopoRoleEntry:
    """Kernel-backed operation role assigned to one result entity.

    Output roles are independent of topology change events. For example, an
    extrusion start cap can be identified by ``FirstShape`` without claiming
    that OCC classified it as generated or modified.
    """

    ref: TopoRef
    role: str
    origin_role: Optional[str] = None
    parent_refs: Tuple[TopoRef, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        role = str(self.role).strip().lower()
        if not role or any(not part for part in role.split(".")):
            raise ValueError("topology output role must be a non-empty dot token")
        object.__setattr__(self, "role", role)


@dataclass(frozen=True)
class TopoDelta:
    """Complete topological change set for a single operation.

    Each operation produces a delta describing how its inputs' subshapes
    map to the outputs.  All lists store *references* (``TopoRef``), not
    the geometric objects themselves.

    Attributes:
        preserved:     Entities that survived unchanged.
        modified:      Entities that were altered (split, trimmed, re-faced…).
        generated:     Entities newly created by the operation.
        deleted:       Entities completely removed.
        section_edges: Edges created by boolean intersection (convenience subset
                       of ``generated``).
        entries:       Optional richer per-entity records with lineage.
        roles:         Operation-native output-role evidence, independent of events.
        raw_event:     Opaque dict for transport of OCC-specific detail.
    """

    preserved: Tuple[TopoRef, ...] = ()
    modified: Tuple[TopoRef, ...] = ()
    generated: Tuple[TopoRef, ...] = ()
    deleted: Tuple[TopoRef, ...] = ()
    section_edges: Tuple[TopoRef, ...] = ()
    entries: Tuple[TopoEntry, ...] = ()
    roles: Tuple[TopoRoleEntry, ...] = ()
    raw_event: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticDelta:
    """Semantic entity change set attached to a single recorded operation."""

    created: Tuple[SemanticRef, ...] = ()
    modified: Tuple[SemanticRef, ...] = ()
    deleted: Tuple[SemanticRef, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)


def bind_semantic_delta(
    delta: Optional[SemanticDelta], graph_id: str, node_id: str
) -> Optional[SemanticDelta]:
    if delta is None:
        return None

    def bind_ref(ref: SemanticRef) -> SemanticRef:
        return SemanticRef(
            graph_id=graph_id if ref.graph_id in {"", "pending"} else ref.graph_id,
            node_id=node_id if ref.node_id in {"", "pending"} else ref.node_id,
            entity_type=ref.entity_type,
            entity_id=ref.entity_id,
        )

    return SemanticDelta(
        created=tuple(bind_ref(ref) for ref in delta.created),
        modified=tuple(bind_ref(ref) for ref in delta.modified),
        deleted=tuple(bind_ref(ref) for ref in delta.deleted),
        metadata=dict(delta.metadata),
    )


def bind_topo_delta(
    delta: Optional[TopoDelta], graph_id: str, node_id: str
) -> Optional[TopoDelta]:
    if delta is None:
        return None

    def bind_ref(ref: TopoRef) -> TopoRef:
        return TopoRef(
            graph_id=graph_id if ref.graph_id in {"", "pending"} else ref.graph_id,
            node_id=node_id if ref.node_id in {"", "pending"} else ref.node_id,
            output_slot=ref.output_slot,
            kind=ref.kind,
            topo_id=ref.topo_id,
        )

    return TopoDelta(
        preserved=tuple(bind_ref(ref) for ref in delta.preserved),
        modified=tuple(bind_ref(ref) for ref in delta.modified),
        generated=tuple(bind_ref(ref) for ref in delta.generated),
        deleted=tuple(bind_ref(ref) for ref in delta.deleted),
        section_edges=tuple(bind_ref(ref) for ref in delta.section_edges),
        entries=tuple(
            TopoEntry(
                ref=bind_ref(entry.ref),
                event=entry.event,
                origin_role=entry.origin_role,
                parent_refs=tuple(bind_ref(ref) for ref in entry.parent_refs),
                metadata=dict(entry.metadata),
            )
            for entry in delta.entries
        ),
        roles=tuple(
            TopoRoleEntry(
                ref=bind_ref(entry.ref),
                role=entry.role,
                origin_role=entry.origin_role,
                parent_refs=tuple(bind_ref(ref) for ref in entry.parent_refs),
                metadata=dict(entry.metadata),
            )
            for entry in delta.roles
        ),
        raw_event=dict(delta.raw_event),
    )


@dataclass(frozen=True)
class OperationNode:
    """A single node in the operation DAG.

    Attributes:
        node_id:      Unique identifier within the graph.
        op:           Operation type (e.g. ``"make_line_redge"``, ``"make_cut_rsolid"``).
        params:       Serialisable parameters for re-creation.
        inputs:       Upstream nodes whose outputs feed into this node.
        context:      Work-plane / coordinate-system snapshot taken at creation time.
        output_count: Number of output shapes this node produces (usually 1).
        topo_delta:   Topological change set (may be ``None`` for simple primitives).
        tags:         Free-form labels for annotation.
        source:       Best-effort Python source provenance; ignored by replay.
        expressions:  The expressions ``param_exprs`` refers to.
        frame:        The coordinate frame current when the node was recorded.

    ``expressions`` and ``frame`` duplicate what the recording session keeps
    in its expression and frame graphs. They travel with the node so a node
    that outlives its session (a notebook cell's result, restored from the
    cell cache) can still be registered in a new one. They are excluded from
    equality and from :meth:`OperationGraph.to_dict`.

    Nodes pickle and deep-copy without recursion (see :meth:`__reduce__`).
    """

    node_id: str
    op: str
    params: Dict[str, Any] = field(default_factory=dict)
    param_exprs: Dict[str, Any] = field(default_factory=dict)
    inputs: Tuple["OperationNode", ...] = ()
    context: Optional[Dict[str, Any]] = None
    output_count: int = 1
    semantic_delta: Optional[SemanticDelta] = None
    topo_delta: Optional[TopoDelta] = None
    tags: FrozenSet[str] = frozenset()
    graph_id: Optional[str] = None
    source: Optional[Dict[str, Any]] = None
    expressions: Tuple["ScalarExpr", ...] = field(
        default=(), compare=False, repr=False
    )
    frame: Optional["FrameNode"] = field(default=None, compare=False, repr=False)

    def __reduce__(self) -> Tuple[Any, ...]:
        # The default pickle recurses through ``inputs`` and overflows the
        # stack on long chains. Instead the whole upstream closure is written
        # as a flat list of records, inputs first, each naming its inputs by
        # id. The records hold the nodes' own field objects, so pickle's memo
        # writes data shared between several pickled nodes only once.
        records = tuple(_node_record(node) for node in upstream_closure((self,)))
        return (_restore_operation_node, (_NODE_FIELD_NAMES, records))

    def __deepcopy__(self, memo: Dict[int, Any]) -> "OperationNode":
        # Same reason as ``__reduce__``: copy the closure iteratively. Every
        # field except ``inputs`` is deep-copied; ``memo`` keeps nodes shared
        # within one ``deepcopy`` call shared in the copy.
        copies: Dict[str, OperationNode] = {}

        def copied(node: OperationNode) -> OperationNode:
            done = memo.get(id(node))
            return done if done is not None else copies[node.node_id]

        for node in upstream_closure((self,), stop_at=lambda node: id(node) in memo):
            copy = replace(
                node,
                inputs=tuple(copied(item) for item in node.inputs),
                **{
                    name: deepcopy(getattr(node, name), memo)
                    for name in _NODE_FIELD_NAMES
                    if name != "inputs"
                },
            )
            memo[id(node)] = copies[node.node_id] = copy
        return memo[id(self)]


_NODE_FIELD_NAMES: Tuple[str, ...] = tuple(item.name for item in fields(OperationNode))
# What two node objects must agree on to be the same operation, besides
# their input ids (see same_node_content).
_NODE_CONTENT_FIELDS: Tuple[str, ...] = tuple(
    item.name for item in fields(OperationNode) if item.compare and item.name != "inputs"
)


class StaleLineageError(ValueError):
    """Two different operations carry the same node id.

    In a notebook this means values from an older run of a cell met values
    from a newer run of the same cell; re-running the cells that produced
    them resolves it.
    """

    def __init__(self, node_id: str) -> None:
        super().__init__(
            f"node '{node_id}' exists in two different versions (stale lineage); "
            "re-run the cells that produced these values"
        )
        self.node_id = node_id


def same_node_content(first: OperationNode, second: OperationNode) -> bool:
    """Whether two node objects record the same operation.

    Shallow on purpose: every field other than ``inputs`` must be equal and
    the inputs must have the same ids in the same order. The dataclass
    ``==`` compares ``inputs`` recursively, which is exponential on
    diamond-shaped graphs.
    """

    if first is second:
        return True
    return all(
        getattr(first, name) == getattr(second, name) for name in _NODE_CONTENT_FIELDS
    ) and _input_ids(first) == _input_ids(second)


def upstream_closure(
    roots: Iterable[OperationNode],
    *,
    stop_at: Optional[Callable[[OperationNode], bool]] = None,
) -> List[OperationNode]:
    """Return *roots* and every node upstream of them, inputs first.

    The walk is an iterative depth-first post-order over ``inputs``, so
    chains of any length are fine and the order is deterministic. Nodes are
    identified by ``node_id``: a second object with an id already seen is
    skipped when :func:`same_node_content` holds and raises
    :class:`StaleLineageError` otherwise. Nodes for which *stop_at* returns
    true are neither returned nor walked through.
    """

    order: List[OperationNode] = []
    seen: Dict[str, OperationNode] = {}
    # (node, inputs_done): a node is emitted once all its inputs have been.
    stack: List[Tuple[OperationNode, bool]] = [
        (root, False) for root in reversed(tuple(roots))
    ]
    while stack:
        node, inputs_done = stack.pop()
        if inputs_done:
            order.append(node)
            continue
        known = seen.get(node.node_id)
        if known is not None:
            if not same_node_content(known, node):
                raise StaleLineageError(node.node_id)
            continue
        if stop_at is not None and stop_at(node):
            continue
        seen[node.node_id] = node
        stack.append((node, True))
        stack.extend((item, False) for item in reversed(node.inputs))
    return order


def _input_ids(node: OperationNode) -> Tuple[str, ...]:
    return tuple(item.node_id for item in node.inputs)


def _node_record(node: OperationNode) -> Tuple[Any, ...]:
    """One node's fields in ``_NODE_FIELD_NAMES`` order, inputs as ids."""

    return tuple(
        _input_ids(node) if name == "inputs" else getattr(node, name)
        for name in _NODE_FIELD_NAMES
    )


# Nodes restored from pickles, by (graph_id, node_id). marimo pickles every
# cell variable separately; this lets two variables that shared a node before
# pickling share one node object again after loading.
_RESTORED_NODES: "weakref.WeakValueDictionary[Tuple[Optional[str], str], OperationNode]" = (
    weakref.WeakValueDictionary()
)


def _restore_operation_node(
    field_names: Tuple[str, ...], records: Tuple[Tuple[Any, ...], ...]
) -> OperationNode:
    """Rebuild the node pickled by :meth:`OperationNode.__reduce__`.

    *records* is its upstream closure, inputs first, so the pickled node is
    the last one. The field names are stored with the records, which keeps
    old pickles loadable after fields with defaults are added.
    """

    restored: Dict[str, OperationNode] = {}
    node: Optional[OperationNode] = None
    for record in records:
        state = dict(zip(field_names, record))
        state["inputs"] = tuple(restored[node_id] for node_id in state["inputs"])
        node = _share_restored(OperationNode(**state))
        restored[node.node_id] = node
    if node is None:
        raise ValueError("an operation node pickle holds no records")
    return node


def _share_restored(node: OperationNode) -> OperationNode:
    """Return the live restored twin of *node*, or register *node* as one.

    A twin must hold the very same input objects: *node*'s inputs are
    already shared, so an input that was replaced by a newer version makes
    every node downstream of it a new version too.
    """

    key = (node.graph_id, node.node_id)
    existing = _RESTORED_NODES.get(key)
    if (
        existing is not None
        and len(existing.inputs) == len(node.inputs)
        and all(old is new for old, new in zip(existing.inputs, node.inputs))
        and same_node_content(existing, node)
    ):
        return existing
    _RESTORED_NODES[key] = node
    return node


def _make_id(prefix: str = "node") -> str:
    """Generate a short unique id."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _node_display_category(op: str) -> str:
    if op.startswith("make_select_"):
        return "selection"
    if op in {
        "cut",
        "union",
        "intersect",
        "make_cut_rsolid",
        "make_union_rsolid",
        "make_intersect_rsolid",
    }:
        return "boolean"
    if op in {
        "translate",
        "rotate",
        "mirror",
        "make_translate_rshape",
        "make_rotate_rshape",
        "make_mirror_rshape",
    }:
        return "transform"
    if op in {"linear_pattern", "radial_pattern"}:
        return "pattern"
    if op in {
        "extrude",
        "revolve",
        "loft",
        "sweep",
        "helical_sweep",
        "make_extrude_rsolid",
        "make_revolve_rsolid",
        "make_loft_rsolid",
        "make_sweep_rsolid",
        "make_twisted_sweep_rsolid",
    }:
        return "feature"
    if op in {
        "fillet",
        "chamfer",
        "shell",
        "make_fillet_rsolid",
        "make_chamfer_rsolid",
        "make_shell_rsolid",
    }:
        return "detail"
    if op.startswith("make_"):
        if any(token in op for token in ("_wire", "_edge", "_face", "point")):
            return "profile"
        return "primitive"
    return "operation"


def _node_display_label(op: str) -> str:
    label = op.replace("_", " ")
    if label.startswith("make "):
        label = label[5:]
    return " ".join(word.capitalize() for word in label.split())


def _node_display_summary(op: str, params: Dict[str, Any]) -> str:
    ignored = {
        "selected_edges",
        "selected_faces",
        "selected_edge_node_ids",
        "selected_face_node_ids",
        "selected_edge_indices",
        "selected_face_indices",
        "geo_selector",
    }
    summary_parts: List[str] = []
    for key, value in params.items():
        if key in ignored:
            continue
        if isinstance(value, float):
            summary_parts.append(f"{key}={value:.4g}")
        elif isinstance(value, (list, tuple)) and len(value) > 4:
            summary_parts.append(f"{key}[{len(value)}]")
        else:
            summary_parts.append(f"{key}={value}")
        if len(summary_parts) == 3:
            break

    if not summary_parts:
        return _node_display_label(op)
    return ", ".join(summary_parts)


def _node_display_payload(op: str, params: Dict[str, Any]) -> Dict[str, Any]:
    selection_count = 0
    if isinstance(params.get("selected_edges"), list):
        selection_count = len(params["selected_edges"])
    elif isinstance(params.get("selected_faces"), list):
        selection_count = len(params["selected_faces"])

    payload: Dict[str, Any] = {
        "label": _node_display_label(op),
        "category": _node_display_category(op),
        "summary": _node_display_summary(op, params),
    }
    if selection_count:
        payload["selection_count"] = selection_count
    return payload


class OperationGraph:
    """A directed acyclic graph of CAD operations.

    The graph tracks nodes (operations) and edges (data-flow dependencies).
    It supports topological ordering, upstream/downstream queries, and
    root/leaf enumeration.

    Usage::

        g = OperationGraph()
        e1 = g.add_node("make_line_redge", {"start": (0, 0, 0), "end": (1, 0, 0)})
        e2 = g.add_node("make_line_redge", {"start": (1, 0, 0), "end": (1, 1, 0)})
        wire = g.add_node("make_wire_from_edges_rwire", {"edge_count": 2}, inputs=[e1, e2])
        assert wire.node_id == g.leaf_nodes()[0].node_id

    A *namespace* prefixes every id the graph allocates
    (``<namespace>_node_00000001``). Graphs that share a ``graph_id`` but
    allocate ids independently, such as the per-cell graphs of a notebook,
    use distinct namespaces so their nodes can later meet in one graph
    (:meth:`adopt`) without id clashes.
    """

    def __init__(
        self, graph_id: Optional[str] = None, *, namespace: Optional[str] = None
    ) -> None:
        if namespace is not None and not namespace:
            raise ValueError("graph namespace must be a non-empty string")
        self.graph_id: str = graph_id or _make_id("graph")
        self.namespace: Optional[str] = namespace
        self._nodes: Dict[str, OperationNode] = {}
        self._edges: List[Tuple[str, str]] = []
        self._adj: Dict[str, List[str]] = defaultdict(list)
        self._radj: Dict[str, List[str]] = defaultdict(list)
        self._counter: int = 0

    def namespaced(self, prefix: str) -> str:
        """Return *prefix* qualified with this graph's namespace, if any."""

        return prefix if self.namespace is None else f"{self.namespace}_{prefix}"

    def allocate_node_id(self, prefix: str = "node") -> str:
        """Allocate the next deterministic graph-local node identifier."""

        qualified = self.namespaced(prefix)
        while True:
            self._counter += 1
            node_id = f"{qualified}_{self._counter:08x}"
            if node_id not in self._nodes:
                return node_id

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def add_node(
        self,
        op: str,
        params: Optional[Dict[str, Any]] = None,
        param_exprs: Optional[Dict[str, Any]] = None,
        inputs: Optional[List[OperationNode]] = None,
        node_id: Optional[str] = None,
        output_count: int = 1,
        semantic_delta: Optional[SemanticDelta] = None,
        topo_delta: Optional[TopoDelta] = None,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[Set[str]] = None,
        source: Optional[Dict[str, Any]] = None,
        expressions: Iterable[ScalarExpr] = (),
        frame: Optional[FrameNode] = None,
    ) -> OperationNode:
        """Add an operation node and wire its input edges.

        Returns the created :class:`OperationNode`.
        """
        nid = node_id or self.allocate_node_id()
        if nid in self._nodes:
            raise ValueError(f"node id '{nid}' already exists in graph")

        input_nodes = tuple(inputs) if inputs else ()
        for inp in input_nodes:
            if inp.graph_id is not None and inp.graph_id != self.graph_id:
                raise ValueError(
                    f"input node '{inp.node_id}' belongs to graph "
                    f"'{inp.graph_id}', active graph is '{self.graph_id}'"
                )
            if inp.node_id not in self._nodes:
                raise ValueError(
                    f"input node '{inp.node_id}' is not part of this graph"
                )
            if self._nodes[inp.node_id] is not inp:
                raise ValueError(
                    f"input node '{inp.node_id}' is not the node owned by this graph"
                )

        bound_semantic_delta = bind_semantic_delta(semantic_delta, self.graph_id, nid)
        bound_topo_delta = bind_topo_delta(topo_delta, self.graph_id, nid)

        node = OperationNode(
            node_id=nid,
            op=op,
            params=dict(params) if params else {},
            param_exprs=dict(param_exprs) if param_exprs else {},
            inputs=input_nodes,
            context=context,
            output_count=output_count,
            semantic_delta=bound_semantic_delta,
            topo_delta=bound_topo_delta,
            tags=frozenset(tags) if tags else frozenset(),
            graph_id=self.graph_id,
            source=dict(source) if source else None,
            expressions=tuple(expressions),
            frame=frame,
        )
        self._insert(node)
        return node

    def adopt(self, node: OperationNode) -> OperationNode:
        """Make *node* and everything upstream of it part of this graph.

        Nodes keep their ids and stay the same objects. An id this graph
        already has is accepted when it is the same object or has the same
        content (:func:`same_node_content`); the graph keeps its own object
        then, and nothing upstream of it is revisited. A different node under
        a known id raises :class:`StaleLineageError`. Nodes must carry this
        graph's ``graph_id``.

        Returns the graph's node for ``node.node_id``, which is *node* or an
        object with the same content.
        """

        def known(item: OperationNode) -> bool:
            owned = self._nodes.get(item.node_id)
            if owned is None:
                return False
            if not same_node_content(owned, item):
                raise StaleLineageError(item.node_id)
            return True

        for item in upstream_closure((node,), stop_at=known):
            if item.graph_id != self.graph_id:
                raise ValueError(
                    f"node '{item.node_id}' belongs to graph '{item.graph_id}', "
                    f"this graph is '{self.graph_id}'"
                )
            self._insert(item)
        return self._nodes[node.node_id]

    def _insert(self, node: OperationNode) -> None:
        # Callers guarantee a new id whose inputs are already in the graph.
        self._nodes[node.node_id] = node
        for inp in node.inputs:
            self._edges.append((inp.node_id, node.node_id))
            self._adj[inp.node_id].append(node.node_id)
            self._radj[node.node_id].append(inp.node_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[OperationNode]:
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> List[OperationNode]:
        return list(self._nodes.values())

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edges(self) -> Set[Tuple[str, str]]:
        return set(self._edges)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def upstream_nodes(self, node_id: str) -> List[str]:
        """Return ids of nodes that feed into *node_id*."""
        return list(self._radj.get(node_id, []))

    def downstream_nodes(self, node_id: str) -> List[str]:
        """Return ids of nodes that consume *node_id*'s output."""
        return list(self._adj.get(node_id, []))

    def root_nodes(self) -> List[OperationNode]:
        """Nodes with no inputs."""
        return [self._nodes[nid] for nid in self._nodes if not self._radj.get(nid)]

    def leaf_nodes(self) -> List[OperationNode]:
        """Nodes with no downstream consumers."""
        return [self._nodes[nid] for nid in self._nodes if not self._adj.get(nid)]

    def is_dag(self) -> bool:
        """Return ``True`` if the graph has no cycles (always valid for correct usage)."""
        visited: Set[str] = set()
        on_stack: Set[str] = set()

        def dfs(nid: str) -> bool:
            visited.add(nid)
            on_stack.add(nid)
            for child in self._adj.get(nid, []):
                if child not in visited:
                    if not dfs(child):
                        return False
                elif child in on_stack:
                    return False
            on_stack.discard(nid)
            return True

        for nid in self._nodes:
            if nid not in visited:
                if not dfs(nid):
                    return False
        return True

    def topological_order(self) -> List[OperationNode]:
        """Return nodes in valid execution (topological) order.

        Raises ``ValueError`` if the graph contains a cycle.
        """
        if not self.is_dag():
            raise ValueError("graph contains a cycle")

        in_degree: Dict[str, int] = {nid: 0 for nid in self._nodes}
        for child, parent in self._edges:
            in_degree[parent] = in_degree.get(parent, 0) + 1

        queue: List[str] = [nid for nid, d in in_degree.items() if d == 0]
        order: List[str] = []

        while queue:
            nid = queue.pop(0)
            order.append(nid)
            for child in self._adj.get(nid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        return [self._nodes[nid] for nid in order]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the graph to a JSON-compatible dictionary."""
        nodes_data = []
        for node in self.topological_order():
            node_data: Dict[str, Any] = {
                "node_id": node.node_id,
                "op": node.op,
                "params": dict(node.params),
                "inputs": [inp.node_id for inp in node.inputs],
                "output_count": node.output_count,
                "tags": sorted(node.tags),
                "display": _node_display_payload(node.op, node.params),
            }
            if node.source is not None:
                node_data["source"] = canonical_source_payload(node.source)
            if node.param_exprs:
                node_data["param_exprs"] = dict(node.param_exprs)
            if node.context:
                node_data["context"] = node.context
            if node.semantic_delta is not None:
                node_data["semantic_delta"] = semantic_delta_to_dict(
                    node.semantic_delta
                )
            if node.topo_delta is not None:
                node_data["topo_delta"] = topo_delta_to_dict(node.topo_delta)
            nodes_data.append(node_data)

        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "producer_version": _producer_version(),
            "capabilities": graph_capabilities_payload(),
            "graph_id": self.graph_id,
            "nodes": nodes_data,
            "edges": [[src, dst] for src, dst in self._edges],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the graph to a JSON string."""
        import json

        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any], *, strict: bool = True
    ) -> "OperationGraph":
        """Reconstruct a graph from a dictionary.

        Nodes are added in topological order so that input references resolve.
        """
        if not isinstance(data, dict):
            raise ValueError("graph payload must be an object")
        if strict and data.get("schema_version") != GRAPH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported graph schema_version {data.get('schema_version')!r}"
            )
        raw_nodes = data.get("nodes", [])
        raw_edges = data.get("edges", [])
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise ValueError("graph nodes and edges must be arrays")
        graph = cls(graph_id=data.get("graph_id"))

        # Build nodes first (without edges)
        node_map: Dict[str, OperationNode] = {}
        declared_edges: set[tuple[str, str]] = set()
        for nd in raw_nodes:
            if not isinstance(nd, dict):
                raise ValueError("graph node entries must be objects")
            node_id = nd.get("node_id")
            op = nd.get("op")
            output_count = nd.get("output_count", 1)
            inputs = nd.get("inputs", [])
            if not isinstance(node_id, str) or not node_id:
                raise ValueError("graph node_id must be a non-empty string")
            if not isinstance(op, str) or not op:
                raise ValueError(f"graph node '{node_id}' op must be a non-empty string")
            if (
                isinstance(output_count, bool)
                or not isinstance(output_count, int)
                or output_count < 0
            ):
                raise ValueError(
                    f"graph node '{node_id}' output_count must be a non-negative integer"
                )
            if not isinstance(inputs, list) or not all(
                isinstance(input_id, str) for input_id in inputs
            ):
                raise ValueError(f"graph node '{node_id}' inputs must be string ids")
            if len(set(inputs)) != len(inputs):
                raise ValueError(f"graph node '{node_id}' contains duplicate inputs")
            declared_edges.update((input_id, node_id) for input_id in inputs)
            tags_set = set(nd.get("tags", []))
            node = graph.add_node(
                op=op,
                params=nd.get("params", {}),
                param_exprs=nd.get("param_exprs", {}),
                node_id=node_id,
                output_count=output_count,
                semantic_delta=(
                    semantic_delta_from_dict(nd["semantic_delta"])
                    if isinstance(nd.get("semantic_delta"), dict)
                    else None
                ),
                topo_delta=(
                    topo_delta_from_dict(nd["topo_delta"])
                    if isinstance(nd.get("topo_delta"), dict)
                    else None
                ),
                context=nd.get("context"),
                tags=tags_set if tags_set else None,
                source=nd.get("source"),
            )
            node_map[node_id] = node

        # Wire edges
        serialized_edges: set[tuple[str, str]] = set()
        for edge in raw_edges:
            if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                if strict:
                    raise ValueError(f"malformed graph edge entry: {edge!r}")
                continue
            src, dst = edge
            if src not in node_map or dst not in node_map:
                if strict:
                    raise ValueError(
                        f"graph edge references missing node(s): {src!r} -> {dst!r}"
                    )
                continue
            pair = (src, dst)
            if pair in serialized_edges and strict:
                raise ValueError(f"duplicate graph edge: {src!r} -> {dst!r}")
            serialized_edges.add(pair)
            graph._edges.append((src, dst))
            graph._adj[src].append(dst)
            graph._radj[dst].append(src)

        # Fix up inputs references
        if strict and serialized_edges != declared_edges:
            raise ValueError("graph edges do not match node input declarations")

        for nd in raw_nodes:
            node = node_map.get(nd["node_id"])
            if node and nd.get("inputs"):
                missing_inputs = [iid for iid in nd["inputs"] if iid not in node_map]
                if missing_inputs and strict:
                    raise ValueError(
                        f"graph node '{node.node_id}' references missing input node(s): "
                        + ", ".join(str(iid) for iid in missing_inputs)
                    )
                input_nodes = tuple(
                    node_map[iid] for iid in nd["inputs"] if iid in node_map
                )
                # Rebuild the node with correct inputs
                graph._nodes[node.node_id] = OperationNode(
                    node_id=node.node_id,
                    op=node.op,
                    params=node.params,
                    param_exprs=node.param_exprs,
                    inputs=input_nodes,
                    context=node.context,
                    output_count=node.output_count,
                    semantic_delta=node.semantic_delta,
                    topo_delta=node.topo_delta,
                    tags=node.tags,
                    graph_id=graph.graph_id,
                    source=dict(node.source) if node.source else None,
                )

        if strict and not graph.is_dag():
            raise ValueError("graph contains a cycle")
        return graph

    @classmethod
    def from_json(cls, json_str: str, *, strict: bool = True) -> "OperationGraph":
        """Reconstruct a graph from a JSON string."""
        import json

        return cls.from_dict(json.loads(json_str), strict=strict)

"""Topology tracking data models for recording CAD operations and their lineage.

These models form the foundation for:
- Tracking how topological entities (vertex/edge/wire/face/solid) change through operations
- Recording an operation DAG that can be serialized and replayed
- Providing stable references for auto-tagging and query-language integration
"""

from __future__ import annotations

import uuid
import weakref
from collections import defaultdict, deque
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
from simplecadapi._cpp import (
    OperationGraph,
    OperationNode,
    SemanticDelta,
    SemanticRef,
    StaleLineageError,
    same_node_content,
    upstream_closure,
)

if TYPE_CHECKING:
    from ..params.expr import ScalarExpr
    from simplecadapi._cpp import FrameNode

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




_NODE_FIELD_NAMES: Tuple[str, ...] = tuple(item.name for item in fields(OperationNode))
# What two node objects must agree on to be the same operation, besides
# their input ids (see same_node_content).
_NODE_CONTENT_FIELDS: Tuple[str, ...] = tuple(
    item.name for item in fields(OperationNode) if item.compare and item.name != "inputs"
)








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
        "make_scale_rsolid",
        "make_transform_rsolid",
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
        "make_extrude_taper_rsolid",
        "make_extrude_until_rsolid",
        "make_sweep_multisection_rsolid",
    }:
        return "feature"
    if op in {
        "fillet",
        "chamfer",
        "shell",
        "make_fillet_rsolid",
        "make_chamfer_rsolid",
        "make_shell_rsolid",
        "make_offset_rsolid",
        "make_draft_rsolid",
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



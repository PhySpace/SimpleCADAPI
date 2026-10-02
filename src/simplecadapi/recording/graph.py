"""DAG session recorder for building operation graphs.

Usage::

    from simplecadapi.recording.graph import GraphSession, record_operation

    with GraphSession() as session:
        line_a = record_operation(
            "make_line_redge", {"start": (0, 0, 0), "end": (10, 0, 0)}
        )
        line_b = record_operation(
            "make_line_redge", {"start": (10, 0, 0), "end": (10, 5, 0)}
        )
        wire = record_operation(
            "make_wire_from_edges_rwire", {"edge_count": 2}, inputs=[line_a, line_b]
        )

    # Session graph is now available
    assert session.graph.node_count == 3
    json_str = session.graph.to_json()
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, fields, is_dataclass
from functools import wraps
import json
import inspect
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    ParamSpec,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)
from pathlib import Path

from ..params.expr import (
    ExpressionGraph,
    ScalarLike,
    ToleranceLike,
    canonicalize_params,
    referenced_expressions,
)
from ..params.units import UnitLike
from ..params.frame import FrameGraph, FrameNode
from ..params.tolerance import (
    ToleranceGraph,
    ToleranceMethod,
    ToleranceReport,
    ToleranceRequirement,
)
from ..topology.model import (
    OperationGraph,
    OperationNode,
    TopoDelta,
    TopoEntry,
    TopoEvent,
    TopoRoleEntry,
)
from ..topology.model import SemanticDelta, SemanticRef
from ..topology.model import TopoKind, TopoRef, topo_ref_to_dict
from ..core import (
    WORLD_CS,
    Compound,
    Edge,
    Face,
    Shell,
    Solid,
    Vertex,
    Wire,
    get_current_cs,
    use_coordinate_system,
)
from ..product.assembly import Assembly
from ..product.part import Part
from .source_mapping import capture_source_provenance

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

_active_session_var: ContextVar[Optional["GraphSession"]] = ContextVar(
    "simplecadapi_active_graph_session", default=None
)
_recording_suspend_depth_var: ContextVar[int] = ContextVar(
    "simplecadapi_recording_suspend_depth", default=0
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


class GraphSession:
    """Context manager that records CAD operations into a DAG.

    Usage::

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

    Args:
        graph_id: Id of the recorded graph (random when omitted).
        allow_external_definitions: Let built ``Part``/``Assembly`` values
            that carry their own definition enter as ``reference_definition``
            nodes instead of being rejected.
        namespace: Prefix for every node and object id this session
            allocates, as in ``OperationGraph(namespace=...)``.
        shared_lineage: Accept values recorded by other sessions with the
            same ``graph_id`` by adopting their nodes, as in
            ``OperationGraph.adopt``. Notebook cell sessions use this;
            every other session only accepts nodes its own graph owns.
    """

    def __init__(
        self,
        graph_id: Optional[str] = None,
        *,
        allow_external_definitions: bool = False,
        namespace: Optional[str] = None,
        shared_lineage: bool = False,
    ) -> None:
        self.graph = OperationGraph(graph_id=graph_id, namespace=namespace)
        self.expression_graph = ExpressionGraph()
        self.tolerance_graph = ToleranceGraph(self.expression_graph)
        self.frame_graph = FrameGraph()
        self._active_session_token: Optional[Token[Optional["GraphSession"]]] = None
        self._result_node_ids: List[str] = []
        self._has_explicit_results = False
        self._captured_values: List[Any] = []

        self._object_id_counters: Dict[str, int] = {}
        self._external_definition_nodes: Dict[int, OperationNode] = {}
        self._external_definition_nodes_by_id: Dict[str, OperationNode] = {}
        self._allow_external_definitions = bool(allow_external_definitions)
        self._shared_lineage = bool(shared_lineage)

    def start(self) -> None:
        if self._active_session_token is not None:
            raise RuntimeError("GraphSession is already active")
        self._active_session_token = _active_session_var.set(self)

    def stop(self) -> None:
        if self._active_session_token is not None:
            _active_session_var.reset(self._active_session_token)
            self._active_session_token = None

    def __enter__(self) -> "GraphSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def allocate_object_id(self, prefix: str) -> str:
        """Allocate a deterministic session-local identifier outside the DAG."""

        next_value = self._object_id_counters.get(prefix, 0) + 1
        self._object_id_counters[prefix] = next_value
        return f"{self.graph.namespaced(prefix)}_{next_value:08x}"

    def owned_node(self, node: OperationNode) -> OperationNode:
        """Return this session's graph node for *node*.

        A shared-lineage session adopts *node* with its upstream nodes and
        may return an equal node object it already had. Any other session
        requires *node* to be the very object its graph owns.
        """

        if self._shared_lineage:
            return self.graph.adopt(node)
        if self.graph.get_node(node.node_id) is not node:
            raise ValueError(
                f"graph node '{node.node_id}' is not owned by active graph "
                f"'{self.graph.graph_id}'"
            )
        return node

    def register_external_definition(
        self,
        *,
        value: Part | Assembly,
        definition_kind: str,
        definition_id: str,
        revision: str,
        content_hash: str,
    ) -> OperationNode:
        """Represent one immutable child definition without importing its DAG."""

        marker = id(value)
        existing = self._external_definition_nodes.get(marker)
        if existing is not None:
            return existing
        expected_id = value.part_id if isinstance(value, Part) else value.assembly_id
        expected_kind = "single_solid" if isinstance(value, Part) else "assembly"
        if expected_id != definition_id or expected_kind != definition_kind:
            raise ValueError("external definition runtime identity differs")
        node_id: str | None = None
        if self._shared_lineage:
            # Cells referencing one definition must agree on its node, so
            # the projected product holds a single reference to it.
            node_id = "ref_" + content_hash.removeprefix("sha256:")[:16]
            shared = self.graph.get_node(node_id)
            if shared is not None:
                self._external_definition_nodes[marker] = shared
                self._external_definition_nodes_by_id[definition_id] = shared
                return shared
        node = self.graph.add_node(
            node_id=node_id,
            op="reference_definition",
            params={
                "definition_kind": definition_kind,
                "definition_id": definition_id,
                "revision": revision,
                "content_hash": content_hash,
            },
            output_count=1,
            semantic_delta=SemanticDelta(
                created=(
                    SemanticRef(
                        graph_id="pending",
                        node_id="pending",
                        entity_type="ExternalDefinition",
                        entity_id=definition_id,
                    ),
                ),
                metadata={
                    "definition_kind": definition_kind,
                    "revision": revision,
                    "content_hash": content_hash,
                },
            ),
        )
        self._external_definition_nodes[marker] = node
        self._external_definition_nodes_by_id[definition_id] = node
        return node

    def external_definition_node(self, value: Any) -> OperationNode | None:
        direct = self._external_definition_nodes.get(id(value))
        if direct is not None:
            return direct
        if isinstance(value, Part):
            return self._external_definition_nodes_by_id.get(value.part_id)
        if isinstance(value, Assembly):
            return self._external_definition_nodes_by_id.get(value.assembly_id)
        return None

    def require_tolerance(
        self,
        value: ScalarLike,
        tolerance: ToleranceLike,
        *,
        method: ToleranceMethod = "worst_case",
        name: str | None = None,
        requirement_id: str | None = None,
        tolerance_unit: UnitLike | None = None,
    ) -> ToleranceRequirement:
        """Declare a persisted Length or Angle manufacturing requirement.

        ``tolerance_unit`` defaults to the target's canonical unit for
        unit-aware expressions. The requirement is validated immediately and at
        session/model export, import, replay, and translation boundaries.
        ``requirement_id`` defaults to the next ``tolreq`` object id.
        """

        return self.tolerance_graph.require(
            value,
            tolerance,
            method=method,
            name=name,
            requirement_id=(
                self.allocate_object_id("tolreq")
                if requirement_id is None
                else requirement_id
            ),
            tolerance_unit=tolerance_unit,
        )

    def validate_tolerances(self, *, raise_on_failure: bool = False) -> ToleranceReport:
        """Validate every declared dimension-chain requirement."""

        return self.tolerance_graph.validate(raise_on_failure=raise_on_failure)

    @property
    def result_node_ids(self) -> Tuple[str, ...]:
        """Return the explicitly captured model result node ids."""

        return tuple(self._result_node_ids)

    @property
    def has_explicit_results(self) -> bool:
        """Whether ``capture_result`` has been called for this session."""

        return self._has_explicit_results

    @property
    def captured_values(self) -> Tuple[Any, ...]:
        """Return values explicitly marked for final artifact export."""

        return tuple(self._captured_values)

    def capture_result(self, *, value: Any) -> Any:
        """Capture graph nodes directly represented by *value* as results."""

        self.validate_graph_ownership(value)
        nodes = list(_graph_nodes_in_value(value, deep=True))
        if not nodes:
            raise ValueError(
                "capture_result() requires a value containing at least one "
                "graph-backed shape or semantic value"
            )
        # validate_graph_ownership has checked (or adopted) every node.
        captured_ids: List[str] = []
        for node in nodes:
            if node.node_id not in captured_ids:
                captured_ids.append(node.node_id)
        self._has_explicit_results = True
        for node_id in captured_ids:
            if node_id not in self._result_node_ids:
                self._result_node_ids.append(node_id)
        self._captured_values.append(value)
        return value

    def clear_results(self) -> None:
        """Clear explicit result nodes and restore leaf fallback on export."""

        self._result_node_ids.clear()
        self._has_explicit_results = False
        self._captured_values.clear()

    def validate_graph_ownership(self, value: Any) -> None:
        """Reject values carrying lineage from a different graph."""

        for item in _walk_values(value, set(), deep=True):
            found = _graph_node_and_id(item)
            if found is not None:
                node, source_graph_id = found
                if source_graph_id not in {None, self.graph.graph_id}:
                    raise ValueError(
                        f"value contains graph node '{node.node_id}' from graph "
                        f"'{source_graph_id}', active graph is '{self.graph.graph_id}'"
                    )
                if self._shared_lineage:
                    self.graph.adopt(node)
                elif self.graph.get_node(node.node_id) is not node:
                    raise ValueError(
                        f"value contains graph node '{node.node_id}' not owned by "
                        f"active graph '{self.graph.graph_id}'"
                    )
            getter = getattr(item, "_get_runtime", None)
            topo_ref = getter("topo.ref") if callable(getter) else None
            if not isinstance(topo_ref, TopoRef):
                continue
            if topo_ref.graph_id != self.graph.graph_id:
                raise ValueError(
                    f"value contains topology reference '{topo_ref.topo_id}' from "
                    f"graph '{topo_ref.graph_id}', active graph is "
                    f"'{self.graph.graph_id}'"
                )
            if self.graph.get_node(topo_ref.node_id) is None:
                raise ValueError(
                    f"value contains topology reference '{topo_ref.topo_id}' for "
                    f"unknown node '{topo_ref.node_id}'"
                )




def get_active_session() -> Optional[GraphSession]:
    """Return the currently active GraphSession, or None."""
    return _active_session_var.get()


@contextmanager
def suspend_graph_recording():
    """Temporarily suspend automatic graph recording for internal API composition."""

    token = _recording_suspend_depth_var.set(_recording_suspend_depth_var.get() + 1)
    try:
        yield
    finally:
        _recording_suspend_depth_var.reset(token)


@contextmanager
def isolated_recording():
    """Run a nested definition build as if it were called at top level.

    The caller's session is hidden (no active session, recording not
    suspended) and the world coordinate system is current, so the nested
    build records only into its own session and does not depend on where it
    was called from. Everything is restored on exit.
    """

    session_token = _active_session_var.set(None)
    suspend_token = _recording_suspend_depth_var.set(0)
    try:
        with use_coordinate_system(WORLD_CS):
            yield
    finally:
        _recording_suspend_depth_var.reset(suspend_token)
        _active_session_var.reset(session_token)


def _graph_node_and_id(value: Any) -> Optional[Tuple[OperationNode, Optional[str]]]:
    getter = getattr(value, "_get_runtime", None)
    if not callable(getter):
        return None
    node = getter("graph.node")
    if not isinstance(node, OperationNode):
        return None
    graph_id = node.graph_id
    get_metadata = getattr(value, "get_metadata", None)
    graph_payload = get_metadata("graph", None) if callable(get_metadata) else None
    if graph_id is None and isinstance(graph_payload, dict):
        raw_graph_id = graph_payload.get("graph_id")
        graph_id = str(raw_graph_id) if raw_graph_id else None
    return node, graph_id


def _walk_values(value: Any, seen: Set[int], *, deep: bool) -> Iterable[Any]:
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return
    value_id = id(value)
    if value_id in seen:
        return
    seen.add(value_id)
    yield value
    if _graph_node_and_id(value) is not None:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_values(key, seen, deep=deep)
            yield from _walk_values(item, seen, deep=deep)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _walk_values(item, seen, deep=deep)
    elif deep and is_dataclass(value) and not isinstance(value, OperationNode):
        for data_field in fields(value):
            if not data_field.name.startswith("_"):
                yield from _walk_values(
                    getattr(value, data_field.name), seen, deep=True
                )


def _graph_nodes_with_ids(
    value: Any, *, deep: bool = False
) -> Iterable[Tuple[OperationNode, Optional[str]]]:
    seen_nodes: Set[Tuple[Optional[str], str]] = set()
    for item in _walk_values(value, set(), deep=deep):
        found = _graph_node_and_id(item)
        if found is None:
            continue
        node, graph_id = found
        node_key = (graph_id, node.node_id)
        if node_key in seen_nodes:
            continue
        seen_nodes.add(node_key)
        yield node, graph_id


def _graph_nodes_in_value(value: Any, *, deep: bool = False) -> Iterable[OperationNode]:
    for node, _graph_id in _graph_nodes_with_ids(value, deep=deep):
        yield node




def _normalize_output_shapes(outputs: Any) -> List[Any]:
    if outputs is None:
        return []
    if isinstance(outputs, (list, tuple)):
        return list(outputs)
    return [outputs]


def _extract_input_nodes(
    inputs: Optional[Iterable[Any]], session: GraphSession
) -> List[OperationNode]:
    if not inputs:
        return []

    nodes: List[OperationNode] = []
    seen: Set[str] = set()
    for obj in inputs:
        external = session.external_definition_node(obj)
        candidates = ((external, session.graph.graph_id),) if external else _graph_nodes_with_ids(obj)
        for node, _graph_id in candidates:
            if node.node_id in seen:
                continue
            seen.add(node.node_id)
            nodes.append(session.owned_node(node))
    return nodes


def _validate_input_graph_ownership(
    inputs: Optional[Iterable[Any]], session: GraphSession
) -> None:
    for value in inputs or ():
        if session.external_definition_node(value) is not None:
            continue
        if session._allow_external_definitions and isinstance(value, (Part, Assembly)):
            definition_id = value.part_id if isinstance(value, Part) else value.assembly_id
            definition_kind = "single_solid" if isinstance(value, Part) else "assembly"
            revision = value._get_runtime("definition.revision")
            content_hash = value._get_runtime("definition.content_hash")
            if isinstance(revision, str) and isinstance(content_hash, str):
                session.register_external_definition(
                    value=value,
                    definition_kind=definition_kind,
                    definition_id=definition_id,
                    revision=revision,
                    content_hash=content_hash,
                )
                continue
        session.validate_graph_ownership(value)
        if isinstance(value, (Part, Assembly)) and _graph_node_and_id(value) is None:
            raise ValueError(
                f"unrecorded {type(value).__name__} cannot be used in active graph "
                f"'{session.graph.graph_id}'; build it inside this GraphSession"
            )


def _current_context_snapshot() -> Dict[str, Any]:
    cs = get_current_cs()
    return {
        "origin": tuple(float(v) for v in cs.origin),
        "x_axis": tuple(float(v) for v in cs.x_axis),
        "y_axis": tuple(float(v) for v in cs.y_axis),
        "z_axis": tuple(float(v) for v in cs.z_axis),
    }


def _current_frame(node_id: str) -> FrameNode:
    """The current coordinate system as the frame of node *node_id*."""

    cs = get_current_cs()
    return FrameNode(
        frame_id=f"frame:{node_id}",
        origin=_vector3(cs.origin),
        x_axis=_vector3(cs.x_axis),
        y_axis=_vector3(cs.y_axis),
        z_axis=_vector3(cs.z_axis),
        metadata={"node_id": node_id},
    )


def _vector3(values: Iterable[Any]) -> Tuple[float, float, float]:
    x, y, z = (float(v) for v in values)
    return (x, y, z)


def _shape_kind(shape: Any) -> Optional[TopoKind]:
    if isinstance(shape, Vertex):
        return TopoKind.VERTEX
    if isinstance(shape, Edge):
        return TopoKind.EDGE
    if isinstance(shape, Wire):
        return TopoKind.WIRE
    if isinstance(shape, Face):
        return TopoKind.FACE
    if isinstance(shape, Shell):
        return TopoKind.SHELL
    if isinstance(shape, Solid):
        return TopoKind.SOLID
    if isinstance(shape, Compound):
        return TopoKind.COMPOUND
    return None


def _wrapped_shape(shape: Any) -> Any:
    if isinstance(shape, (Vertex, Edge, Wire, Face, Shell, Solid, Compound)):
        return shape.wrapped
    return None


def _shape_topo_id(shape: Any) -> str:
    topo_id = getattr(shape, "topo_id", None)
    if topo_id is not None:
        kind = _shape_kind(shape)
        prefix = kind.name.lower() if kind is not None else "shape"
        return f"{prefix}_{topo_id}"
    wrapped = _wrapped_shape(shape)
    if wrapped is None:
        return f"obj_{id(shape)}"
    kind = _shape_kind(shape)
    prefix = kind.name.lower() if kind is not None else "shape"
    try:
        return f"{prefix}_{wrapped.HashCode(1000000)}"
    except AttributeError:
        return f"{prefix}_{hash(wrapped)}"


def _kernel_topo_id(shape: Any) -> str:
    wrapped = _wrapped_shape(shape)
    if wrapped is None:
        return f"obj_{id(shape)}"
    try:
        return str(wrapped.HashCode(1000000))
    except AttributeError:
        return str(hash(wrapped))


def _topology_wrappers(shape: Any) -> List[Any]:
    result: List[Any] = []
    seen_wrappers: Set[int] = set()
    queue = [shape]
    while queue:
        current = queue.pop(0)
        marker = id(current)
        if marker in seen_wrappers:
            continue
        seen_wrappers.add(marker)
        if _shape_kind(current) is not None:
            result.append(current)
        children = getattr(current, "get_children", None)
        if callable(children):
            queue.extend(children())
    return result


def _unique_ref_index(
    shapes: Iterable[Any],
    *,
    ref_factory: Optional[Callable[[Any, TopoKind], TopoRef]] = None,
) -> Dict[tuple[TopoKind, str], TopoRef]:
    candidates: Dict[tuple[TopoKind, str], List[TopoRef]] = {}
    for shape in shapes:
        for wrapper in _topology_wrappers(shape):
            kind = _shape_kind(wrapper)
            if kind is None:
                continue
            if ref_factory is None:
                ref = getattr(wrapper, "_get_runtime", lambda *_args: None)("topo.ref")
                if not isinstance(ref, TopoRef):
                    continue
            else:
                ref = ref_factory(wrapper, kind)
            key = (kind, _kernel_topo_id(wrapper))
            candidates.setdefault(key, []).append(ref)

    result: Dict[tuple[TopoKind, str], TopoRef] = {}
    for key, refs in candidates.items():
        unique = set(refs)
        if len(unique) > 1:
            raise ValueError(f"ambiguous topology identity for {key[0].name}:{key[1]}")
        result[key] = next(iter(unique))
    return result


def _canonicalize_recorded_topo_delta(
    delta: Optional[TopoDelta],
    *,
    graph_id: str,
    node_id: str,
    outputs: List[Any],
    inputs: Optional[Iterable[Any]],
) -> Optional[TopoDelta]:
    if delta is None:
        return None

    def output_ref_factory(slot: int):
        return lambda wrapper, kind: TopoRef(
            graph_id=graph_id,
            node_id=node_id,
            output_slot=slot,
            kind=kind,
            topo_id=_shape_topo_id(wrapper),
        )

    output_index: Dict[tuple[TopoKind, str], TopoRef] = {}
    for slot, output in enumerate(outputs):
        slot_index = _unique_ref_index([output], ref_factory=output_ref_factory(slot))
        for key, ref in slot_index.items():
            existing = output_index.get(key)
            if existing is not None and existing != ref:
                raise ValueError(
                    f"topology entity {key[0].name}:{key[1]} appears in multiple output slots"
                )
            output_index[key] = ref
    source_index = _unique_ref_index(inputs or ())

    def resolve(
        ref: TopoRef,
        *,
        source: bool,
        required: bool = True,
    ) -> TopoRef | None:
        index = source_index if source else output_index
        resolved = index.get((ref.kind, ref.topo_id))
        if resolved is not None:
            return resolved
        temporary_tracking_ref = ref.graph_id.startswith(
            "g_"
        ) and ref.node_id.startswith("n_")
        if temporary_tracking_ref:
            return None
        if ref.graph_id not in {"", "pending"} and ref.node_id not in {"", "pending"}:
            return ref
        if required:
            side = "source" if source else "result"
            raise ValueError(
                f"complete topology witness cannot resolve {side} {ref.kind.name}:{ref.topo_id}"
            )
        return ref

    def ref_key(ref: TopoRef) -> tuple[str, str, int, str, str]:
        return (
            ref.graph_id,
            ref.node_id,
            ref.output_slot,
            ref.kind.name,
            ref.topo_id,
        )

    def canonical_parents(refs: Iterable[TopoRef]) -> tuple[TopoRef, ...]:
        return tuple(sorted(refs, key=ref_key))

    entries = []
    for entry in delta.entries:
        complete = (
            str(entry.metadata.get("coverage", "complete")) == "complete"
            and str(entry.metadata.get("status", "proven")) == "proven"
        )
        resolved_ref = resolve(
            entry.ref,
            source=entry.event == TopoEvent.DELETED,
            required=complete,
        )
        resolved_parents = tuple(
            resolve(ref, source=True, required=complete) for ref in entry.parent_refs
        )
        if resolved_ref is None or any(ref is None for ref in resolved_parents):
            continue
        entries.append(
            TopoEntry(
                ref=resolved_ref,
                event=entry.event,
                origin_role=entry.origin_role,
                parent_refs=canonical_parents(
                    ref for ref in resolved_parents if ref is not None
                ),
                metadata=dict(entry.metadata),
            )
        )

    roles = []
    for role in delta.roles:
        complete = (
            str(role.metadata.get("coverage", "complete")) == "complete"
            and str(role.metadata.get("status", "proven")) == "proven"
        )
        resolved_ref = resolve(role.ref, source=False, required=complete)
        resolved_parents = tuple(
            resolve(ref, source=True, required=complete) for ref in role.parent_refs
        )
        if resolved_ref is None or any(ref is None for ref in resolved_parents):
            continue
        roles.append(
            TopoRoleEntry(
                ref=resolved_ref,
                role=role.role,
                origin_role=role.origin_role,
                parent_refs=canonical_parents(
                    ref for ref in resolved_parents if ref is not None
                ),
                metadata=dict(role.metadata),
            )
        )

    def resolve_many(refs: Iterable[TopoRef], *, source: bool) -> tuple[TopoRef, ...]:
        resolved = (resolve(ref, source=source) for ref in refs)
        return tuple(sorted((ref for ref in resolved if ref is not None), key=ref_key))

    entries.sort(
        key=lambda entry: (
            ref_key(entry.ref),
            entry.event.name,
            entry.origin_role or "",
            tuple(ref_key(ref) for ref in entry.parent_refs),
            json.dumps(entry.metadata, sort_keys=True, separators=(",", ":")),
        )
    )
    roles.sort(
        key=lambda role: (
            ref_key(role.ref),
            role.role,
            role.origin_role or "",
            tuple(ref_key(ref) for ref in role.parent_refs),
            json.dumps(role.metadata, sort_keys=True, separators=(",", ":")),
        )
    )

    def event_refs(event: TopoEvent) -> tuple[TopoRef, ...]:
        if not entries:
            source = event == TopoEvent.DELETED
            legacy = {
                TopoEvent.PRESERVED: delta.preserved,
                TopoEvent.MODIFIED: delta.modified,
                TopoEvent.GENERATED: delta.generated,
                TopoEvent.DELETED: delta.deleted,
            }[event]
            return resolve_many(legacy, source=source)
        return tuple(
            sorted(
                {entry.ref for entry in entries if entry.event == event},
                key=ref_key,
            )
        )

    return TopoDelta(
        preserved=event_refs(TopoEvent.PRESERVED),
        modified=event_refs(TopoEvent.MODIFIED),
        generated=event_refs(TopoEvent.GENERATED),
        deleted=event_refs(TopoEvent.DELETED),
        section_edges=resolve_many(delta.section_edges, source=False),
        entries=tuple(entries),
        roles=tuple(roles),
        raw_event=dict(delta.raw_event),
    )


def _attach_topo_refs_recursive(
    shape: Any,
    *,
    graph_id: str,
    node: OperationNode,
    output_slot: int,
) -> None:
    kind = _shape_kind(shape)
    if kind is None:
        return

    topo_ref = TopoRef(
        graph_id=graph_id,
        node_id=node.node_id,
        output_slot=output_slot,
        kind=kind,
        topo_id=_shape_topo_id(shape),
    )

    setter = getattr(shape, "_set_runtime", None)
    if callable(setter):
        setter("topo.ref", topo_ref)
        setter("topo.kind", kind.name)
        setter("topo.id", topo_ref.topo_id)

    set_metadata = getattr(shape, "set_metadata", None)
    if callable(set_metadata):
        set_metadata("topo_ref", topo_ref_to_dict(topo_ref))

    children = getattr(shape, "get_children", None)
    if callable(children):
        for child in children():
            _attach_topo_refs_recursive(
                child,
                graph_id=graph_id,
                node=node,
                output_slot=output_slot,
            )


def attach_graph_node(
    output: Any,
    node: OperationNode,
    output_slot: int = 0,
    graph_id: Optional[str] = None,
) -> Any:
    """Attach graph-node lineage to a shape-like object.

    The attachment is intentionally stored in runtime state plus lightweight
    metadata so later operations can discover upstream node identity without
    changing the public API.
    """

    if output is None:
        return output

    setter = getattr(output, "_set_runtime", None)
    if callable(setter):
        setter("graph.node", node)
        setter("graph.node_id", node.node_id)
        setter("graph.output_slot", output_slot)

    set_metadata = getattr(output, "set_metadata", None)
    effective_graph_id = graph_id
    if effective_graph_id is None:
        active = get_active_session()
        effective_graph_id = active.graph.graph_id if active is not None else ""

    if callable(set_metadata):
        set_metadata(
            "graph",
            {
                "graph_id": effective_graph_id or None,
                "node_id": node.node_id,
                "op": node.op,
                "output_slot": output_slot,
            },
        )

    if effective_graph_id:
        _attach_topo_refs_recursive(
            output,
            graph_id=effective_graph_id,
            node=node,
            output_slot=output_slot,
        )

    return output


def attach_semantic_graph_node(
    output: Any,
    node: OperationNode,
    output_slot: int = 0,
    graph_id: Optional[str] = None,
) -> Any:
    """Attach semantic graph lineage without replacing geometry topology refs."""

    if output is None:
        return output

    setter = getattr(output, "_set_runtime", None)
    if callable(setter):
        setter("graph.node", node)
        setter("graph.node_id", node.node_id)
        setter("graph.output_slot", output_slot)

    effective_graph_id = graph_id
    if effective_graph_id is None:
        active = get_active_session()
        effective_graph_id = active.graph.graph_id if active is not None else ""

    set_metadata = getattr(output, "set_metadata", None)
    if callable(set_metadata):
        set_metadata(
            "graph",
            {
                "graph_id": effective_graph_id or None,
                "node_id": node.node_id,
                "op": node.op,
                "output_slot": output_slot,
            },
        )
    return output


def record_operation_if_active(
    op: str,
    params: Optional[Dict[str, Any]] = None,
    outputs: Any = None,
    input_shapes: Optional[Iterable[Any]] = None,
    semantic_delta: Optional[SemanticDelta] = None,
    topo_delta: Optional[TopoDelta] = None,
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[Set[str]] = None,
    source: Optional[Dict[str, Any]] = None,
) -> Optional[OperationNode]:
    """Record an operation only when a session is active.

    This is the seamless bridge used by the original modeling APIs.
    Users keep calling `make_box_rsolid(...)` or `cut_rsolid(...)`; when a
    graph session exists, the operation is recorded automatically and its
    outputs are annotated with hidden lineage state.
    """

    session = get_active_session()
    if session is None or _recording_suspend_depth_var.get() > 0:
        return None

    numeric_params, param_exprs = canonicalize_params(params, session.expression_graph)
    output_list = _normalize_output_shapes(outputs)
    input_list = list(input_shapes or ())
    _validate_input_graph_ownership(input_list, session)
    input_nodes = _extract_input_nodes(input_list, session)
    node_id = session.graph.allocate_node_id()
    frame = _current_frame(node_id)
    canonical_topo_delta = _canonicalize_recorded_topo_delta(
        topo_delta,
        graph_id=session.graph.graph_id,
        node_id=node_id,
        outputs=output_list,
        inputs=input_list,
    )
    node = session.graph.add_node(
        op=op,
        params=numeric_params,
        param_exprs=param_exprs or None,
        inputs=input_nodes or None,
        node_id=node_id,
        output_count=len(output_list),
        semantic_delta=semantic_delta,
        topo_delta=canonical_topo_delta,
        context=context or _current_context_snapshot(),
        tags=tags,
        source=(source if source is not None else capture_source_provenance()),
        expressions=referenced_expressions(param_exprs, session.expression_graph),
        frame=frame,
    )
    session.frame_graph.add(frame)

    for idx, output in enumerate(output_list):
        attach_graph_node(
            output, node, output_slot=idx, graph_id=session.graph.graph_id
        )

    return node


def record_operation(
    op: str,
    params: Optional[Dict[str, Any]] = None,
    inputs: Optional[List[OperationNode]] = None,
    node_id: Optional[str] = None,
    output_count: int = 1,
    semantic_delta: Optional[SemanticDelta] = None,
    topo_delta: Optional[TopoDelta] = None,
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[Set[str]] = None,
    source: Optional[Dict[str, Any]] = None,
) -> OperationNode:
    """Record an operation to the active graph session.

    Args:
        op: Operation type (e.g. ``"make_box"``, ``"cut"``).
        params: Operation parameters (serialisable).
        inputs: Upstream nodes whose outputs feed into this node.
        node_id: Optional explicit node id.
        output_count: Number of output shapes.
        topo_delta: Optional topological change set from tracking.
        context: Optional work-plane / coordinate-system snapshot.
        tags: Optional free-form labels.

    Returns:
        The created :class:`OperationNode`.

    Raises:
        RuntimeError: If no active session exists.
    """
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "No active GraphSession. Use `with GraphSession() as session:` "
            "or call `session.start()` before recording."
        )
    numeric_params, param_exprs = canonicalize_params(params, session.expression_graph)
    resolved_id = node_id or session.graph.allocate_node_id()
    frame = _current_frame(resolved_id)
    node = session.graph.add_node(
        op=op,
        params=numeric_params,
        param_exprs=param_exprs or None,
        inputs=[session.owned_node(item) for item in inputs or ()],
        node_id=resolved_id,
        output_count=output_count,
        semantic_delta=semantic_delta,
        topo_delta=topo_delta,
        context=context,
        tags=tags,
        source=(source if source is not None else capture_source_provenance()),
        expressions=referenced_expressions(param_exprs, session.expression_graph),
        frame=frame,
    )
    session.frame_graph.add(frame)
    return node

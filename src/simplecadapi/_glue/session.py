"""``GraphSession`` for the layers that stay Python (notebook runtime, build, artifacts).

The C++ session records shape operations.  The notebook runtime needs more of
the Python session's contract:

* ``shared_lineage``: a cell session accepts values that other cell sessions
  recorded.  The C++ session finds the producing node in a process-wide
  registry (``find_registered_node``) and adopts it; this class does the same
  for the Python-side checks (``validate_graph_ownership``, ``capture_result``);
* ``allow_external_definitions``: a built ``Part``/``Assembly`` that carries its
  own definition enters as a ``reference_definition`` node;
* detached sessions restored from a feature graph, whose ``graph``,
  ``expression_graph`` and ``frame_graph`` are assigned;
* product values (``Part``, ``Assembly``, ...) are graph values: they carry the
  node that produced them (``attach_graph_node``) and the nodes of the values
  they were made from are inputs of the node of an operation on them.
"""

from __future__ import annotations

import dataclasses
import functools
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import simplecadapi._cpp as _n

_Base = _n.GraphSession
_graph_get = _Base.__dict__["graph"].fget
_expression_get = _Base.__dict__["expression_graph"].fget
_frame_get = _Base.__dict__["frame_graph"].fget
_results_get = _Base.__dict__["result_node_ids"].fget


def lineage_of(value: Any) -> Optional[Tuple[str, str]]:
    """``(graph_id, node_id)`` of the node that produced *value*, if it is a recorded output."""

    getter = getattr(value, "_get_runtime", None)
    if not callable(getter):
        return None
    node_id = getter("graph.node_id")
    if not isinstance(node_id, str) or not node_id:
        return None
    graph_id = getter("graph.id")
    if not isinstance(graph_id, str):
        payload = value.get_metadata("graph", None) if hasattr(value, "get_metadata") else None
        graph_id = str(payload.get("graph_id") or "") if isinstance(payload, dict) else ""
    return graph_id, node_id


def _children(item: Any) -> Iterable[Any]:
    kind = type(item).__name__
    if kind == "Part":
        yield item.body
        yield from item.connectors
        if item.material is not None:
            yield item.material
    elif kind == "Assembly":
        yield from item.components
        yield from item.constraints
    elif kind == "Component":
        yield item.item
        yield item.placement
    elif kind == "Connector":
        yield item.placement if hasattr(item, "placement") else None


def walk_values(value: Any, *, deep: bool, seen: Optional[Set[int]] = None) -> Iterable[Any]:
    """The values inside *value* (containers and, when *deep*, product values)."""

    if seen is None:
        seen = set()
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return
    if id(value) in seen:
        return
    seen.add(id(value))
    yield value
    if lineage_of(value) is not None:
        return  # a recorded value stands for everything upstream of it
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk_values(key, deep=deep, seen=seen)
            yield from walk_values(item, deep=deep, seen=seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from walk_values(item, deep=deep, seen=seen)
    elif deep:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):  # a result wrapped in the caller's own dataclass
            for field in dataclasses.fields(value):
                if not field.name.startswith("_"):
                    yield from walk_values(getattr(value, field.name), deep=True, seen=seen)
        for child in _children(value):
            yield from walk_values(child, deep=True, seen=seen)


class GraphSession(_Base):
    """Context manager that records CAD operations into a DAG (see the module docstring)."""

    def __init__(
        self,
        graph_id: Optional[str] = None,
        *,
        allow_external_definitions: bool = False,
        namespace: Optional[str] = None,
        shared_lineage: bool = False,
        **options: Any,
    ) -> None:
        from ..recording.source_mapping import capture_source_provenance

        options.setdefault("source_provider", capture_source_provenance)
        super().__init__(
            graph_id,
            allow_external_definitions=bool(allow_external_definitions),
            namespace=namespace,
            shared_lineage=bool(shared_lineage),
            **options,
        )
        from ..params.tolerance import ToleranceGraph

        self._allow_external_definitions = bool(allow_external_definitions)
        self._shared_lineage = bool(shared_lineage)
        self._graph: Any = None
        self._expression_graph: Any = None
        self._frame_graph: Any = None
        self._result_node_ids: List[str] = []
        self._has_explicit_results = False
        self._captured_values: List[Any] = []
        self._external_definition_nodes: Dict[int, Any] = {}
        self._external_definition_nodes_by_id: Dict[str, Any] = {}
        self.tolerance_graph = ToleranceGraph(self.expression_graph)

    # -- graphs (a restored session replaces them) -----------------------------------------

    @property
    def graph(self) -> Any:
        return self._graph if self._graph is not None else _graph_get(self)

    @graph.setter
    def graph(self, value: Any) -> None:
        self._graph = value

    @property
    def expression_graph(self) -> Any:
        return self._expression_graph if self._expression_graph is not None else _expression_get(self)

    @expression_graph.setter
    def expression_graph(self, value: Any) -> None:
        self._expression_graph = value

    @property
    def frame_graph(self) -> Any:
        return self._frame_graph if self._frame_graph is not None else _frame_get(self)

    @frame_graph.setter
    def frame_graph(self, value: Any) -> None:
        self._frame_graph = value

    # -- lineage ---------------------------------------------------------------------------

    def owned_node(self, node: Any) -> Any:
        """This session's graph node for *node* (adopted when the lineage is shared)."""

        if self._shared_lineage:
            return self.graph.adopt(node)
        if self.graph.get_node(node.node_id) is not node:
            raise ValueError(
                f"graph node '{node.node_id}' is not owned by active graph '{self.graph.graph_id}'"
            )
        return node

    def _node_of(self, graph_id: str, node_id: str) -> Any:
        graph = self.graph
        if graph_id not in ("", None, graph.graph_id):
            raise ValueError(
                f"value contains graph node '{node_id}' from graph '{graph_id}', "
                f"active graph is '{graph.graph_id}'"
            )
        node = graph.get_node(node_id)
        if node is None and self._shared_lineage:
            foreign = _n.find_registered_node(graph.graph_id, node_id)
            if foreign is not None:
                node = graph.adopt(foreign)
        if node is None:
            raise ValueError(
                f"value contains graph node '{node_id}' not owned by active graph '{graph.graph_id}'"
            )
        return node

    def validate_graph_ownership(self, value: Any) -> None:
        """Reject values carrying lineage from a different graph (adopt it when shared)."""

        for item in walk_values(value, deep=True):
            found = lineage_of(item)
            if found is not None:
                self._node_of(*found)
            getter = getattr(item, "_get_runtime", None)
            topo_ref = getter("topo.ref") if callable(getter) else None
            if topo_ref is None or not hasattr(topo_ref, "topo_id"):
                continue
            if topo_ref.graph_id != self.graph.graph_id:
                raise ValueError(
                    f"value contains topology reference '{topo_ref.topo_id}' from "
                    f"graph '{topo_ref.graph_id}', active graph is '{self.graph.graph_id}'"
                )
            if self.graph.get_node(topo_ref.node_id) is None:
                raise ValueError(
                    f"value contains topology reference '{topo_ref.topo_id}' for "
                    f"unknown node '{topo_ref.node_id}'"
                )

    def lineage_nodes(self, value: Any, *, deep: bool = False) -> List[Any]:
        """The nodes (in this graph) of the recorded values inside *value*."""

        nodes: List[Any] = []
        seen: Set[str] = set()
        for item in walk_values(value, deep=deep):
            found = lineage_of(item)
            if found is None or found[1] in seen:
                continue
            seen.add(found[1])
            nodes.append(self._node_of(*found))
        return nodes

    # -- external definitions ----------------------------------------------------------------

    def register_external_definition(
        self,
        *,
        value: Any,
        definition_kind: str,
        definition_id: str,
        revision: str,
        content_hash: str,
    ) -> Any:
        """Represent one immutable child definition without importing its DAG."""

        marker = id(value)
        existing = self._external_definition_nodes.get(marker)
        if existing is not None:
            return existing
        is_part = type(value).__name__ == "Part"
        expected_id = value.part_id if is_part else value.assembly_id
        expected_kind = "single_solid" if is_part else "assembly"
        if expected_id != definition_id or expected_kind != definition_kind:
            raise ValueError("external definition runtime identity differs")
        node_id: Optional[str] = None
        if self._shared_lineage:
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
            semantic_delta=_n.SemanticDelta(
                created=(
                    _n.SemanticRef(
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
        if self._shared_lineage:
            _n.register_node(node)
        self._external_definition_nodes[marker] = node
        self._external_definition_nodes_by_id[definition_id] = node
        return node

    def external_definition_node(self, value: Any) -> Any:
        direct = self._external_definition_nodes.get(id(value))
        if direct is not None:
            return direct
        kind = type(value).__name__
        if kind == "Part":
            return self._external_definition_nodes_by_id.get(value.part_id)
        if kind == "Assembly":
            return self._external_definition_nodes_by_id.get(value.assembly_id)
        return None

    # -- tolerance requirements ----------------------------------------------------------------

    def require_tolerance(
        self,
        value: Any,
        tolerance: Any,
        *,
        method: str = "worst_case",
        name: Optional[str] = None,
        requirement_id: Optional[str] = None,
        tolerance_unit: Any = None,
    ) -> Any:
        """Declare a persisted Length or Angle manufacturing requirement."""

        return self.tolerance_graph.require(
            value,
            tolerance,
            method=method,
            name=name,
            requirement_id=(
                self.allocate_object_id("tolreq") if requirement_id is None else requirement_id
            ),
            tolerance_unit=tolerance_unit,
        )

    def validate_tolerances(self, *, raise_on_failure: bool = False) -> Any:
        return self.tolerance_graph.validate(raise_on_failure=raise_on_failure)

    # -- results -----------------------------------------------------------------------------------

    @property
    def result_node_ids(self) -> Tuple[str, ...]:
        return tuple(self._result_node_ids)

    @property
    def has_explicit_results(self) -> bool:
        return self._has_explicit_results

    @property
    def captured_values(self) -> Tuple[Any, ...]:
        return tuple(self._captured_values)

    def capture_result(self, *, value: Any) -> Any:
        self.validate_graph_ownership(value)
        nodes = self.lineage_nodes(value, deep=True)
        if not nodes:
            raise ValueError(
                "capture_result() requires a value containing at least one "
                "graph-backed shape or semantic value"
            )
        self._has_explicit_results = True
        for node in nodes:
            if node.node_id not in self._result_node_ids:
                self._result_node_ids.append(node.node_id)
        self._captured_values.append(value)
        return value

    def clear_results(self) -> None:
        self._result_node_ids.clear()
        self._has_explicit_results = False
        self._captured_values.clear()


# ---------------------------------------------------------------------------
# Recording operations on values (Parts, Assemblies, ...), from Python
# ---------------------------------------------------------------------------


def attach_semantic_graph_node(
    output: Any, node: Any, output_slot: int = 0, graph_id: Optional[str] = None
) -> Any:
    """Re-attribute *output* to *node* without renaming what it contains (a tag assignment)."""

    keep = getattr(output, "_keep_topology_owner", None)
    if callable(keep):
        keep()
    return attach_graph_node(output, node, output_slot, graph_id)


def attach_graph_node(
    output: Any, node: Any, output_slot: int = 0, graph_id: Optional[str] = None
) -> Any:
    """Record on *output* which graph node produced it (the keys the C++ recorder writes).

    Topology references of sub-shapes are derived from the root's lineage on
    demand (``topo_ref_of``), so nothing is stamped on the entities here.
    """

    if output is None:
        return output
    effective = graph_id
    if effective is None:
        active = _n.get_active_session()
        effective = active.graph.graph_id if active is not None else ""
    setter = getattr(output, "_set_runtime", None)
    if callable(setter):
        setter("graph.node_id", node.node_id)
        setter("graph.id", effective or "")
        setter("graph.output_slot", output_slot)
    set_metadata = getattr(output, "set_metadata", None)
    if callable(set_metadata):
        set_metadata(
            "graph",
            {
                "graph_id": effective or None,
                "node_id": node.node_id,
                "op": node.op,
                "output_slot": output_slot,
            },
        )
    return output


def _input_nodes(session: GraphSession, values: Iterable[Any], *, shapes: bool) -> List[Any]:
    nodes: List[Any] = []
    seen: Set[str] = set()
    for value in values:
        external = session.external_definition_node(value)
        if external is None and session._allow_external_definitions:
            kind = type(value).__name__
            if kind in ("Part", "Assembly"):
                revision = value._get_runtime("definition.revision")
                content_hash = value._get_runtime("definition.content_hash")
                if isinstance(revision, str) and isinstance(content_hash, str):
                    external = session.register_external_definition(
                        value=value,
                        definition_kind="single_solid" if kind == "Part" else "assembly",
                        definition_id=value.part_id if kind == "Part" else value.assembly_id,
                        revision=revision,
                        content_hash=content_hash,
                    )
        found = [external] if external is not None else []
        if external is None and not shapes and type(value).__name__ in ("Part", "Assembly") and lineage_of(value) is None:
            raise ValueError(
                f"unrecorded {type(value).__name__} cannot be used in active graph "
                f"'{session.graph.graph_id}'; build it inside this GraphSession"
            )
        if not found:
            for item in walk_values(value, deep=False):
                if not shapes and isinstance(item, _n.AnyShape):
                    continue
                lineage = lineage_of(item)
                if lineage is not None:
                    found.append(session._node_of(*lineage))
        for node in found:
            if node.node_id not in seen:
                seen.add(node.node_id)
                nodes.append(session.owned_node(node) if node is external else node)
    return nodes


def _frame(node_id: str) -> Any:
    cs = _n.get_current_cs()
    return _n.FrameNode(
        frame_id=f"frame:{node_id}",
        origin=tuple(float(v) for v in cs.origin),
        x_axis=tuple(float(v) for v in cs.x_axis),
        y_axis=tuple(float(v) for v in cs.y_axis),
        z_axis=tuple(float(v) for v in cs.z_axis),
        metadata={"node_id": node_id},
    )


def _context() -> Dict[str, Any]:
    cs = _n.get_current_cs()
    return {
        "origin": tuple(float(v) for v in cs.origin),
        "x_axis": tuple(float(v) for v in cs.x_axis),
        "y_axis": tuple(float(v) for v in cs.y_axis),
        "z_axis": tuple(float(v) for v in cs.z_axis),
    }


def record_operation_if_active(
    op: str,
    params: Optional[Dict[str, Any]] = None,
    outputs: Any = None,
    input_shapes: Optional[Iterable[Any]] = None,
    semantic_delta: Any = None,
    topo_delta: Any = None,
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[Set[str]] = None,
    source: Optional[Dict[str, Any]] = None,
) -> Any:
    """Record an operation only when a session is active (outputs and inputs may be product values)."""

    if not _n.recording_active():
        return None
    session = _n.get_active_session()
    from ..recording.source_mapping import capture_source_provenance

    numeric, exprs = _n.canonicalize_params(params or {}, session.expression_graph)
    if outputs is None:
        output_list: List[Any] = []
    elif isinstance(outputs, (list, tuple)):
        output_list = list(outputs)
    else:
        output_list = [outputs]
    input_nodes = _input_nodes(session, list(input_shapes or ()), shapes=True)
    node_id = session.graph.allocate_node_id()
    frame = _frame(node_id)
    node = session.graph.add_node(
        op=op,
        params=numeric,
        param_exprs=exprs or None,
        inputs=input_nodes or None,
        node_id=node_id,
        output_count=1 if outputs is None else len(output_list),  # a value op holds one output; an empty list result none
        semantic_delta=semantic_delta,
        context=context or _context(),
        tags=tags,
        source=(source if source is not None else capture_source_provenance()),
        expressions=_n.referenced_expressions(exprs, session.expression_graph),
        frame=frame,
    )
    session.frame_graph.add(frame)
    if session.shared_lineage:
        _n.register_node(node)
    for slot, output in enumerate(output_list):
        attach_graph_node(output, node, output_slot=slot, graph_id=session.graph.graph_id)
    return node


def record_operation(
    op: str,
    params: Optional[Dict[str, Any]] = None,
    inputs: Optional[List[Any]] = None,
    node_id: Optional[str] = None,
    output_count: int = 1,
    semantic_delta: Any = None,
    topo_delta: Any = None,
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[Set[str]] = None,
    source: Optional[Dict[str, Any]] = None,
) -> Any:
    """Record an operation to the active graph session (explicit input nodes)."""

    session = _n.get_active_session()
    if session is None:
        raise RuntimeError(
            "No active GraphSession. Use `with GraphSession() as session:` "
            "or call `session.start()` before recording."
        )
    from ..recording.source_mapping import capture_source_provenance

    numeric, exprs = _n.canonicalize_params(params or {}, session.expression_graph)
    resolved_id = node_id or session.graph.allocate_node_id()
    frame = _frame(resolved_id)
    node = session.graph.add_node(
        op=op,
        params=numeric,
        param_exprs=exprs or None,
        inputs=[session.owned_node(item) for item in inputs or ()],
        node_id=resolved_id,
        output_count=output_count,
        semantic_delta=semantic_delta,
        context=context,
        tags=tags,
        source=(source if source is not None else capture_source_provenance()),
        expressions=_n.referenced_expressions(exprs, session.expression_graph),
        frame=frame,
    )
    session.frame_graph.add(frame)
    if session.shared_lineage:
        _n.register_node(node)
    return node


# ---------------------------------------------------------------------------
# The product operators: values in, values out
# ---------------------------------------------------------------------------

_PRODUCT_OPS = (
    "make_material_rmaterial",
    "make_placement_rplacement",
    "identity_placement_rplacement",
    "make_part_rpart",
    "assign_material_rpart",
    "make_assembly_rassembly",
    "add_component_rassembly",
    "place_component_rassembly",
    "make_face_connector_rconnector",
    "make_edge_connector_rconnector",
    "make_vertex_connector_rconnector",
    "make_placement_connector_rconnector",
    "add_connector_rpart",
    "set_public_connector_rassembly",
    "make_connector_ref_rconnectorref",
    "make_scalar_limit_rscalarlimit",
    "ground_component_rassembly",
    "unground_component_rassembly",
    "add_fixed_constraint_rassembly",
    "add_revolute_constraint_rassembly",
    "add_prismatic_constraint_rassembly",
    "add_gear_constraint_rassembly",
    "add_belt_constraint_rassembly",
    "add_rack_pinion_constraint_rassembly",
    "solve_assembly_constraints_rassembly",
    "make_compound_from_assembly_rcompound",
)


def _wrap_product_op(function: Any) -> Any:
    from .compat import signature_of

    signature = signature_of(function)

    @functools.wraps(function)
    def operator(*args: Any, **kwargs: Any) -> Any:
        if not _n.recording_active():
            return function(*args, **kwargs)
        session = _n.get_active_session()
        before = session.last_node
        try:
            session._expect_value_op(
                _input_nodes(session, [*args, *kwargs.values()], shapes=False), True
            )
            result = function(*args, **kwargs)
        finally:
            session._clear_value_op()
        node = session.last_node
        if node is not None and node is not before and not isinstance(result, _n.AnyShape):
            attach_graph_node(result, node, output_slot=0, graph_id=session.graph.graph_id)
        return result

    if signature is not None:
        operator.__signature__ = signature  # type: ignore[attr-defined]
    return operator


def _sketch_ops(nat: Any) -> List[str]:
    """The operators that take a Sketch and give one back (or a shape built from one)."""

    names = [name for name in dir(nat) if name.endswith("_rsketch")]
    return names + ["make_face_from_sketch_rface", "make_wire_from_sketch_rwire"]


def install_product_operators(nat: Any) -> None:
    for name in (*_PRODUCT_OPS, *_sketch_ops(nat)):
        setattr(nat, name, _wrap_product_op(getattr(nat, name)))

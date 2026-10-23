"""``_topology_cache`` for native shapes: the entity table the artifact layer reads and writes.

``artifacts/topology_snapshot.py`` captures and restores the semantic state of
every topology entity of a body (tags, tag bindings, lineage, metadata,
incidence, the feature output an entity came from).  The Python wrappers keep
that state in ``_TopoEntity`` records; here the records are views over the
native handles: reading goes to the handle, writing to its setters.  Entity
ids are the native ones (``face_3``: the index in the root's ``TopExp`` map),
which a body decoded from the same BRep bytes reproduces.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import simplecadapi._cpp as _n


def topo_ref_of(handle: Any) -> Any:
    """The ``TopoRef`` of an entity of a recorded output (the SDK names its id ``<kind>_<topo id>``)."""

    data = handle._topo_ref()
    if data is None:
        return None
    from ..topology.model import TopoKind, TopoRef

    kind = TopoKind[str(data["kind"]).upper()]
    topo_id = str(data["topo_id"])
    if not topo_id.startswith(kind.name.lower() + "_" + kind.name.lower() + "_"):
        topo_id = f"{kind.name.lower()}_{topo_id}"
    return TopoRef(
        graph_id=data["graph_id"],
        node_id=data["node_id"],
        output_slot=int(data["output_slot"]),
        kind=kind,
        topo_id=topo_id,
    )


class _RuntimeView:
    """``entity.runtime``: the handle's runtime dictionary, ``topo.ref`` as a ``TopoRef``."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    def get(self, key: str, default: Any = None) -> Any:
        if key == "topo.ref":
            ref = topo_ref_of(self._handle)
            return default if ref is None else ref
        return self._handle._get_runtime(key, default)

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "topo.ref":
            # The stamped form (what the recorder writes with attach_topology_refs): kind in lower case.
            value = {
                "graph_id": value.graph_id,
                "node_id": value.node_id,
                "output_slot": value.output_slot,
                "kind": value.kind.name.lower(),
                "topo_id": value.topo_id,
            }
        self._handle._set_runtime(key, value)

    def pop(self, key: str, default: Any = None) -> Any:
        # The runtime has no deletion; a restore only removes entries it has not written yet.
        return default


class _Entity:
    """One topology entity of a root, with the fields of ``core._TopoEntity``."""

    def __init__(self, handle: Any, kind: str) -> None:
        self.handle = handle
        self.kind = kind
        self.incident_face_ids: set = set()
        self.incident_edge_ids: set = set()
        self.runtime = _RuntimeView(handle)
        self._tag_override: Optional[set] = None

    @property
    def topo_id(self) -> str:
        return self.handle.topo_id

    @topo_id.setter
    def topo_id(self, value: str) -> None:
        if value != self.handle.topo_id:
            raise ValueError(
                f"native topology ids come from the shape ({self.handle.topo_id}); "
                f"cannot restore {value}"
            )

    @property
    def wrappers(self) -> list:
        """The shape objects standing for this entity: the native handle is the only one."""
        return [self.handle]

    @property
    def representative(self) -> Any:
        return self.handle  # the native handle: its geometry is measured, not decoded

    @property
    def tags(self) -> set:
        return _TagSet(self.handle)

    @property
    def tag_bindings(self) -> "_BindingList":
        return _BindingList(self.handle)

    @property
    def tag_lineage(self) -> "_LineageList":
        return _LineageList(self.handle)

    @property
    def metadata(self) -> "_MetadataView":
        return _MetadataView(self.handle)


class _TagSet(set):
    """A snapshot of the tag names whose ``clear``/``update`` write through."""

    def __init__(self, handle: Any) -> None:
        super().__init__(handle._tags)
        self._handle = handle

    def clear(self) -> None:
        super().clear()

    def update(self, *others: Iterable[str]) -> None:
        super().update(*others)
        if set(self) != set(self._handle._tags):
            self._handle._tags = set(self)


class _BindingList(list):
    def __init__(self, handle: Any) -> None:
        super().__init__(handle._local_tag_bindings())
        self._handle = handle

    def __setitem__(self, index: Any, value: Any) -> None:
        if isinstance(index, slice) and index == slice(None):
            self._handle._replace_local_tag_bindings(list(value))
            super().__setitem__(index, value)
        else:
            super().__setitem__(index, value)


class _LineageList(list):
    def __init__(self, handle: Any) -> None:
        super().__init__(handle._tag_lineage)
        self._handle = handle

    def __setitem__(self, index: Any, value: Any) -> None:
        if isinstance(index, slice) and index == slice(None):
            for witness in value:
                self._handle._add_tag_lineage(
                    witness.binding,
                    derivation=str(getattr(witness.derivation, "value", witness.derivation)),
                    source_topo_id=witness.source_topo_id,
                    evidence=witness.evidence,
                    coverage=witness.coverage,
                )
        super().__setitem__(index, value)


class _MetadataView(dict):
    def __init__(self, handle: Any) -> None:
        super().__init__(handle._metadata_dict())
        self._handle = handle

    def clear(self) -> None:
        super().clear()

    def update(self, other: Any = (), /, **kwargs: Any) -> None:
        data = dict(other, **kwargs)
        for key, value in data.items():
            self._handle.set_metadata(key, value)
        super().update(data)


class TopologyCache:
    """The entities of one root, in a stable order (``entities()``) and by id."""

    def __init__(self, root: Any) -> None:
        self.root = root
        self._entities: Optional[List[_Entity]] = None
        self._by_id: Dict[str, _Entity] = {}

    def _build(self) -> None:
        entities: Dict[str, _Entity] = {}

        def add(handle: Any, kind: str) -> _Entity:
            entity = entities.get(handle.topo_id)
            if entity is None:
                entity = entities[handle.topo_id] = _Entity(handle, kind)
            return entity

        root = self.root
        kind = type(root).__name__.lower()
        add(root, kind)
        solids = [root] if kind == "solid" else (list(root._iter_solids()) if kind == "compound" else [])
        faces = (
            [root] if kind == "face" else
            [f for solid in solids for f in solid._iter_faces()] if solids else
            (list(root._iter_faces()) if kind == "shell" else [])
        )
        for solid in solids:
            if solid is not root:
                add(solid, "solid")
        for face in faces:
            face_entity = add(face, "face")
            outer = face.get_outer_wire() if hasattr(face, "get_outer_wire") else None
            wires = [(outer, True)] if outer is not None else []
            wires += [(wire, False) for wire in face._iter_inner_wires()]
            for wire, _outer in wires:
                wire_entity = add(wire, "wire")
                wire_entity.incident_face_ids.add(face.topo_id)
                for edge in wire._iter_edges():
                    edge_entity = add(edge, "edge")
                    edge_entity.incident_face_ids.add(face.topo_id)
                    for vertex in edge._iter_vertices():
                        vertex_entity = add(vertex, "vertex")
                        vertex_entity.incident_edge_ids.add(edge.topo_id)
            del face_entity
        self._entities = list(entities.values())
        self._by_id = dict(entities)

    def entities(self, kind: Optional[str] = None) -> List[_Entity]:
        if self._entities is None:
            self._build()
        assert self._entities is not None
        if kind is None:
            return list(self._entities)
        return [entity for entity in self._entities if entity.kind == kind]

    @property
    def _entities_by_id(self) -> Dict[str, _Entity]:
        if self._entities is None:
            self._build()
        return self._by_id

    @_entities_by_id.setter
    def _entities_by_id(self, value: Dict[str, _Entity]) -> None:
        self._by_id = dict(value)

    def wrappers_for(self, topo_id: str) -> List[Any]:
        entity = self._entities_by_id.get(topo_id)
        return [entity.handle] if entity is not None else []


def _restore_shape_with_node(deserialize: Any, args: Tuple[Any, ...], node: Any) -> Any:
    from .graph_nodes import share_node

    shape = deserialize(*args)
    shape._attach_node(share_node(node))
    return shape


def _n_active_session() -> Any:
    import simplecadapi._cpp as native

    return native.get_active_session()


def install(nat: Any) -> None:
    def topology_cache(self: Any) -> TopologyCache:
        return TopologyCache(self)

    for name in ("Vertex", "Edge", "Wire", "Face", "Shell", "Solid", "Compound"):
        cls = getattr(nat, name)
        cls._topology_cache = property(topology_cache)
        original = cls._get_runtime

        def get_runtime(self: Any, key: str, default: Any = None, _get=original) -> Any:
            if key == "topo.ref":
                found = _get(self, key, None)
                if found is None:
                    ref = topo_ref_of(self)
                    return default if ref is None else ref
                return topo_ref_of(self) or default
            return _get(self, key, default)

        cls._get_runtime = get_runtime
        original_reduce = cls.__reduce__

        def reduce(self: Any, _reduce=original_reduce, _get=get_runtime) -> Any:
            restore, args = _reduce(self)
            node = _get(self, "graph.node", None)
            return (restore, args) if node is None else (_restore_shape_with_node, (restore, args, node))

        cls.__reduce__ = reduce
        original_set = cls._set_runtime

        def set_runtime(self: Any, key: str, value: Any, _set=original_set) -> None:
            if key == "topo.ref" and hasattr(value, "topo_id") and hasattr(value, "kind"):
                value = {  # the stamped form: kind in lower case
                    "graph_id": value.graph_id,
                    "node_id": value.node_id,
                    "output_slot": value.output_slot,
                    "kind": value.kind.name.lower(),
                    "topo_id": value.topo_id,
                }
            _set(self, key, value)

        cls._set_runtime = set_runtime

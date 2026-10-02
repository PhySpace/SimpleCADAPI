"""Pickle support for the topology wrappers (Vertex … Compound).

The notebook runtime caches cell results with pickle, and OCP handles
cannot be pickled. A wrapper is therefore reduced to two things:

* the exact kernel shape, as BinTools bytes (every double bit-exact, so the
  restored geometry is identical to the one that was built), and
* the semantic state of every topology entity under the root — tags, tag
  bindings, tag lineage, metadata, runtime lineage and ``topo_id`` — keyed by
  the entity's position in the root's ``TopExp.MapShapes`` index map.

Restoring rebuilds the wrapper tree through the normal constructor (which
also recomputes derived data such as the default mesh) and then puts the
saved state back on the entities at the same positions. BinTools keeps the
sub-shape order, so the positions line up one to one.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Set, Tuple

from OCP.BinTools import BinTools, BinTools_FormatVersion
from OCP.TopAbs import (
    TopAbs_COMPOUND,
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_ShapeEnum,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS_Shape
from OCP.TopTools import TopTools_IndexedMapOfShape

if TYPE_CHECKING:
    from ..core import AnyShape, _TopoEntity, _TopologyEntityCache

# Entity kind (as stored on ``_TopoEntity.kind``) -> OCP shape enum.
_KIND_ENUMS: Mapping[str, TopAbs_ShapeEnum] = {
    "vertex": TopAbs_VERTEX,
    "edge": TopAbs_EDGE,
    "wire": TopAbs_WIRE,
    "face": TopAbs_FACE,
    "shell": TopAbs_SHELL,
    "solid": TopAbs_SOLID,
    "compound": TopAbs_COMPOUND,
}

# Runtime entries that are derived data and cheaper to recompute than to
# store: the constructor rebuilds the default mesh from the exact geometry.
_DERIVED_RUNTIME_PREFIXES = ("mesh.",)


@dataclass(frozen=True, slots=True)
class _EntityState:
    """Picklable semantic state of one topology entity."""

    kind: str
    index: int
    topo_id: str
    tags: Tuple[str, ...]
    tag_bindings: Tuple[Any, ...]
    tag_lineage: Tuple[Any, ...]
    metadata: Dict[str, Any]
    runtime: Dict[str, Any]
    incident_face_ids: Tuple[str, ...]
    incident_edge_ids: Tuple[str, ...]


def _index_map(root: TopoDS_Shape, kind: str) -> TopTools_IndexedMapOfShape:
    shapes = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(root, _KIND_ENUMS[kind], shapes)
    return shapes


def _entities_by_kind(cache: "_TopologyEntityCache") -> Dict[str, List["_TopoEntity"]]:
    grouped: Dict[str, List["_TopoEntity"]] = {}
    for entity in cache.entities():
        grouped.setdefault(entity.kind, []).append(entity)
    return grouped


def _write_shape(shape: TopoDS_Shape) -> bytes:
    stream = io.BytesIO()
    BinTools.Write_s(
        shape, stream, False, False, BinTools_FormatVersion.BinTools_FormatVersion_VERSION_4
    )
    return stream.getvalue()


def _read_shape(payload: bytes) -> TopoDS_Shape:
    shape = TopoDS_Shape()
    BinTools.Read_s(shape, io.BytesIO(payload))
    return shape


def remember_source_bytes(wrapper: "AnyShape", payload: bytes) -> None:
    """Record the BinTools bytes the wrapper's kernel shape was decoded from.

    Re-encoding a decoded shape does not always give those bytes back (see
    ``artifacts.brep.write_brep_bytes``), so encoders start from them instead.
    """

    wrapper._brep_source = (wrapper.wrapped, payload)


def source_bytes(wrapper: "AnyShape") -> bytes | None:
    """The bytes recorded by :func:`remember_source_bytes`, while still current."""

    source = getattr(wrapper, "_brep_source", None)
    if source is None or not source[0].IsEqual(wrapper.wrapped):
        return None
    return source[1]


def _capture_states(wrapper: "AnyShape") -> Tuple[_EntityState, ...]:
    """Collect the state of every cached entity that lies under the root.

    A wrapper may share its entity cache with a larger shape (a Face taken
    from a Solid); entities outside the root's index maps are skipped.
    """

    root = wrapper.wrapped
    states: List[_EntityState] = []
    for kind, entities in _entities_by_kind(wrapper._topology_cache).items():
        if kind not in _KIND_ENUMS:
            continue
        shapes = _index_map(root, kind)
        for entity in entities:
            index = shapes.FindIndex(entity.representative)
            if index == 0:
                continue
            states.append(
                _EntityState(
                    kind=kind,
                    index=index,
                    topo_id=entity.topo_id,
                    tags=tuple(sorted(entity.tags)),
                    tag_bindings=tuple(entity.tag_bindings),
                    tag_lineage=tuple(entity.tag_lineage),
                    metadata=dict(entity.metadata),
                    runtime={
                        key: value
                        for key, value in entity.runtime.items()
                        if not key.startswith(_DERIVED_RUNTIME_PREFIXES)
                    },
                    incident_face_ids=tuple(sorted(entity.incident_face_ids)),
                    incident_edge_ids=tuple(sorted(entity.incident_edge_ids)),
                )
            )
    return tuple(states)


def _find_entity(
    cache: "_TopologyEntityCache", kind: str, shape: TopoDS_Shape
) -> "_TopoEntity | None":
    """Look an entity up without creating one (``cache.get`` would)."""

    for entity in cache.entities(kind):
        if entity.representative.IsSame(shape):
            return entity
    return None


_TOPO_ID_RE = re.compile(r"^(?P<kind>[a-z]+)_(?P<index>\d+)$")


def _renumber(cache: "_TopologyEntityCache", restored: Set[int]) -> None:
    """Rebuild the id index and move counters past every restored id.

    Entities that got no saved state keep constructor ids, which can clash
    with restored ones; they are given fresh ids after the highest in use.
    """

    counters: Dict[str, int] = {}
    for entity in cache.entities():
        match = _TOPO_ID_RE.fullmatch(entity.topo_id)
        if match is not None and id(entity) in restored:
            kind = match.group("kind")
            counters[kind] = max(counters.get(kind, 0), int(match.group("index")) + 1)
    for entity in cache.entities():
        if id(entity) not in restored:
            next_index = counters.get(entity.kind, 0)
            counters[entity.kind] = next_index + 1
            entity.topo_id = f"{entity.kind}_{next_index}"
    cache._counters = counters
    cache._entities_by_id = {entity.topo_id: entity for entity in cache.entities()}


def _apply_states(wrapper: "AnyShape", states: Tuple[_EntityState, ...]) -> None:
    cache = wrapper._topology_cache
    maps: Dict[str, TopTools_IndexedMapOfShape] = {}
    restored: Set[int] = set()
    for state in states:
        shapes = maps.get(state.kind)
        if shapes is None:
            shapes = maps[state.kind] = _index_map(wrapper.wrapped, state.kind)
        if state.index > shapes.Extent():
            raise ValueError(
                f"pickled {state.kind} #{state.index} is outside the restored shape"
            )
        entity = _find_entity(cache, state.kind, shapes.FindKey(state.index))
        if entity is None:
            continue
        entity.topo_id = state.topo_id
        entity.tags.clear()
        entity.tags.update(state.tags)
        entity.tag_bindings[:] = list(state.tag_bindings)
        entity.tag_lineage[:] = list(state.tag_lineage)
        entity.metadata.clear()
        entity.metadata.update(state.metadata)
        derived = {
            key: value
            for key, value in entity.runtime.items()
            if key.startswith(_DERIVED_RUNTIME_PREFIXES)
        }
        entity.runtime.clear()
        entity.runtime.update(state.runtime)
        entity.runtime.update(derived)
        entity.incident_face_ids.clear()
        entity.incident_face_ids.update(state.incident_face_ids)
        entity.incident_edge_ids.clear()
        entity.incident_edge_ids.update(state.incident_edge_ids)
        restored.add(id(entity))
    _renumber(cache, restored)
    wrapper._refresh_tag_cache(recursive=True)


def reduce_shape(wrapper: "AnyShape") -> Tuple[Any, Tuple[Any, ...]]:
    """``__reduce__`` implementation shared by every topology wrapper."""

    payload = source_bytes(wrapper) or _write_shape(wrapper.wrapped)
    return (restore_shape, (type(wrapper).__name__, payload, _capture_states(wrapper)))


def restore_shape(
    class_name: str, payload: bytes, states: Tuple[_EntityState, ...]
) -> "AnyShape":
    """Unpickle target: rebuild the wrapper and re-apply entity state."""

    from .. import core

    wrapper_type = getattr(core, class_name)
    wrapper = wrapper_type(_read_shape(payload))
    remember_source_bytes(wrapper, payload)
    _apply_states(wrapper, states)
    return wrapper


__all__ = ["reduce_shape", "remember_source_bytes", "restore_shape", "source_bytes"]

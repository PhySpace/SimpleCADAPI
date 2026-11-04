"""Element references resolved through recorded operation history (the engine behind :mod:`simplecadapi.ref`).

An *anchor* names a sub-shape by where it was born.  Two forms:

* a raw anchor ``{node_id, output_slot, kind, topo_id}`` (:func:`anchor_of`): valid inside one run;
* a stable anchor ``{feature, op, occurrence, output_slot, kind, role, role_ordinal, topo_id}``
  (:func:`stable_anchor_of`): the node is named by its cell, op name and how many nodes of that cell with that
  op feed it, the entity by its kernel role -- so an operation inserted earlier in the cell does not shift it.
  This is the form to persist.

:func:`resolve` follows the anchor through the ``TopoDelta`` every later node recorded from OCCT's history (the C++
kernel does the walk, ``scad::reactive::resolve_by_history``) to the entities of a later shape, and says how it
went:

* ``ok``     -- exactly one entity, nothing else merged into it;
* ``split``  -- several entities (a cut through a face); ``candidates`` lists them;
* ``merged`` -- one entity that also absorbed entities outside the lineage (a fuse unifying faces);
* ``lost``   -- none; ``lost_at`` / ``reason`` say where and why (``deleted``, ``replaced``, ``no_history``,
  ``not_downstream``, ``anchor_missing``, ``anchor_ambiguous``); with a ``guard`` the ``candidates`` are ranked
  look-alikes.

:func:`require` is what a feature uses: it returns the entities for ``ok`` / ``merged`` and raises
:class:`ElementRefError` (carrying the candidates) for ``split`` unless the caller picked a piece, and for ``lost``.
Nothing is ever chosen silently.  See ``design-docs/stable-refs-design.md``.

The public face is :mod:`simplecadapi.ref` (``scad.ref.of`` / ``scad.ref.face(...)`` / ``ql.ref``); this module
works on anchor dicts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .._cpp import _native

NAMING_VERSION: str = _native._naming_version

__all__ = [
    "NAMING_VERSION",
    "Candidate",
    "ElementRefError",
    "Resolution",
    "ResolvedRef",
    "anchor_of",
    "anchors_for_role",
    "guard_of",
    "require",
    "resolve",
    "stable_anchor_of",
]


@dataclass(frozen=True)
class Candidate:
    """An entity the person can choose: a piece of a split, or a look-alike of a lost entity."""

    entity: Any
    topo_id: str
    kind: str
    geom_type: str
    center: tuple
    size: float  # area of a face, length of an edge, volume of a solid
    score: float = 0.0  # lost only: distance to the guard, smaller is closer

    def describe(self) -> Dict[str, Any]:
        return {
            "topo_id": self.topo_id,
            "kind": self.kind,
            "geom_type": self.geom_type,
            "center": list(self.center),
            "size": self.size,
            "score": self.score,
        }


@dataclass(frozen=True)
class Resolution:
    """How a reference resolved in a shape: ``ok`` / ``split`` / ``merged`` / ``lost``, the entities, and why.

    ``candidates`` are the pieces of a split (in a geometric order: centre, then size) or, for a lost reference with
    a guard, up to five look-alikes ranked by their distance to the guard; ``bodies`` says which solid of the shape
    each entity lies in.
    """

    status: str
    entities: List[Any]
    targets: List[Dict[str, Any]]
    hops: List[Dict[str, Any]] = field(default_factory=list)
    lost_at: Optional[str] = None
    reason: Optional[str] = None
    candidates: List[Candidate] = field(default_factory=list)
    # Which body (solid of the target shape, in its solid order) each of `entities` lies in.
    bodies: List[Optional[int]] = field(default_factory=list)
    # The reference was made under another naming version (NAMING_VERSION): check it against its guard.
    version_changed: bool = False

    def describe(self) -> Dict[str, Any]:
        """The editor-facing form: status, where it was lost and why, and the candidates to choose from."""

        return {
            "status": self.status,
            "lost_at": self.lost_at,
            "reason": self.reason,
            "bodies": list(self.bodies),
            "version_changed": self.version_changed,
            "candidates": [c.describe() for c in self.candidates],
        }


ResolvedRef = Resolution  # the spike's name


class ElementRefError(ValueError):
    """A reference that does not name exactly one entity: ``split`` (choose a piece) or ``lost``.

    ``status`` and ``candidates`` say which and what to choose from; ``resolved`` is the whole :class:`Resolution`.
    """

    def __init__(self, resolved: Resolution):
        self.resolved = resolved
        self.status = resolved.status
        self.candidates = resolved.candidates
        if resolved.status == "split":
            text = f"the referenced entity was split into {len(resolved.candidates)} pieces: choose one"
        else:
            text = f"the referenced entity is lost ({resolved.reason} at {resolved.lost_at})"
            if resolved.candidates:
                text += f"; {len(resolved.candidates)} look-alike candidate(s)"
        if resolved.version_changed:
            text += " (the reference was made under another naming version)"
        super().__init__(text)

    def __reduce__(self):
        return (type(self), (self.resolved,))


def _node_of(shape: Any) -> Any:
    node = shape._get_runtime("graph.node", None)
    if node is None:
        raise ValueError("the shape was not recorded in a GraphSession: it has no history to resolve through")
    return node


def anchor_of(entity: Any) -> Dict[str, Any]:
    """The raw anchor of a sub-shape of a recorded output (a face picked from a solid, say)."""

    ref = entity.get_metadata("topo_ref", None)
    if not ref:
        raise ValueError("the entity is not part of a recorded output")
    return {key: ref[key] for key in ("node_id", "output_slot", "kind", "topo_id")}


def stable_anchor_of(entity: Any, shape: Any) -> Dict[str, Any]:
    """The re-execution-stable anchor of *entity*, a sub-shape of *shape* (or of a shape *shape* descends from)."""

    return dict(_native._stable_anchor(_node_of(shape), anchor_of(entity)))


def anchors_for_role(shape: Any, role: str) -> List[Dict[str, Any]]:
    """The anchors of the entities the node that made *shape* gave kernel role *role* (``"extrusion.end"``)."""

    return list(_native._anchors_for_role(_node_of(shape), role))


def _size(entity: Any) -> float:
    if type(entity).__name__ == "Solid":
        return float(entity.get_volume())
    if type(entity).__name__ == "Vertex":
        return 0.0  # a point has no size: its centre is all there is to it
    return float(entity.get_area()) if hasattr(entity, "get_area") else float(entity.get_length())


def _geom_type(entity: Any) -> str:
    kind = type(entity).__name__
    if kind in ("Solid", "Vertex"):
        return kind.upper()
    return entity._geom_type()


def guard_of(entity: Any) -> Dict[str, Any]:
    """A geometric fingerprint of *entity*: checks a resolution and ranks candidates for a lost one, never more."""

    c = entity.get_center()
    guard: Dict[str, Any] = {
        "kind": type(entity).__name__.lower(),
        "geom_type": _geom_type(entity),
        "center": [c.x, c.y, c.z],
        "size": _size(entity),
    }
    if hasattr(entity, "get_normal_at"):
        n = entity.get_normal_at()
        guard["normal"] = [n.x, n.y, n.z]
    return guard


def _candidate(entity: Any, topo_id: str, score: float = 0.0) -> Candidate:
    c = entity.get_center()
    return Candidate(
        entity=entity,
        topo_id=topo_id,
        kind=type(entity).__name__.lower(),
        geom_type=_geom_type(entity),
        center=(c.x, c.y, c.z),
        size=_size(entity),
        score=score,
    )


def _geometric_order(candidates: List[Candidate]) -> List[Candidate]:
    # A deterministic order that does not depend on OCCT's numbering: by centre, then size.
    return sorted(candidates, key=lambda c: (tuple(round(v, 6) for v in c.center), round(c.size, 6)))


def _ranked_lookalikes(shape: Any, guard: Dict[str, Any], kind: str, limit: int = 5) -> List[Candidate]:
    from .. import ql

    factory = {"face": ql.faces, "edge": ql.edges, "vertex": ql.vertices, "solid": ql.solids}.get(kind)
    if factory is None:
        return []
    out: List[Candidate] = []
    for entity in factory().resolve(shape):
        ref = entity.get_metadata("topo_ref", None) or {}
        c = entity.get_center()
        distance = math.dist((c.x, c.y, c.z), guard["center"])
        size = _size(entity)
        score = distance + abs(size - guard["size"]) / max(guard["size"], 1e-9)
        if _geom_type(entity) != guard.get("geom_type"):
            score += 1000.0
        if "normal" in guard and hasattr(entity, "get_normal_at"):
            n = entity.get_normal_at()
            dot = n.x * guard["normal"][0] + n.y * guard["normal"][1] + n.z * guard["normal"][2]
            score += 10.0 * (1.0 - max(-1.0, min(1.0, dot)))
        out.append(_candidate(entity, str(ref.get("topo_id", "")), score))
    out.sort(key=lambda c: c.score)
    return out[:limit]


def _bodies_of(shape: Any, entities: List[Any]) -> List[Optional[int]]:
    from .. import ql

    if not entities:
        return []
    shape_kind = type(shape).__name__
    if shape_kind == "Solid":
        solids = [shape]
    elif shape_kind == "Compound":
        solids = ql.solids().resolve(shape)
    else:  # a Face, Shell, Wire or Edge holds no solid: its entities belong to no body
        return [None for _ in entities]
    out: List[Optional[int]] = []
    for entity in entities:
        kind = type(entity).__name__
        found = None
        for index, solid in enumerate(solids):
            if kind == "Solid":
                if solid == entity:
                    found = index
                    break
                continue
            members = ql.faces().resolve(solid) if kind == "Face" else ql.edges().resolve(solid)
            if any(member == entity for member in members):
                found = index
                break
        out.append(found)
    return out


def resolve(
    anchor: Dict[str, Any],
    shape: Any,
    *,
    follow: str = "identity",
    output_slot: Optional[int] = None,
    guard: Optional[Dict[str, Any]] = None,
) -> Resolution:
    """Follow *anchor* (raw or stable) through recorded history to the entities of *shape* (a later output).

    *shape* names its node and output slot itself (a body of a multi-body result is its own slot).
    """

    node = _node_of(shape)
    if output_slot is None:
        output_slot = int((shape.get_metadata("graph", None) or {}).get("output_slot", 0))
    raw = anchor
    if "op" in anchor:  # a stable anchor: find its node in this run first
        raw = _native._locate_anchor(node, anchor)
        if raw is None:
            # Several nodes share the key and the parameters do not tell them apart: the person chooses.
            ambiguous = len(_native._stable_candidates(node, anchor)) > 1
            lookalikes = _ranked_lookalikes(shape, guard, str(anchor["kind"]).lower()) if guard else []
            reason = "anchor_ambiguous" if ambiguous else "anchor_missing"
            changed = anchor.get("naming", "") != NAMING_VERSION
            return Resolution("lost", [], [], [], None, reason, lookalikes, [], changed)
    data = _native._resolve_by_history(node, raw, output_slot, follow)
    targets = list(data["targets"])
    entities: List[Any] = []
    by_kind: Dict[str, List[str]] = {}
    for target in targets:
        by_kind.setdefault(str(target["kind"]).lower(), []).append(target["topo_id"])
    candidates: List[Candidate] = []
    for kind, ids in by_kind.items():
        found = list(_native._subshapes_by_recorded_id(shape, kind, ids))
        entities.extend(found)
        candidates.extend(_candidate(entity, topo_id) for entity, topo_id in zip(found, ids))
    status = data["status"]
    if status == "split":
        candidates = _geometric_order(candidates)
    elif status == "lost":
        kind = str(raw["kind"]).lower()
        candidates = _ranked_lookalikes(shape, guard, kind) if guard else []
    else:
        candidates = []
    return Resolution(
        status=status,
        entities=entities,
        targets=targets,
        hops=list(data["hops"]),
        lost_at=data.get("lost_at"),
        reason=data.get("reason"),
        candidates=candidates,
        bodies=_bodies_of(shape, entities),
        version_changed="op" in anchor and anchor.get("naming", "") != NAMING_VERSION,
    )


def require(
    anchor: Dict[str, Any],
    shape: Any,
    *,
    piece: Optional[int] = None,
    follow: str = "identity",
    guard: Optional[Dict[str, Any]] = None,
) -> Sequence[Any]:
    """The entities a feature may use, or :class:`ElementRefError`.

    A split is an error unless *piece* says which of ``candidates`` (geometric order) the person chose.
    """

    resolved = resolve(anchor, shape, follow=follow, guard=guard)
    if resolved.status in ("ok", "merged"):
        return resolved.entities
    if resolved.status == "split" and piece is not None:
        if not 0 <= piece < len(resolved.candidates):
            raise ElementRefError(resolved)
        return [resolved.candidates[piece].entity]
    raise ElementRefError(resolved)

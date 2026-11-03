"""Element references resolved through recorded operation history (spike; private, not exported).

An *anchor* names a sub-shape by where it was born: ``{node_id, output_slot, kind, topo_id}`` of the
node that produced it.  :func:`resolve` follows the anchor through the ``TopoDelta`` every later node
recorded from OCCT's history (the C++ kernel does the walk, ``scad::reactive::resolve_by_history``) to
the entities of a later shape, and says how it went:

* ``ok``     -- exactly one entity, nothing else merged into it;
* ``split``  -- several entities (a cut through a face);
* ``merged`` -- one entity that also absorbed entities outside the lineage (a fuse unifying faces);
* ``lost``   -- none; ``lost_at`` / ``reason`` say where and why (``deleted``, ``replaced``,
  ``no_history``, ``not_downstream``).

No geometry is consulted and nothing is guessed.  See ``design-docs/stable-refs-design.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .._cpp import _native

__all__ = ["ResolvedRef", "anchor_of", "anchors_for_role", "resolve"]


@dataclass(frozen=True)
class ResolvedRef:
    status: str
    entities: List[Any]
    targets: List[Dict[str, Any]]
    hops: List[Dict[str, Any]] = field(default_factory=list)
    lost_at: Optional[str] = None
    reason: Optional[str] = None


def _node_of(shape: Any) -> Any:
    node = shape._get_runtime("graph.node", None)
    if node is None:
        raise ValueError("the shape was not recorded in a GraphSession: it has no history to resolve through")
    return node


def anchor_of(entity: Any) -> Dict[str, Any]:
    """The anchor of a sub-shape of a recorded output (a face picked from a solid, say)."""

    ref = entity.get_metadata("topo_ref", None)
    if not ref:
        raise ValueError("the entity is not part of a recorded output")
    return {key: ref[key] for key in ("node_id", "output_slot", "kind", "topo_id")}


def anchors_for_role(shape: Any, role: str) -> List[Dict[str, Any]]:
    """The anchors of the entities the node that made *shape* gave kernel role *role* (``"extrude.first_cap"``)."""

    return list(_native._anchors_for_role(_node_of(shape), role))


def resolve(anchor: Dict[str, Any], shape: Any, *, follow: str = "identity", output_slot: int = 0) -> ResolvedRef:
    """Follow *anchor* through recorded history to the entities of *shape* (a later recorded output)."""

    data = _native._resolve_by_history(_node_of(shape), anchor, output_slot, follow)
    targets = list(data["targets"])
    entities: List[Any] = []
    by_kind: Dict[str, List[str]] = {}
    for target in targets:
        by_kind.setdefault(str(target["kind"]).lower(), []).append(target["topo_id"])
    for kind, ids in by_kind.items():
        entities.extend(_native._subshapes_by_recorded_id(shape, kind, ids))
    return ResolvedRef(
        status=data["status"],
        entities=entities,
        targets=targets,
        hops=list(data["hops"]),
        lost_at=data.get("lost_at"),
        reason=data.get("reason"),
    )

"""Stable references for the editor, worked out in the kernel (where the values are).

The editor never computes a reference from geometry: it sends the entity ids the person picked in the viewport, and
the kernel names each one with :func:`simplecadapi.ref.of` on the solid the preview drew it from.  The same goes for a
feature's health: the kernel resolves the references of a feature cell against the body the cell reads, and a repair
(a piece of a split, a look-alike of a lost reference) is :meth:`ElementRef.choose` there.  Every answer is plain data
(the reference as its code and record, the resolution as ``Resolution.describe()``).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .. import ref as _ref
from ._marimo import safe_get_context


def _scene_entity(entity_id: str) -> tuple[Any, Any] | None:
    """(the entity, the solid it is part of) for an entity id of the scene last previewed."""
    from . import live

    scene = live._last_preview
    if scene is None:
        return None
    _, _, rest = entity_id.partition("entity/")
    definition, _, tail = rest.partition("/")
    body_id = ""
    if tail.startswith("body:"):
        segment, _, tail = tail.partition("/")
        body_id = segment[len("body:") :]
    kind, _, topo_id = tail.partition("/")
    key = next((k for k, d in scene.definitions.items() if d == definition and scene.bodies.get(k, "") == body_id), None)
    if key is None:
        return None
    solid = scene.solids[key]
    pool = {"face": solid._iter_faces, "edge": solid._iter_edges}.get(kind)
    if pool is None:
        return None
    entity = next((item for item in pool() if item.topo_id == topo_id), None)
    return (entity, solid) if entity is not None else None


def entity_refs(entity_ids: Sequence[str]) -> list[dict[str, Any]]:
    """The reference of each picked entity: ``{"code", "record"}``, or ``{"error"}`` when it cannot be named."""
    out: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        found = _scene_entity(str(entity_id))
        if found is None:
            out.append({"error": "the entity is not in the scene last previewed"})
            continue
        try:
            reference = _ref.of(*found)
        except (ValueError, TypeError) as exc:  # a value without recorded history (an imported body)
            out.append({"error": str(exc)})
            continue
        out.append({"code": reference.code(), "record": reference.to_dict()})
    return out


def _value(name: str) -> Any:
    context = safe_get_context()
    if context is None:
        raise RuntimeError("not running inside a marimo kernel")
    if name not in context.globals:
        raise KeyError(f"{name!r} is not a value of the notebook (has its cell run?)")
    return context.globals[name]


def reference_status(body: str, records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """How each reference resolves in the notebook value *body*: ``Resolution.describe()`` plus its ``code``."""
    shape = _value(body)
    out: list[dict[str, Any]] = []
    for record in records:
        reference = _ref.coerce(dict(record))
        try:
            resolution = reference.resolve(shape)
        except (ValueError, TypeError) as exc:
            out.append({"code": reference.code(), "status": "lost", "reason": "error", "error": str(exc), "candidates": []})
            continue
        described = resolution.describe()
        if resolution.status == "split" and reference.piece is not None and reference.piece < len(resolution.candidates):
            described["chosen"] = reference.piece  # a split the person has resolved: the feature runs
        described["code"] = reference.code()
        out.append(described)
    return out


def reference_choose(body: str, record: Mapping[str, Any], choice: int) -> dict[str, Any]:
    """The reference with candidate *choice* written in (``ElementRef.choose``): ``{"code", "record"}``."""
    chosen = _ref.coerce(dict(record)).choose(int(choice), _value(body))
    return {"code": chosen.code(), "record": chosen.to_dict()}


__all__ = ["entity_refs", "reference_choose", "reference_status"]

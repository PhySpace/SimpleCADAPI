"""A 3D curve the editor draws in space, and the cell code it becomes.

A sketch lies in one plane; a 3D curve does not: each of its points is in world space, on a workplane, or at a vertex
of the model, so one path can run between planes and through the model (a sweep path, a rail, a loft guide).  The
document is plain data::

    {"points": [{"id": "p1", "at": [0, 0, 0]},                                  # world mm
                {"id": "p2", "on": "wp_2", "uv": [10, 5]},                       # on a workplane variable: follows it
                {"id": "p3", "vertex": {<scad.ref record>}, "at": [20, 0, 10]}],  # a vertex of the model: follows it
     "curves": [{"id": "c1", "kind": "line", "points": ["p1", "p2"]},
                {"id": "c2", "kind": "arc", "points": ["p2", "p4", "p3"]},       # start, a point on it, end
                {"id": "c3", "kind": "spline", "points": ["p3", "p5", "p6"]}]}   # through the points

The curves follow one another (each starts where the last ended) and become one wire.  :func:`render` writes the cell:
one name per point (a vertex resolves through its stable reference in the body, a workplane point through
``wp.point(u, v)``), one SDK edge per curve, and ``make_wire_from_edges_rwire`` joining them.  Nothing here is
geometry: the code is the SDK's, the document only says which points and curves.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

from .. import ref as _ref

KINDS = {"line": 2, "arc": 3, "spline": 2}
"""Each kind and how many points it takes (a spline takes this many or more)."""

_ID = re.compile(r"[a-z][a-z0-9_]{0,30}")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class CurveError(ValueError):
    """A 3D curve document the editor cannot turn into code."""


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise CurveError(f"{what} must be a finite number")
    return round(float(value), 6) + 0.0


def _vector(value: Any, size: int, what: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise CurveError(f"{what} needs {size} numbers")
    return [_number(v, what) for v in value]


def validate(doc: Mapping[str, Any]) -> dict[str, Any]:
    """The document checked and cleaned; :class:`CurveError` names what is wrong."""
    if not isinstance(doc, Mapping):
        raise CurveError("a 3D curve is an object with points and curves")
    points: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in doc.get("points") or []:
        if not isinstance(raw, Mapping) or not _ID.fullmatch(str(raw.get("id", ""))):
            raise CurveError("every point needs an id (a lower-case name)")
        pid = str(raw["id"])
        if pid in ids:
            raise CurveError(f"point {pid!r} is listed twice")
        ids.add(pid)
        point: dict[str, Any] = {"id": pid}
        if raw.get("on") is not None:
            if not _NAME.fullmatch(str(raw["on"])):
                raise CurveError(f"point {pid!r}: {raw['on']!r} is not a workplane name")
            point["on"] = str(raw["on"])
            point["uv"] = _vector(raw.get("uv"), 2, f"point {pid!r} on {raw['on']}")
        if raw.get("vertex") is not None:
            try:
                reference = _ref.coerce(raw["vertex"])
            except (ValueError, TypeError) as exc:
                raise CurveError(f"point {pid!r}: {exc}") from exc
            if reference.kind != "vertex":
                raise CurveError(f"point {pid!r}: a point is snapped to a vertex, not a {reference.kind}")
            point["vertex"] = reference.to_dict()
        if raw.get("at") is not None or ("on" not in point and "vertex" not in point):
            point["at"] = _vector(raw.get("at"), 3, f"point {pid!r}")
        if "on" in point and "vertex" in point:
            raise CurveError(f"point {pid!r} is either on a workplane or at a vertex, not both")
        points.append(point)
    curves: list[dict[str, Any]] = []
    for raw in doc.get("curves") or []:
        if not isinstance(raw, Mapping) or not _ID.fullmatch(str(raw.get("id", ""))):
            raise CurveError("every curve needs an id (a lower-case name)")
        kind = str(raw.get("kind", ""))
        if kind not in KINDS:
            raise CurveError(f"curve {raw['id']!r}: a curve is a line, an arc or a spline")
        names = [str(p) for p in raw.get("points") or []]
        if any(p not in ids for p in names):
            raise CurveError(f"curve {raw['id']!r} names a point the document does not have")
        if (kind == "spline" and len(names) < 2) or (kind != "spline" and len(names) != KINDS[kind]):
            article = "an" if kind == "arc" else "a"
            raise CurveError(f"curve {raw['id']!r}: {article} {kind} takes {'at least 2' if kind == 'spline' else KINDS[kind]} points")
        curves.append({"id": str(raw["id"]), "kind": kind, "points": names})
    if not curves:
        raise CurveError("draw at least one line, arc or spline")
    for before, after in zip(curves, curves[1:]):
        if before["points"][-1] != after["points"][0]:
            raise CurveError(f"curve {after['id']!r} must start where {before['id']!r} ends: the curves make one path")
    return {"points": points, "curves": curves}


def workplanes_of(doc: Mapping[str, Any]) -> list[str]:
    """The workplane variables the document's points are on (the cell reads them)."""
    return sorted({p["on"] for p in doc.get("points") or [] if p.get("on")})


def needs_body(doc: Mapping[str, Any]) -> bool:
    """Whether a point is at a vertex of the model (resolved in the body)."""
    return any(p.get("vertex") for p in doc.get("points") or [])


def _literal(values: list[float]) -> str:
    return "(" + ", ".join(repr(v) for v in values) + ")"


def render(slug: str, doc: Mapping[str, Any], body: str | None) -> list[str]:
    """The lines of the feature cell for a validated *doc*; the wire is bound to *slug*, model vertices resolve in *body*."""
    lines: list[str] = []
    used = {p for curve in doc["curves"] for p in curve["points"]}
    for point in doc["points"]:
        if point["id"] not in used:
            continue
        name = f"_{point['id']}"
        if point.get("vertex"):
            if body is None:
                raise CurveError(f"point {point['id']!r} is at a vertex of the model, and there is no body to find it in")
            code = _ref.ElementRef.from_dict(point["vertex"]).code()
            lines.append(f"{name} = {code}.one({body}).get_coordinates()")
        elif point.get("on"):
            u, v = point["uv"]
            lines.append(f"{name} = {point['on']}.point({u!r}, {v!r})")
        else:
            lines.append(f"{name} = {_literal(point['at'])}")
    edges = []
    for curve in doc["curves"]:
        names = [f"_{p}" for p in curve["points"]]
        if curve["kind"] == "line":
            edges.append(f"scad.make_segment_redge({names[0]}, {names[1]})")
        elif curve["kind"] == "arc":
            edges.append(f"scad.make_three_point_arc_redge({names[0]}, {names[1]}, {names[2]})")
        else:
            edges.append(f"scad.make_interpolated_spline_redge(points=[{', '.join(names)}])")
    lines.append(f"{slug} = scad.make_wire_from_edges_rwire([")
    lines.extend(f"    {edge}," for edge in edges)
    lines.append("])")
    return lines


__all__ = ["KINDS", "CurveError", "needs_body", "render", "validate", "workplanes_of"]

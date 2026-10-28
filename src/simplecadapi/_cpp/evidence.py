"""Failure-evidence pictures: what an operation shows next to the text of its error.

An operation that has diagnosed a failure asks for a picture (``DiagnosticImage`` in C++); this module draws it:

* ``render``            solids on the software renderer (four axonometric views): each operand in its own colour, or
                        one solid with the implicated edges as orange lines (a failed blend); a failed QL selection
                        is drawn by ``_ql_evidence``, which the QL layer asks for through its own hook;
* ``wire_plan_render``  wires projected on their best-fit plane, the loose ends in orange (matplotlib);
* ``sketch_render``     a sketch at the solver's positions, implicated entities orange, related ones purple (matplotlib).

Every picture is best effort: a failure to draw never replaces the error, which stays text-complete.  One picture per
failure signature per process (agent retry loops must not pay again), and ``SCA_NO_DIAGNOSTIC_RENDER`` switches them off.
"""

from __future__ import annotations

import math
import os
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .._glue.notice import say

# One picture per distinct failure signature (the tests clear it).
_RENDER_DEDUP: Set[Any] = set()

_DISABLE_ENV = "SCA_NO_DIAGNOSTIC_RENDER"
_TRUTHY = {"1", "true", "yes", "on"}

# Ink palette shared by the 2D schematics: orange = implicated, purple = related, grey ink = the rest.
_INK = "#3a3a3a"
_HIGHLIGHT = "#f39c12"
_NEAR = "#8066bf"
_CONSTRUCTION = "#9a9a9a"

_DIAGNOSTIC_VIEWS = (
    (30.0, 45.0, "iso FR"),
    (30.0, 135.0, "iso BR"),
    (30.0, 225.0, "iso BL"),
    (30.0, 315.0, "iso FL"),
)


def enabled() -> bool:
    return os.environ.get(_DISABLE_ENV, "").strip().lower() not in _TRUTHY


def _root() -> Path:
    """``<cwd>/.simplecad/diagnostics``, resolved at every call (a process that changes directory follows it)."""

    return Path.cwd() / ".simplecad" / "diagnostics"


def _path(prefix: str) -> Path:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.png"


def _evidence(kind: str, path: Path, view: str, caption: str, symbols: Sequence[Tuple[str, str]] = ()) -> Dict[str, Any]:
    return {"kind": kind, "path": str(path), "view": view, "caption": caption, "symbols": list(symbols)}


def provide(kind: str, operation: str, view: str, caption: str, dedup_key: str, shapes: Sequence[Any],
            payload: Mapping[str, Any], highlight_edges: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    """The provider the C++ side calls: the evidence dict for one requested picture, or None."""

    if not enabled():
        return None
    key = (operation, dedup_key) if kind != "sketch_render" else dedup_key
    if key in _RENDER_DEDUP:
        return None
    _RENDER_DEDUP.add(key)
    try:
        if kind == "render":
            return _render_solids(operation, view, caption, shapes, payload, highlight_edges)
        if kind == "wire_plan_render":
            return _wire_plan(operation, view, caption, shapes, payload)
        if kind == "sketch_render":
            return _sketch(operation, view, caption, payload)
    except Exception as error:  # noqa: BLE001 - a picture must never mask the error it illustrates
        if kind == "render":
            return _evidence("render-unavailable", Path(), view,
                             f"diagnostic render unavailable: {type(error).__name__}: {error}")
        say(f"the {kind} picture of {operation} could not be drawn ({type(error).__name__}: {error})")
    return None


# ---- 3D: the operands on the software renderer ------------------------------------------------


def _draw_solids(operation: str, drawn: Sequence[Any], *, tags: Sequence[str] = (), tag_labels: Mapping[str, str] = {},
                 edges: Sequence[Any] = (), callouts: bool = False) -> Path:
    from .screenshot import render_screenshot

    path = _path(operation)
    render_screenshot(
        list(drawn),
        path,
        views=_DIAGNOSTIC_VIEWS,
        supersample=1,
        edge_width_scale=0.0035,  # heavier model ink so panels read at grid size
        highlight_edge_width=8.0,  # highlights outweigh the ink, always
        highlight_tags=tuple(tags),
        tag_labels=dict(tag_labels),
        highlight_edges=tuple(edges),
        show_legend=True,
        show_callouts=callouts,
    )
    return path


def _render_solids(operation: str, view: str, caption: str, shapes: Sequence[Any], payload: Mapping[str, Any],
                   highlight_edges: Sequence[Any] = ()):
    if highlight_edges:
        # One solid, the implicated edges as orange lines over it: nothing to tag.
        return _evidence("render", _draw_solids(operation, shapes, edges=list(highlight_edges)), view,
                         caption)

    from . import _native as _n

    labels = list(payload.get("operand_labels") or [])
    tags: List[str] = []
    tag_labels: Dict[str, str] = {}
    drawn: List[Any] = []
    for index, shape in enumerate(shapes[:2]):
        copy = _n.clone_semantic_view(shape)  # tag a copy: never the caller's object
        tag = f"diagnostic.operand_{index + 1}"
        copy._apply_tag(tag, propagate=False)
        drawn.append(copy)
        tags.append(tag)
        tag_labels[tag] = labels[index] if index < len(labels) else f"operand {index + 1}"
    # A solid-tag callout anchor sits inside the solid and may point at the wrong body.
    return _evidence("render", _draw_solids(operation, drawn, tags=tags, tag_labels=tag_labels), view, caption)


# ---- 3D: a QL selection that missed its cardinality -------------------------------------------

_MATCHED_TAG = "diagnostic.matched"
_NEAR_MISS_TAG = "diagnostic.near_miss"


def _ql_evidence(scope: Any, matched: Sequence[Any], target_kind: str, dedup_key: Any,
                 near_misses: Sequence[Any]) -> List[Dict[str, Any]]:
    """The provider the QL layer calls: the scope with the matched entities visibly highlighted.

    A face selection draws a copy of the scope whose matched faces carry ``diagnostic.matched`` (orange) and up to
    three near-miss faces ``diagnostic.near_miss`` (purple), with legend and callouts; the user's own shape is never
    tagged.  Other targets draw the first eight matched entities as orange lines.
    """

    if not enabled() or dedup_key in _RENDER_DEDUP:
        return []
    _RENDER_DEDUP.add(dedup_key)
    operation = f"ql_{target_kind}_resolve"
    try:
        from . import _native as _n

        tags: List[str] = []
        tag_labels: Dict[str, str] = {}
        shapes: List[Any] = []
        if target_kind == "face" and scope.__class__.__name__ == "Solid":
            copy = _n.clone_semantic_view(scope)
            # Match by kernel topology identity: Python-level wrappers differ across copies, TopoDS identity does not.
            matched_wrapped = [item._native_wrapped for item in matched]
            near_wrapped = [item._native_wrapped for item in near_misses]
            matched_any = False
            near_tagged = 0
            for face in copy._iter_faces():
                if any(face._native_wrapped.IsSame(w) for w in matched_wrapped):
                    face._apply_tag(_MATCHED_TAG, propagate=False)
                    matched_any = True
                elif near_tagged < 3 and any(face._native_wrapped.IsSame(w) for w in near_wrapped):
                    face._apply_tag(_NEAR_MISS_TAG, propagate=False)
                    near_tagged += 1
            if matched_any:
                tags = [_MATCHED_TAG] + ([_NEAR_MISS_TAG] if near_tagged else [])
                tag_labels = {_MATCHED_TAG: f"matched {target_kind}(s)", _NEAR_MISS_TAG: "near miss"}
                shapes = [copy]
        edges: List[Any] = []
        if not shapes:
            # Everything but faces (and faces of a scope that is no solid, or none matched): the matched entities
            # themselves, as orange lines.
            edges = list(matched[:8])
            if scope.__class__.__name__ == "Solid":
                shapes = [scope]
            if not shapes and not edges:
                return []
        path = _draw_solids(operation, shapes, tags=tags, tag_labels=tag_labels, edges=edges, callouts=bool(tags))
    except Exception as error:  # noqa: BLE001 - a picture must never mask the error it illustrates
        return [_evidence("render-unavailable", Path(), "default",
                          f"diagnostic render unavailable: {type(error).__name__}: {error}")]
    caption = ("orange = matched, purple = near miss; see inventory for identities" if target_kind == "face"
               else "orange lines = matched entities; see inventory")
    return [_evidence("render", path, "default", caption)]


# ---- 2D: wires on their best-fit plane --------------------------------------------------------


def _wire_plan(operation: str, view: str, caption: str, shapes: Sequence[Any], payload: Mapping[str, Any]):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.lines import Line2D

    from . import _native as _n

    marks = [(tuple(m["point"]), str(m["label"]), str(m.get("tone", "highlight"))) for m in payload.get("marks", [])]
    pins = [np.array(point, dtype=float) for point, _label, _tone in marks]

    polylines: List[Tuple[List[Tuple[float, float, float]], str]] = []
    all_points: List[Tuple[float, float, float]] = []
    for shape in shapes:
        edges = list(shape._iter_edges()) if hasattr(shape, "_iter_edges") else [shape]
        for edge in edges:
            points = [tuple(p) for p in _n._sample_edge_points(edge, 16)]
            if len(points) < 2:
                continue
            ends = (np.array(points[0], dtype=float), np.array(points[-1], dtype=float))
            # An edge with one of the marked ends is the geometry the failure is about.
            near = any(np.linalg.norm(end - pin) < 1e-6 for end in ends for pin in pins)
            polylines.append((points, "highlight" if near else "ink"))
            all_points.extend(points)
    all_points.extend(point for point, _label, _tone in marks)
    if len(all_points) < 2:
        return None

    matrix = np.array(all_points, dtype=float)
    centered = matrix - matrix.mean(axis=0)
    _, _, right = np.linalg.svd(centered, full_matrices=False)
    basis_u, basis_v = right[0], right[1]

    def to_plan(point) -> Tuple[float, float]:
        return (float(np.dot(point, basis_u)), float(np.dot(point, basis_v)))

    colours = {"ink": _INK, "highlight": _HIGHLIGHT, "near": _NEAR}
    figure, axes = plt.subplots(figsize=(10.0, 7.0), dpi=100)
    path = _path("wire")
    try:
        plan_points: List[Tuple[float, float]] = []
        for points, tone in polylines:
            plan = [to_plan(point) for point in points]
            plan_points.extend(plan)
            axes.plot([p[0] for p in plan], [p[1] for p in plan], color=colours.get(tone, _INK),
                      linewidth=3.2 if tone == "highlight" else 1.6, solid_capstyle="round")
        for point, label, tone in marks:
            plan = to_plan(point)
            plan_points.append(plan)
            colour = colours.get(tone, _INK)
            axes.plot(*plan, marker="o", markersize=9, color=colour)
            axes.annotate(label, plan, xytext=(8, 8), textcoords="offset points", fontsize=10, fontweight="bold",
                          color=colour, bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": colour, "alpha": 0.9})
        xs = [p[0] for p in plan_points]
        ys = [p[1] for p in plan_points]
        pad_x = max((max(xs) - min(xs)) * 0.08, 0.5)
        pad_y = max((max(ys) - min(ys)) * 0.08, 0.5)
        axes.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
        axes.set_ylim(min(ys) - pad_y, max(ys) + pad_y)
        axes.set_aspect("equal", adjustable="box")
        axes.grid(True, color="#e6e6e6", linewidth=0.6)
        axes.set_title(f"{operation} — wire plan (projected)", fontsize=13, fontweight="bold")
        axes.legend(handles=[Line2D([0], [0], color=_HIGHLIGHT, linewidth=3.2, label="implicated geometry"),
                             Line2D([0], [0], color=_NEAR, linewidth=2, label="related"),
                             Line2D([0], [0], color=_INK, linewidth=1.6, label="context")],
                    loc="upper right", fontsize=9)
        figure.text(0.5, 0.015, "\n".join(textwrap.wrap(caption, width=110) or [caption]), ha="center", fontsize=9,
                    color="#555555", va="top")
        figure.savefig(path, bbox_inches="tight")
    finally:
        plt.close(figure)
    return _evidence("wire_plan_render", path, view, caption)


# ---- 2D: a sketch at the solver's positions ----------------------------------------------------


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _sketch(operation: str, view: str, caption: str, payload: Mapping[str, Any]):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Arc, Circle, Ellipse

    sketch = payload["sketch"]
    entities = {item["id"]: item for item in sketch.get("entities", [])}
    order = [item["id"] for item in sketch.get("entities", [])]
    solved = {key: tuple(value) for key, value in (payload.get("solved_points") or {}).items()}
    scalars = payload.get("solved_scalars") or {}
    highlight = {str(item) for item in payload.get("highlight", [])}
    near = {str(item) for item in payload.get("near", [])}
    labels = [(str(a), str(b)) for a, b in payload.get("constraint_labels", [])]
    mode = str(payload.get("mode", ""))

    positions: Dict[str, Tuple[float, float]] = {}
    for entity_id in order:
        entity = entities[entity_id]
        if entity["kind"] != "point":
            continue
        point = solved.get(entity_id)
        if point is None:
            x, y = _number(entity.get("x")), _number(entity.get("y"))
            point = (x, y) if x is not None and y is not None else None
        if point is not None:
            positions[entity_id] = (float(point[0]), float(point[1]))
    if not positions:
        return None  # nothing to place a drawing on

    def tone(entity_id: str) -> str:
        return _HIGHLIGHT if entity_id in highlight else (_NEAR if entity_id in near else _INK)

    def poles(entity_id: str) -> List[Tuple[float, float]]:
        out: List[Tuple[float, float]] = []
        for raw in entities[entity_id].get("control_points", []):
            if isinstance(raw, str):
                if raw in positions:
                    out.append(positions[raw])
            elif isinstance(raw, Mapping) and raw.get("point_id") in positions:
                out.append(positions[raw["point_id"]])
            else:
                try:
                    x, y = _number(raw[0]), _number(raw[1])
                except (TypeError, IndexError, KeyError):
                    continue
                if x is not None and y is not None:
                    out.append((x, y))
        return out

    def anchor(entity_id: str) -> Optional[Tuple[float, float]]:
        entity = entities.get(entity_id)
        if entity is None:
            return None
        kind = entity["kind"]
        if kind == "point":
            return positions.get(entity_id)
        if kind == "line":
            start, end = positions.get(str(entity.get("start"))), positions.get(str(entity.get("end")))
            if start and end:
                return ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        if kind in {"circle", "arc", "ellipse"}:
            return positions.get(str(entity.get("center")))
        if kind == "bspline":
            pts = poles(entity_id)
            if pts:
                return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        return None

    extent: List[Tuple[float, float]] = []
    figure, axes = plt.subplots(figsize=(10.0, 7.0), dpi=100)
    path = _path(f"sketch-{mode}")
    try:
        for entity_id in order:
            entity = entities[entity_id]
            colour = tone(entity_id)
            weight = 2.8 if entity_id in highlight else 1.4
            style = (0, (4, 3)) if entity.get("construction") else "solid"
            if entity.get("construction") and colour == _INK:
                colour = _CONSTRUCTION
            kind = entity["kind"]
            if kind == "point":
                extent.append(positions[entity_id])
                axes.plot(*positions[entity_id], marker="o", markersize=9 if entity_id in highlight else 6, color=colour)
            elif kind == "line":
                start, end = positions.get(str(entity.get("start"))), positions.get(str(entity.get("end")))
                if start and end:
                    extent.extend((start, end))
                    axes.plot([start[0], end[0]], [start[1], end[1]], color=colour, linewidth=weight, linestyle=style)
            elif kind == "circle":
                centre = positions.get(str(entity.get("center")))
                radius = _number(scalars.get(f"circle:{entity_id}:radius")) or _number(entity.get("radius"))
                if centre and radius:
                    extent.extend(((centre[0] - radius, centre[1] - radius), (centre[0] + radius, centre[1] + radius)))
                    axes.add_patch(Circle(centre, radius, fill=False, edgecolor=colour, linewidth=weight, linestyle=style))
            elif kind == "arc":
                centre, start, end = (positions.get(str(entity.get(k))) for k in ("center", "start", "end"))
                if centre and start and end:
                    radius = math.dist(centre, start)
                    extent.extend(((centre[0] - radius, centre[1] - radius), (centre[0] + radius, centre[1] + radius)))
                    a0 = math.degrees(math.atan2(start[1] - centre[1], start[0] - centre[0]))
                    a1 = math.degrees(math.atan2(end[1] - centre[1], end[0] - centre[0]))
                    if (a1 - a0) % 360.0 > 180.0:  # the minor arc is the schematic
                        a0, a1 = a1, a0
                    axes.add_patch(Arc(centre, 2 * radius, 2 * radius, theta1=a0, theta2=a1, edgecolor=colour,
                                       linewidth=weight, linestyle=style))
            elif kind == "ellipse":
                centre, major, minor = (positions.get(str(entity.get(k))) for k in ("center", "major", "minor"))
                if centre and major and minor:
                    a, b = math.dist(centre, major), math.dist(centre, minor)
                    reach = max(a, b)
                    extent.extend(((centre[0] - reach, centre[1] - reach), (centre[0] + reach, centre[1] + reach)))
                    angle = math.degrees(math.atan2(major[1] - centre[1], major[0] - centre[0]))
                    axes.add_patch(Ellipse(centre, 2 * a, 2 * b, angle=angle, fill=False, edgecolor=colour,
                                           linewidth=weight, linestyle=style))
            elif kind == "bspline":
                pts = poles(entity_id)
                if len(pts) >= 2:
                    extent.extend(pts)
                    axes.plot([p[0] for p in pts], [p[1] for p in pts], color=colour, linewidth=weight * 0.75,
                              linestyle=(0, (2, 3)))
        for entity_id, position in positions.items():
            if entity_id in highlight or entity_id in near:
                axes.annotate(entity_id, position, xytext=(6, 6), textcoords="offset points", fontsize=10,
                              fontweight="bold", color=tone(entity_id))
        constraints = {c["id"]: c for c in sketch.get("constraints", [])}
        for constraint_id, _text in labels:
            constraint = constraints.get(constraint_id)
            if not constraint or not constraint.get("targets"):
                continue
            first = constraint["targets"][0]
            target = first.get("entity_id") if isinstance(first, Mapping) else first
            place = anchor(str(target))
            if place is not None:
                axes.annotate(constraint_id, place, xytext=(-14, -16), textcoords="offset points", fontsize=11,
                              fontweight="bold", color=_HIGHLIGHT,
                              bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": _HIGHLIGHT, "alpha": 0.9})
        xs, ys = [p[0] for p in extent], [p[1] for p in extent]
        pad_x = max((max(xs) - min(xs)) * 0.08, 1.0)
        pad_y = max((max(ys) - min(ys)) * 0.08, 1.0)
        axes.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
        axes.set_ylim(min(ys) - pad_y, max(ys) + pad_y)
        axes.set_aspect("equal", adjustable="box")
        axes.grid(True, color="#e6e6e6", linewidth=0.6)
        axes.tick_params(colors=_INK)
        title = f"{operation} — {mode}"
        if sketch.get("name"):
            title += f" — {sketch['name']}"
        axes.set_title(title, fontsize=13, fontweight="bold")
        axes.legend(handles=[Line2D([0], [0], color=_HIGHLIGHT, linewidth=3, label="implicated by the failure"),
                             Line2D([0], [0], color=_NEAR, linewidth=2, label="related (shares entities)"),
                             Line2D([0], [0], color=_INK, linewidth=1.4, label="uninvolved")],
                    loc="upper right", fontsize=9)
        figure.text(0.5, 0.015, "\n".join(textwrap.wrap(caption, width=110) or [caption]), ha="center", fontsize=9,
                    color="#555555", va="top")
        figure.savefig(path, bbox_inches="tight")
    finally:
        plt.close(figure)
    symbols = tuple((entity_id, entities[entity_id]["kind"])
                    for entity_id in list(sorted(highlight)) + [n for n in sorted(near) if n not in highlight]
                    if entity_id in entities)
    return _evidence("sketch_render", path, view, caption, symbols)


def install() -> None:
    """Register the provider with the C++ library (the SDK does it once, at import on the native backend)."""

    from . import _native

    _native._set_diagnostic_image_provider(provide)
    _native.ql._set_evidence_provider(_ql_evidence)

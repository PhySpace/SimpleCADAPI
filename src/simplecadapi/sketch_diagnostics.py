"""Sketch-solve failure diagnosis: structured conflict guidance + 2D evidence.

The sketch solver backend already pinpoints failing constraints (py-slvs
``reportFailed``), but the legacy raise path discarded that entirely and
emitted a one-line ``ValueError``.  This module upgrades the two failure
branches of ``Sketch.solve`` to the same error-guidance contract the other
P0 families use:

- **measurements** — DOF / constraint / entity counts at failure time;
- **inventory** — per-constraint rows (failed / near miss / ok) sharing the
  symbol space with the rendered figure;
- **repair** — names the conflicting constraint set and its shared entities,
  preferring relaxation of dimension-type constraints over geometric ones;
- **evidence** — a 2D schematic render (matplotlib, no OCC dependency) where
  entities referenced by failing constraints are highlighted orange and
  entities of likely conflict partners are purple.  This is the drawing
  engine's ``diag_png`` pattern transplanted to sketch documents.

Layering: this module sits beside ``sketch.py`` and imports only ``errors``
and ``_internal``; ``Sketch.solve`` imports it lazily inside the failure
branches so the import graph stays acyclic (operators may import sketch, never the reverse).  The
3D evidence machinery in ``operators/_diagnostics.py`` cannot be reused here
for the same reason.

Text axiom: every visual fact (which entities are implicated, which
constraints failed) also exists as text in the inventory and repair lines;
tests assert against the text, never the image.
"""

from __future__ import annotations

import math
import os
import textwrap
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ._internal.workspace import diagnostics_dir
from .errors import (
    ErrorEvidence,
    ErrorMeasurement,
    InventoryEntry,
    raise_harness_error,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import
    from .sketch import Sketch, SketchConstraint, SketchSolveResult

# Evidence palette — kept in family with the 3D diagnostics colors so agents
# see one consistent visual language: orange = implicated by the failure,
# purple = related/near-miss, gray ink = everything else.
_SKETCH_INK = "#3a3a3a"
_SKETCH_HIGHLIGHT = "#f39c12"   # orange, matches the 3D evidence highlight
_SKETCH_NEAR = "#8066bf"        # purple, matches the 3D near-miss tone
_SKETCH_CONSTRUCTION = "#9a9a9a"

# One render per distinct failure signature; retries of the same failure
# (common in agent repair loops) must not spam the diagnostics directory.
_SKETCH_RENDER_DEDUP: Set[str] = set()

# Inventory caps: the failed set and its partners are the actionable signal;
# satisfied constraints collapse into a single count row beyond this window.
_MAX_RELATED_CONSTRAINTS = 8
_MAX_INVENTORY_OK_ROWS = 8


def _render_enabled() -> bool:
    """Evidence rendering is default-ON on failure paths; env var opts out."""

    return not os.environ.get("SCA_NO_DIAGNOSTIC_RENDER")


def _as_float(value: Any) -> Optional[float]:
    """Best-effort float coercion returning ``None`` for non-numeric data."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _fmt(value: Any) -> str:
    """Compact numeric formatting for constraint values in text symbols."""

    number = _as_float(value)
    if number is None:
        return str(value)
    return f"{number:.4g}"


def _constraint_target_ids(constraint: "SketchConstraint") -> Set[str]:
    """Entity ids referenced by a constraint (any subentity)."""

    return {str(target.get("entity_id")) for target in constraint.targets}


def _describe_constraint(constraint: "SketchConstraint") -> str:
    """Human-readable one-line description, e.g. ``distance(p1, p2 = 5)``.

    Subentities (a circle's radius, an arc's start point) are folded into the
    symbol so the text and the figure labels stay same-source.
    """

    parts: List[str] = []
    for target in constraint.targets:
        label = str(target.get("entity_id"))
        subentity = str(target.get("subentity", "geometry"))
        if subentity and subentity != "geometry":
            label = f"{label}.{subentity}"
        parts.append(label)
    rendered = ", ".join(parts)
    if constraint.value is not None:
        rendered = f"{rendered} = {_fmt(constraint.value)}"
    return f"{constraint.kind}({rendered})"


# ---------------------------------------------------------------------------
# Geometry resolution for the 2D schematic
# ---------------------------------------------------------------------------


def _point_positions(
    sketch: "Sketch",
    result: Optional["SketchSolveResult"],
) -> Dict[str, Tuple[float, float]]:
    """Positions for every point entity: solved when available, initial otherwise.

    On a failed solve the solver's last state is still the best estimate of
    where the sketch "wanted" to be, which is exactly what a conflict diagram
    should show; initial coordinates are the honest fallback.
    """

    positions: Dict[str, Tuple[float, float]] = {}
    solved = dict(result.solved_points) if result is not None else {}
    for entity_id in sketch.entity_order:
        entity = sketch.entities[entity_id]
        if entity.kind != "point":
            continue
        point = solved.get(entity_id)
        if point is None:
            x = _as_float(entity.data.get("x"))
            y = _as_float(entity.data.get("y"))
            point = (x, y) if x is not None and y is not None else None
        if point is not None:
            positions[entity_id] = (float(point[0]), float(point[1]))
    return positions


def _circle_radius(
    sketch: "Sketch",
    entity_id: str,
    result: Optional["SketchSolveResult"],
) -> Optional[float]:
    """Circle radius from the solved scalars, falling back to the authored value."""

    if result is not None:
        solved = result.solved_scalars.get(f"circle:{entity_id}:radius")
        if solved is not None and math.isfinite(float(solved)):
            return float(solved)
    return _as_float(sketch.entities[entity_id].data.get("radius"))


def _bspline_control_points(
    sketch: "Sketch",
    entity_id: str,
    positions: Mapping[str, Tuple[float, float]],
) -> List[Tuple[float, float]]:
    """B-spline control points as plot coordinates (refs resolve, literals pass).

    The dashed control polygon is a schematic, not an exact curve evaluation;
    for conflict diagnosis "where are the poles" is the actionable question.
    """

    raw_points = sketch.entities[entity_id].data.get("control_points", [])
    resolved: List[Tuple[float, float]] = []
    for raw in raw_points:
        if isinstance(raw, str):
            point = positions.get(str(raw))
            if point is not None:
                resolved.append(point)
            continue
        try:
            x = _as_float(raw[0])
            y = _as_float(raw[1])
        except (TypeError, IndexError):
            continue
        if x is not None and y is not None:
            resolved.append((x, y))
    return resolved


def _entity_anchor(
    sketch: "Sketch",
    entity_id: str,
    positions: Mapping[str, Tuple[float, float]],
    result: Optional["SketchSolveResult"],
) -> Optional[Tuple[float, float]]:
    """A representative anchor point for placing an entity's text label."""

    entity = sketch.entities.get(entity_id)
    if entity is None:
        return None
    if entity.kind == "point":
        return positions.get(entity_id)
    if entity.kind == "line":
        start = positions.get(str(entity.data.get("start")))
        end = positions.get(str(entity.data.get("end")))
        if start is not None and end is not None:
            return ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    if entity.kind in {"circle", "arc", "ellipse"}:
        return positions.get(str(entity.data.get("center")))
    if entity.kind == "bspline":
        poles = _bspline_control_points(sketch, entity_id, positions)
        if poles:
            return (
                sum(pole[0] for pole in poles) / len(poles),
                sum(pole[1] for pole in poles) / len(poles),
            )
    return None


# ---------------------------------------------------------------------------
# Evidence render (matplotlib schematic, single 2D view)
# ---------------------------------------------------------------------------


def render_sketch_evidence(
    sketch: "Sketch",
    result: Optional["SketchSolveResult"],
    *,
    operation: str,
    mode: str,
    caption: str,
    highlight_entity_ids: Iterable[str],
    near_entity_ids: Iterable[str],
    constraint_labels: Sequence[Tuple[str, str]],
    dedup_key: str,
) -> Optional[ErrorEvidence]:
    """Render the 2D conflict schematic and return its evidence descriptor.

    Sketches are planar, so a single view is the correct evidence format
    (the four-axonometric rule targets 3D occlusion, which cannot happen
    here).  Failures of the render itself never mask the error: ``None`` is
    returned and the structured error still goes out text-complete.

    ``constraint_labels`` pairs ``(constraint_id, description)`` drawn onto
    the figure next to their first target's anchor so the figure and the
    text repair lines share one symbol table.
    """

    if not _render_enabled():
        return None
    if dedup_key in _SKETCH_RENDER_DEDUP:
        return None
    _SKETCH_RENDER_DEDUP.add(dedup_key)

    positions = _point_positions(sketch, result)
    if not positions:
        # A sketch without any resolvable point geometry (e.g. only free
        # circles whose center points were never added) cannot be drawn.
        return None

    highlight = {str(item) for item in highlight_entity_ids}
    near = {str(item) for item in near_entity_ids}

    # Bounding samples of every drawn primitive (not just point positions):
    # circles/arcs/ellipses extend beyond their defining points, and the
    # frame must contain them or the schematic clips the very geometry the
    # failure is about.
    extent_points: List[Tuple[float, float]] = []

    def tone(entity_id: str) -> str:
        if entity_id in highlight:
            return _SKETCH_HIGHLIGHT
        if entity_id in near:
            return _SKETCH_NEAR
        return _SKETCH_INK

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.patches import Arc, Circle, Ellipse
    except Exception:
        return None

    figure, axes = plt.subplots(figsize=(10.0, 7.0), dpi=100)
    try:
        # --- geometry ink -------------------------------------------------
        for entity_id in sketch.entity_order:
            entity = sketch.entities[entity_id]
            color = tone(entity_id)
            weight = 2.8 if entity_id in highlight else 1.4
            linestyle = (0, (4, 3)) if entity.construction else "solid"
            if entity.construction:
                color = _SKETCH_CONSTRUCTION if color == _SKETCH_INK else color
            if entity.kind == "point":
                extent_points.append(positions[entity_id])
                axes.plot(
                    *positions[entity_id],
                    marker="o",
                    markersize=9 if entity_id in highlight else 6,
                    color=color,
                )
            elif entity.kind == "line":
                start = positions.get(str(entity.data.get("start")))
                end = positions.get(str(entity.data.get("end")))
                if start and end:
                    extent_points.extend((start, end))
                    axes.plot(
                        [start[0], end[0]], [start[1], end[1]],
                        color=color, linewidth=weight, linestyle=linestyle,
                    )
            elif entity.kind == "circle":
                center = positions.get(str(entity.data.get("center")))
                radius = _circle_radius(sketch, entity_id, result)
                if center and radius:
                    extent_points.extend((
                        (center[0] - radius, center[1] - radius),
                        (center[0] + radius, center[1] + radius),
                    ))
                    axes.add_patch(
                        Circle(center, radius, fill=False, edgecolor=color,
                               linewidth=weight, linestyle=linestyle)
                    )
            elif entity.kind == "arc":
                center = positions.get(str(entity.data.get("center")))
                start = positions.get(str(entity.data.get("start")))
                end = positions.get(str(entity.data.get("end")))
                if center and start and end:
                    radius = math.dist(center, start)
                    extent_points.extend((
                        (center[0] - radius, center[1] - radius),
                        (center[0] + radius, center[1] + radius),
                    ))
                    start_angle = math.degrees(math.atan2(
                        start[1] - center[1], start[0] - center[0]))
                    end_angle = math.degrees(math.atan2(
                        end[1] - center[1], end[0] - center[0]))
                    # Arc direction is not reconstructed from the entity
                    # data; the minor arc is drawn as the schematic.
                    span = (end_angle - start_angle) % 360.0
                    if span > 180.0:
                        start_angle, end_angle = end_angle, start_angle
                    axes.add_patch(
                        Arc(center, 2 * radius, 2 * radius, theta1=start_angle,
                            theta2=end_angle, edgecolor=color, linewidth=weight,
                            linestyle=linestyle)
                    )
            elif entity.kind == "ellipse":
                center = positions.get(str(entity.data.get("center")))
                major = positions.get(str(entity.data.get("major")))
                minor = positions.get(str(entity.data.get("minor")))
                if center and major and minor:
                    a = math.dist(center, major)
                    b = math.dist(center, minor)
                    reach = max(a, b)
                    extent_points.extend((
                        (center[0] - reach, center[1] - reach),
                        (center[0] + reach, center[1] + reach),
                    ))
                    angle = math.degrees(math.atan2(
                        major[1] - center[1], major[0] - center[0]))
                    axes.add_patch(
                        Ellipse(center, 2 * a, 2 * b, angle=angle, fill=False,
                                edgecolor=color, linewidth=weight,
                                linestyle=linestyle)
                    )
            elif entity.kind == "bspline":
                poles = _bspline_control_points(sketch, entity_id, positions)
                if len(poles) >= 2:
                    extent_points.extend(poles)
                    axes.plot(
                        [p[0] for p in poles], [p[1] for p in poles],
                        color=color, linewidth=weight * 0.75,
                        linestyle=(0, (2, 3)),
                    )

        # --- entity id labels (the shared symbol table) -------------------
        for entity_id, position in positions.items():
            if entity_id in highlight or entity_id in near:
                axes.annotate(
                    entity_id, position, xytext=(6, 6),
                    textcoords="offset points", fontsize=10, fontweight="bold",
                    color=tone(entity_id),
                )

        # --- failing constraint ids next to their first target ------------
        for constraint_id, _description in constraint_labels:
            constraint = next(
                (c for c in sketch.constraints
                 if c.constraint_id == constraint_id), None,
            )
            if constraint is None or not constraint.targets:
                continue
            target_id = str(constraint.targets[0].get("entity_id"))
            anchor = _entity_anchor(sketch, target_id, positions, result)
            if anchor is None:
                continue
            axes.annotate(
                constraint_id, anchor, xytext=(-14, -16),
                textcoords="offset points", fontsize=11, fontweight="bold",
                color=_SKETCH_HIGHLIGHT,
                bbox={"boxstyle": "round,pad=0.2", "fc": "white",
                      "ec": _SKETCH_HIGHLIGHT, "alpha": 0.9},
            )

        # --- framing: equal aspect, padded to the drawn geometry ----------
        xs = [p[0] for p in extent_points]
        ys = [p[1] for p in extent_points]
        pad_x = max((max(xs) - min(xs)) * 0.08, 1.0)
        pad_y = max((max(ys) - min(ys)) * 0.08, 1.0)
        axes.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
        axes.set_ylim(min(ys) - pad_y, max(ys) + pad_y)
        # "box" adjusts the axes box instead of fighting the fixed data
        # limits (which emits a matplotlib warning on degenerate spans).
        axes.set_aspect("equal", adjustable="box")
        axes.grid(True, color="#e6e6e6", linewidth=0.6)
        axes.tick_params(colors=_SKETCH_INK)

        title = f"{operation} — {mode}"
        if sketch.name:
            title += f" — {sketch.name}"
        axes.set_title(title, fontsize=13, fontweight="bold")

        handles = [
            Line2D([0], [0], color=_SKETCH_HIGHLIGHT, linewidth=3,
                   label="implicated by the failure"),
            Line2D([0], [0], color=_SKETCH_NEAR, linewidth=2,
                   label="related (shares entities)"),
            Line2D([0], [0], color=_SKETCH_INK, linewidth=1.4,
                   label="uninvolved"),
        ]
        axes.legend(handles=handles, loc="upper right", fontsize=9)
        wrapped_caption = "\n".join(
            textwrap.wrap(caption, width=110) or [caption]
        )
        figure.text(
            0.5, 0.015, wrapped_caption, ha="center",
            fontsize=9, color="#555555", va="top",
        )

        root = diagnostics_dir()
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = root / f"sketch-{mode}-{stamp}.png"
        figure.savefig(path, bbox_inches="tight")
    except Exception:
        return None
    finally:
        plt.close(figure)

    symbols = tuple(
        (entity_id, sketch.entities[entity_id].kind)
        for entity_id in list(highlight) + [n for n in near if n not in highlight]
        if entity_id in sketch.entities
    )
    return ErrorEvidence(
        kind="sketch_render",
        path=str(path),
        view="sketch plane",
        caption=caption,
        symbols=symbols,
    )


# ---------------------------------------------------------------------------
# Diagnosis entry points (called from Sketch.solve failure branches)
# ---------------------------------------------------------------------------


def _constraint_inventory(
    sketch: "Sketch",
    failed: Dict[str, "SketchConstraint"],
    related: Dict[str, "SketchConstraint"],
) -> Tuple[InventoryEntry, ...]:
    """Per-constraint inventory rows sharing the figure's symbol space.

    Failed and related constraints get individual rows; uninvolved ones are
    capped (they are context, not signal) and collapse into one count row.
    """

    entries: List[InventoryEntry] = []
    for constraint_id, constraint in failed.items():
        entries.append(InventoryEntry(
            symbol=constraint_id,
            status="failed",
            description=_describe_constraint(constraint),
        ))
    for constraint_id, constraint in related.items():
        entries.append(InventoryEntry(
            symbol=constraint_id,
            status="near miss",
            description=f"{_describe_constraint(constraint)} (shares entities with the failed set)",
        ))
    uninvolved = [
        constraint for constraint in sketch.constraints
        if constraint.constraint_id not in failed
        and constraint.constraint_id not in related
    ]
    for constraint in uninvolved[:_MAX_INVENTORY_OK_ROWS]:
        entries.append(InventoryEntry(
            symbol=constraint.constraint_id,
            status="ok",
            description=_describe_constraint(constraint),
        ))
    if len(uninvolved) > _MAX_INVENTORY_OK_ROWS:
        entries.append(InventoryEntry(
            symbol=f"({len(uninvolved) - _MAX_INVENTORY_OK_ROWS} more)",
            status="ok",
            description="constraints not implicated by the solver",
        ))
    return tuple(entries)


def raise_sketch_solve_failure(
    sketch: "Sketch",
    result: "SketchSolveResult",
) -> None:
    """Raise the structured error for a conflicting / failed solve.

    The solver names the failing constraints; this function turns them into
    measurements, a repair plan (relax dimensions before geometry), and a
    2D schematic where the implicated entities are highlighted.
    """

    failed_ids = {
        diagnostic.constraint_id
        for diagnostic in result.diagnostics
        if diagnostic.severity == "error" and diagnostic.constraint_id
    }
    failed = {
        constraint.constraint_id: constraint
        for constraint in sketch.constraints
        if constraint.constraint_id in failed_ids
    }
    # Related = not itself failed but shares an entity with a failed
    # constraint — these are the direct conflict partners the solver could
    # not name individually.
    implicated_entities: Set[str] = set()
    for constraint in failed.values():
        implicated_entities |= _constraint_target_ids(constraint)
    related: Dict[str, "SketchConstraint"] = {}
    for constraint in sketch.constraints:
        if constraint.constraint_id in failed:
            continue
        if _constraint_target_ids(constraint) & implicated_entities:
            related[constraint.constraint_id] = constraint
    related = dict(list(related.items())[:_MAX_RELATED_CONSTRAINTS])

    measurements = [
        ErrorMeasurement("constraint count", len(sketch.constraints)),
        ErrorMeasurement("entity count", len(sketch.entities)),
        ErrorMeasurement("conflicting constraints", len(failed)),
        ErrorMeasurement("solver DOF at failure", result.dof),
    ]
    for constraint_id, constraint in failed.items():
        value = _as_float(constraint.value)
        if value is not None:
            measurements.append(ErrorMeasurement(
                f"constraint {constraint_id} value", value))

    repair: List[str] = []
    for constraint_id, constraint in failed.items():
        partners = ", ".join(
            related_id for related_id in related
            if _constraint_target_ids(related[related_id])
            & _constraint_target_ids(constraint)
        )
        line = (
            f"Delete or relax {constraint_id}({_describe_constraint(constraint)})"
        )
        if partners:
            line += (
                f" — it constrains the same entities together with {partners}, "
                "making them a direct conflict pair"
            )
        repair.append(line)
    if failed:
        dimension_kinds = {
            "distance", "distance_x", "distance_y", "length", "radius",
            "diameter", "angle", "ratio",
        }
        dimension_side = [
            constraint_id for constraint_id in failed
            if failed[constraint_id].kind in dimension_kinds
        ]
        if dimension_side:
            repair.append(
                f"Prefer relaxing dimension-type constraints first ({', '.join(dimension_side)}) "
                "and keep geometric ones (coincident/tangent/parallel/horizontal/vertical) "
                "— the geometric intent is usually the design intent"
            )
        else:
            repair.append(
                "The conflict set is entirely geometric: delete the weakest "
                "one (usually the last added), or lift the fix constraint on "
                "its target entities first"
            )
    else:
        repair.append(
            "The solver did not name individual constraints: bisect the "
            "constraint set (disable the second half first, then the first) "
            "to locate the conflict pair, or rerun "
            "inspect_sketch_rsketchresult(strict=False) for per-constraint "
            "diagnostics"
        )
    repair.append(
        "Rerun inspect_sketch_rsketchresult(sketch, strict=False) to get "
        "per-constraint diagnostics without raising"
    )

    evidence: List[ErrorEvidence] = []
    highlight_entities = set(implicated_entities)
    near_entities = set()
    for constraint in related.values():
        near_entities |= _constraint_target_ids(constraint)
    near_entities -= highlight_entities
    constraint_labels = [
        (constraint_id, _describe_constraint(constraint))
        for constraint_id, constraint in failed.items()
    ]
    evidence_render = render_sketch_evidence(
        sketch,
        result,
        operation="sketch_solve",
        mode=str(result.status),
        caption=(
            f"status={result.status}, backend={result.backend}: "
            f"orange = entities implicated by failed constraints "
            f"({', '.join(sorted(failed)) or 'solver did not name any'}), "
            f"purple = related constraints sharing those entities"
        ),
        highlight_entity_ids=highlight_entities,
        near_entity_ids=near_entities,
        constraint_labels=constraint_labels,
        dedup_key=(
            f"sketch:{sketch.sketch_id}:{result.status}:"
            f"{','.join(sorted(failed))}"
        ),
    )
    if evidence_render is not None:
        evidence.append(evidence_render)

    what_happened = (
        f"Sketch solve failed with status '{result.status}' "
        f"(backend {result.backend})"
    )
    if failed:
        described = "; ".join(
            f"{constraint_id}({_describe_constraint(constraint)})"
            for constraint_id, constraint in failed.items()
        )
        what_happened += f"; the solver named {len(failed)} failing constraint(s): {described}"
    else:
        what_happened += "; the solver did not name individual constraints"

    raise_harness_error(
        operation="sketch_solve",
        what_happened=what_happened,
        possible_causes=[
            "Two or more constraints impose incompatible requirements on the same entities.",
            "A dimension contradicts a geometric constraint (e.g. a distance smaller than a tangency allows).",
            "A constraint references entities whose solved positions cannot satisfy it.",
        ],
        how_to_fix=[
            "Read the Inventory rows marked [failed] and [near miss]: they share entities and conflict there.",
            "Relax or delete one constraint from each conflicting pair (see the repair lines).",
        ],
        measurements=measurements,
        evidence=evidence,
        repair=repair,
        inventory=_constraint_inventory(sketch, failed, related),
        technical_details=(
            f"sketch_id={sketch.sketch_id}, backend={result.backend}, "
            f"backend_status_code={result.backend_status_code}"
        ),
    )


def raise_sketch_underconstrained(
    sketch: "Sketch",
    result: "SketchSolveResult",
) -> None:
    """Raise the structured error for a solve that left DOF behind.

    The strongest computable signal is the set of entities no constraint
    references at all; combined with the DOF count this gives the agent a
    concrete "constrain these" list instead of a bare number.
    """

    referenced: Set[str] = set()
    for constraint in sketch.constraints:
        referenced |= _constraint_target_ids(constraint)
    unreferenced = [
        entity_id for entity_id in sketch.entity_order
        if entity_id not in referenced
    ]

    measurements = [
        ErrorMeasurement("remaining DOF", result.dof),
        ErrorMeasurement("constraint count", len(sketch.constraints)),
        ErrorMeasurement("unconstrained entities", len(unreferenced)),
    ]

    repair: List[str] = []
    if unreferenced:
        shown = ", ".join(unreferenced[:12])
        more = (
            f" (+{len(unreferenced) - 12} more)"
            if len(unreferenced) > 12 else ""
        )
        repair.append(
            f"These entities are not referenced by any constraint — fix or "
            f"dimension them first: {shown}{more} "
            "(constrain_fix_rsketch / constrain_distance_rsketch and friends)"
        )
    repair.extend([
        "DOF accounting reference: each free point is 2 DOF, a free circle "
        "is 3 (center 2 + radius 1), a free line is 4",
        "Express symmetry intent with geometric constraints "
        "(horizontal/vertical/parallel) and leave only final dimensions to "
        "dimension constraints",
        "Rerun inspect_sketch_rsketchresult(sketch) and confirm the DOF "
        "reaches 0 before requiring full constraint",
    ])

    evidence: List[ErrorEvidence] = []
    evidence_render = render_sketch_evidence(
        sketch,
        result,
        operation="sketch_solve",
        mode="underconstrained",
        caption=(
            f"{result.dof} DOF remain: orange = entities no constraint "
            "references (certainly free); the solver accepted the geometry "
            "but cannot hold it"
        ),
        highlight_entity_ids=unreferenced,
        near_entity_ids=[],
        constraint_labels=[],
        dedup_key=f"sketch:{sketch.sketch_id}:underconstrained:{result.dof}",
    )
    if evidence_render is not None:
        evidence.append(evidence_render)

    inventory = tuple(
        InventoryEntry(
            symbol=entity_id,
            status="unconstrained",
            description=f"{sketch.entities[entity_id].kind} — not referenced by any constraint",
        )
        for entity_id in unreferenced[:_MAX_INVENTORY_OK_ROWS + 8]
    ) + (
        (InventoryEntry(
            symbol=f"({len(referenced)} constrained)",
            status="ok",
            description="entities referenced by at least one constraint "
            "(may still be partially free — see DOF)",
        ),)
        if referenced else ()
    )

    raise_harness_error(
        operation="sketch_solve",
        what_happened=(
            f"Sketch solve succeeded geometrically but {result.dof} degrees of "
            f"freedom remain; a fully constrained result was required"
            + (
                f" and {len(unreferenced)} entities are not referenced by any constraint"
                if unreferenced else ""
            )
        ),
        possible_causes=[
            "Points or curves were added without fix/dimension constraints.",
            "require_fully_constrained=True was set before the profile's dimensions were fully specified.",
        ],
        how_to_fix=[
            "Constrain the entities listed as [unconstrained] in the inventory.",
            "Re-inspect with inspect_sketch_rsketchresult until the DOF reaches 0.",
        ],
        measurements=measurements,
        evidence=evidence,
        repair=repair,
        inventory=inventory,
        technical_details=(
            f"sketch_id={sketch.sketch_id}, backend={result.backend}"
        ),
    )

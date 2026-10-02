"""Failure-time geometric diagnosis and evidence rendering.

Diagnosis runs only on failure paths, computes the geometric facts behind the
failure (measurements), and optionally renders one evidence image under
``.simplecad/diagnostics`` in the working directory. Everything here is best-effort: a diagnosis crash must never
replace the real error, so public entries swallow their own failures.
"""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

from .._internal.workspace import diagnostics_dir
from ..errors import (
    ErrorEvidence,
    ErrorMeasurement,
    InventoryEntry,
    raise_harness_error,
)
from ..kernel.ocp_booleans import common_shapes
from ..kernel.ocp_properties import volume

_DISABLE_ENV = "SCA_NO_DIAGNOSTIC_RENDER"
_TRUTHY = {"1", "true", "yes", "on"}

# Cap on pairwise probes: boolean inputs are small in practice; guard the
# quadratic blow-up for pathological operand counts instead of hanging the
# failure path.
_MAX_PAIR_PROBES = 256

# Evidence rendering runs on the failure path, so it stays bounded: one
# downgraded render per distinct failure signature, abandoned after this
# many seconds (the render worker's own 180s x 6 retries must never hold
# the error hostage).
_RENDER_BUDGET_SECONDS = 15.0
_RENDER_DEDUP: set = set()

# Four axonometric positions, one per viewing corner: a highlighted edge or
# face hidden behind the model in one iso is visible from another. Ruled by
# the user — NOT one iso plus three orthographic projections; agents need
# depth cues to read 3D relationships in every panel.
_DIAGNOSTIC_VIEWS = (
    (30.0, 45.0, "iso FR"),
    (30.0, 135.0, "iso BR"),
    (30.0, 225.0, "iso BL"),
    (30.0, 315.0, "iso FL"),
)


def diagnostics_enabled() -> bool:
    return os.environ.get(_DISABLE_ENV, "").strip().lower() not in _TRUTHY


# Ink palette for the 2D wire-plan schematics — same visual language as the
# sketch-diagnostics figures and the 3D evidence palette: orange marks the
# implicated geometry, purple related, dark ink everything else.
_PLAN_INK = "#3a3a3a"
_PLAN_HIGHLIGHT = "#f39c12"
_PLAN_NEAR = "#8066bf"


def _sample_edge_polyline(edge: Any, samples: int = 16) -> List[Tuple[float, float, float]]:
    """Polylines of an edge by uniform parameter sampling (3D points).

    Sampling avoids OCC meshing entirely — the 3D VTK pipeline cannot render
    bare wires ("no renderable triangles"), so wire evidence goes through a
    planar 2D schematic instead.  Straight lines collapse to two points;
    curves keep their shape.
    """

    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.TopoDS import TopoDS

        raw_edge = edge.wrapped if hasattr(edge, "wrapped") else edge
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(raw_edge))
        first, last = curve.FirstParameter(), curve.LastParameter()
        if curve.GetType() == 0:  # GeomAbs_Line: endpoints are exact
            count = 2
        else:
            count = max(samples, 3)
        return [
            (lambda p: (float(p.X()), float(p.Y()), float(p.Z())))(
                curve.Value(first + (last - first) * index / (count - 1))
            )
            for index in range(count)
        ]
    except Exception:
        return []


def render_wire_plan_evidence(
    wire_groups: Sequence[Tuple[Any, str]],
    *,
    operation: str,
    caption: str,
    dedup_key: tuple,
    point_marks: Sequence[Tuple[Tuple[float, float, float], str, str]] = (),
    label_at: Sequence[Tuple[Tuple[float, float, float], str]] = (),
) -> Optional[ErrorEvidence]:
    """Render wires as a 2D plan schematic (best-fit-plane projection).

    ``wire_groups`` pairs ``(wire, tone)`` with tone ``"ink"``/``"highlight"``/
    ``"near"``; ``point_marks`` are 3D points to pin with ``(point, label,
    tone)``; ``label_at`` places plain text labels.  All geometry is sampled
    to polylines, projected onto the PCA plane of the whole figure, and
    drawn with matplotlib — the same schematic style as the sketch-solve
    evidence.  Non-planar inputs still render (as a projection) and the
    caption says so when it matters.

    Best-effort like every evidence channel: any failure returns None and
    the structured error stays text-complete.
    """

    if not diagnostics_enabled():
        return None
    if dedup_key in _RENDER_DEDUP:
        return None
    _RENDER_DEDUP.add(dedup_key)

    polylines: List[Tuple[List[Tuple[float, float, float]], str]] = []
    all_points: List[Tuple[float, float, float]] = []
    for entry, tone in wire_groups:
        # Entries may be whole Wires or single Edges (highlight targets).
        if hasattr(entry, "_iter_edges"):
            try:
                edges = list(entry._iter_edges())
            except Exception:
                continue
        else:
            edges = [entry]
        for edge in edges:
            points = _sample_edge_polyline(edge)
            if len(points) >= 2:
                polylines.append((points, tone))
                all_points.extend(points)
    for point, _label, _tone in point_marks:
        all_points.append(point)
    if len(all_points) < 2:
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.lines import Line2D
    except Exception:
        return None

    try:
        matrix = np.array(all_points, dtype=float)
        centered = matrix - matrix.mean(axis=0)
        # PCA basis: first two principal directions span the best-fit plane.
        _, _, right = np.linalg.svd(centered, full_matrices=False)
        basis_u, basis_v = right[0], right[1]

        def _to_plan(point) -> Tuple[float, float]:
            return (float(np.dot(point, basis_u)), float(np.dot(point, basis_v)))

        figure, axes = plt.subplots(figsize=(10.0, 7.0), dpi=100)
        plan_points: List[Tuple[float, float]] = []
        for points, tone in polylines:
            plan = [_to_plan(point) for point in points]
            plan_points.extend(plan)
            color = {"ink": _PLAN_INK, "highlight": _PLAN_HIGHLIGHT, "near": _PLAN_NEAR}.get(tone, _PLAN_INK)
            axes.plot(
                [p[0] for p in plan], [p[1] for p in plan],
                color=color,
                linewidth=3.2 if tone == "highlight" else 1.6,
                solid_capstyle="round",
            )
        for point, label, tone in point_marks:
            plan = _to_plan(point)
            plan_points.append(plan)
            color = {"ink": _PLAN_INK, "highlight": _PLAN_HIGHLIGHT, "near": _PLAN_NEAR}.get(tone, _PLAN_INK)
            axes.plot(*plan, marker="o", markersize=9, color=color)
            axes.annotate(
                label, plan, xytext=(8, 8), textcoords="offset points",
                fontsize=10, fontweight="bold", color=color,
                bbox={"boxstyle": "round,pad=0.2", "fc": "white",
                      "ec": color, "alpha": 0.9},
            )
        for point, label in label_at:
            plan = _to_plan(point)
            plan_points.append(plan)
            axes.annotate(label, plan, xytext=(6, -14), textcoords="offset points",
                          fontsize=10, fontweight="bold", color="#555555")

        if not plan_points:
            plt.close(figure)
            return None
        xs = [p[0] for p in plan_points]
        ys = [p[1] for p in plan_points]
        pad_x = max((max(xs) - min(xs)) * 0.08, 0.5)
        pad_y = max((max(ys) - min(ys)) * 0.08, 0.5)
        axes.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
        axes.set_ylim(min(ys) - pad_y, max(ys) + pad_y)
        axes.set_aspect("equal", adjustable="box")
        axes.grid(True, color="#e6e6e6", linewidth=0.6)
        axes.set_title(f"{operation} — wire plan (projected)", fontsize=13, fontweight="bold")
        handles = [
            Line2D([0], [0], color=_PLAN_HIGHLIGHT, linewidth=3.2,
                   label="implicated geometry"),
            Line2D([0], [0], color=_PLAN_NEAR, linewidth=2,
                   label="related"),
            Line2D([0], [0], color=_PLAN_INK, linewidth=1.6,
                   label="context"),
        ]
        axes.legend(handles=handles, loc="upper right", fontsize=9)
        import textwrap

        wrapped = "\n".join(textwrap.wrap(caption, width=110) or [caption])
        figure.text(0.5, 0.015, wrapped, ha="center", fontsize=9,
                    color="#555555", va="top")

        root = diagnostics_dir()
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = root / f"wire-{stamp}.png"
        figure.savefig(path, bbox_inches="tight")
    except Exception:
        return None
    finally:
        plt.close(figure)

    return ErrorEvidence(
        kind="wire_plan_render",
        path=str(path),
        view="best-fit plane projection",
        caption=caption,
    )


# --- Loft section compatibility diagnosis ----------------------------------


@dataclass(frozen=True)
class LoftSectionFacts:
    """Sampled facts about one loft section (the compatibility probe input)."""

    section_id: str
    edge_count: int
    closed: Optional[bool]
    planar: Optional[bool]
    centroid: Tuple[float, float, float]


def _loft_section_facts(
    sections: Sequence[Any],
) -> Optional[List[LoftSectionFacts]]:
    """Per-section edge counts, closure, planarity, and centroid.

    Returns None when sampling fails outright (the caller degrades to the
    generic wrap).  Vertex cap sections are summarized without geometry
    probes; they cannot carry edge counts.
    """

    facts: List[LoftSectionFacts] = []
    for index, section in enumerate(sections):
        section_id = f"S{index + 1}"
        if not hasattr(section, "_iter_edges"):
            # Vertex caps are legal only at the ends (validated upstream).
            try:
                from ..kernel.ocp_topology import vertex_point

                point = vertex_point(section.wrapped)
                facts.append(LoftSectionFacts(
                    section_id=section_id, edge_count=0, closed=None,
                    planar=None,
                    centroid=(float(point[0]), float(point[1]), float(point[2])),
                ))
                continue
            except Exception:
                return None
        try:
            edges = list(section._iter_edges())
            points: List[Tuple[float, float, float]] = []
            for edge in edges:
                points.extend(_sample_edge_polyline(edge))
            if not points:
                return None
            import numpy as np

            matrix = np.array(points, dtype=float)
            centroid = matrix.mean(axis=0)
            centered = matrix - centroid
            # Planarity via PCA: the third singular value is the out-of-plane
            # spread; compare it relative to the in-plane extent.
            singular = np.linalg.svd(centered, compute_uv=False)
            planar = (
                bool(singular[2] <= max(singular[0], 1e-12) * 1e-6)
                if len(singular) == 3 else None
            )
            facts.append(LoftSectionFacts(
                section_id=section_id,
                edge_count=len(edges),
                closed=bool(section.is_closed()),
                planar=planar,
                centroid=(float(centroid[0]), float(centroid[1]), float(centroid[2])),
            ))
        except Exception:
            return None
    return facts


def raise_loft_failure_if_diagnosed(
    sections: Sequence[Any],
    operation: str,
) -> None:
    """Diagnose a kernel loft failure from section facts; raise when explained.

    The kernel reports loft failures as a bare "build did not complete"
    naming nothing.  This probe re-reads the sections the agent passed and
    reports the computable compatibility verdicts: coincident consecutive
    sections, edge-count mismatches, open section wires, and non-monotonic
    station order.  Raises the structured error when any verdict lands;
    returns silently when nothing diagnosable is found (the caller then
    applies the generic wrap).
    """

    facts = _loft_section_facts(sections)
    if facts is None or len(facts) < 2:
        return

    repair: List[str] = []
    findings: List[str] = []
    implicated: Set[str] = set()

    # Coincident consecutive stations: the most common "did not complete"
    # cause when sections were authored at the same height.
    for (fact_a, fact_b) in zip(facts, facts[1:]):
        distance = math.dist(fact_a.centroid, fact_b.centroid)
        if distance <= 1e-9:
            findings.append(
                f"{fact_b.section_id} coincides with {fact_a.section_id} "
                f"(centroid distance {distance:.3g} mm)"
            )
            implicated.update((fact_a.section_id, fact_b.section_id))
            repair.append(
                f"{fact_a.section_id} and {fact_b.section_id} sit at the same "
                "location: a loft needs its sections distributed along the "
                "generation direction — remove the duplicate section or fix "
                "the station placements"
            )

    # Edge-count mismatch: correspondence-based skinning needs comparable
    # station topology; wildly different counts are the classic rejection.
    wire_facts = [fact for fact in facts if fact.edge_count > 0]
    if wire_facts:
        counts = {fact.edge_count for fact in wire_facts}
        if len(counts) > 1:
            described = ", ".join(
                f"{fact.section_id}={fact.edge_count}" for fact in wire_facts
            )
            findings.append(f"edge counts differ across stations: {described}")
            implicated.update(fact.section_id for fact in wire_facts)
            repair.append(
                "Make the edge count consistent across stations (split or "
                "approximate curve stations when mixing with straight-line "
                "stations), or split the loft at stations where the topology "
                "undergoes birth/death/split/merge"
            )

    # Open section wires: a solid loft needs closed loops.
    for fact in wire_facts:
        if fact.closed is False:
            findings.append(f"{fact.section_id} is not closed")
            implicated.add(fact.section_id)
            repair.append(
                f"{fact.section_id} is an open wire: close that section "
                "before lofting"
            )

    # Station ordering: project centroids onto the first→last axis; any
    # backtrack means the section list is out of order.
    first, last = facts[0].centroid, facts[-1].centroid
    axis = [last[i] - first[i] for i in range(3)]
    axis_norm = math.dist(first, last)
    if axis_norm > 1e-9 and len(facts) > 2:
        projections = [
            sum(
                (fact.centroid[i] - first[i]) * axis[i] for i in range(3)
            ) / axis_norm
            for fact in facts
        ]
        backtracks = [
            facts[index].section_id
            for index in range(1, len(projections))
            if projections[index] < projections[index - 1] - 1e-9
        ]
        if backtracks:
            findings.append(
                "section centroids backtrack along the first-to-last axis "
                "(likely out of order): " + ", ".join(backtracks)
            )
            implicated.update(backtracks)
            repair.append(
                f"{', '.join(backtracks)} step backwards along the generation "
                "direction: reorder the section list"
            )

    if not findings:
        return

    inventory = []
    for fact in facts:
        if fact.edge_count == 0:
            description = f"vertex cap, at {_vector_display(fact.centroid)}"
        else:
            description = (
                f"{fact.edge_count} edges, "
                f"{'closed' if fact.closed else 'OPEN'}, "
                f"{'planar' if fact.planar else 'non-planar'}, "
                f"centroid {_vector_display(fact.centroid)}"
            )
        inventory.append(InventoryEntry(
            symbol=fact.section_id,
            status="implicated" if fact.section_id in implicated else "ok",
            description=description,
        ))

    evidence: List[ErrorEvidence] = []
    rendered = render_wire_plan_evidence(
        [
            (section, "highlight" if fact.section_id in implicated else "ink")
            for section, fact in zip(sections, facts)
            if hasattr(section, "_iter_edges")
        ],
        operation=operation,
        caption=(
            "orange = sections implicated by the compatibility findings; "
            "see the Inventory rows and repair lines in the error text "
            "(figure text is ASCII by design: the render font has no CJK glyphs)"
        ),
        dedup_key=(operation, "loft_sections", tuple(sorted(implicated))),
        label_at=[(fact.centroid, fact.section_id) for fact in facts],
    )
    if rendered is not None:
        evidence.append(rendered)

    raise_harness_error(
        operation=operation,
        what_happened=(
            f"the {operation} kernel build did not complete; the section "
            "compatibility check found: " + "; ".join(findings)
        ),
        possible_causes=[
            "Two adjacent sections sit at the same location (no generation direction to skin across).",
            "Edge counts differ too much across stations for the kernel to establish point correspondence.",
            "A section is open, or the list order disagrees with the generation direction.",
        ],
        how_to_fix=[
            "Check every station against its Inventory row (edges / closure / centroid).",
        ],
        evidence=evidence,
        repair=repair,
        inventory=tuple(inventory),
        technical_details=(
            "kernel reported: loft build did not complete; "
            f"section count={len(facts)}"
        ),
    )


def render_failure_evidence(
    shapes: Sequence[Any],
    *,
    operation: str,
    view: str = "default",
    caption: str = "",
    dedup_key: Optional[tuple] = None,
    highlight_tags: Sequence[str] = (),
    tag_labels: Optional[Dict[str, str]] = None,
    highlight_edges: Sequence[Any] = (),
    callouts: bool = True,
) -> Optional[ErrorEvidence]:
    """Render one diagnostic image; never raises.

    Skips (returns None) when disabled or when this failure signature
    already rendered once in the process — agent retry loops must not
    re-pay the render. When a render is attempted but produces no image
    (worker failure, or it exceeds the ``SCA_DIAGNOSTIC_RENDER_BUDGET``
    budget, 15 seconds by default), the evidence channel carries a
    ``render-unavailable`` entry naming the reason: the error goes out
    immediately either way, and a vanished render is never silent.
    """

    if not diagnostics_enabled():
        return None
    try:
        if dedup_key is not None:
            if dedup_key in _RENDER_DEDUP:
                return None
            _RENDER_DEDUP.add(dedup_key)
        root = diagnostics_dir()
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = root / f"{operation}-{stamp}.png"
        from .features import _execute_screenshot_render, _prepare_screenshot_render

        # Prepare (validate + tessellate) on the calling thread: this is
        # where the heavy native imports happen, and a native crash must
        # never originate inside a daemon thread where it takes the whole
        # process down. The thread below only orchestrates the
        # crash-isolated worker subprocess.
        prepared = _prepare_screenshot_render(
            shapes,
            str(path),
            views=_DIAGNOSTIC_VIEWS,
            supersample=1,  # highlight lines are fixed-width; SSAA is not worth the budget
            edge_width_scale=0.0035,  # heavier model ink so panels read at grid size
            highlight_edge_width=8.0,  # highlights outweigh the ink, always
            highlight_tags=tuple(highlight_tags),
            tag_labels=dict(tag_labels or {}),
            highlight_edges=tuple(highlight_edges),
            show_legend=bool(highlight_tags or highlight_edges),
            show_callouts=bool(highlight_tags) and callouts,
            worker_isolated=True,  # a daemon thread must never run in-process GL
        )
        budget = float(os.environ.get("SCA_DIAGNOSTIC_RENDER_BUDGET", _RENDER_BUDGET_SECONDS))
        result: dict = {}

        def _render() -> None:
            try:
                result["path"] = _execute_screenshot_render(prepared)
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=_render, daemon=True)
        worker.start()
        worker.join(budget)
        if "path" in result:
            return ErrorEvidence(
                kind="render",
                path=result["path"],
                view=view,
                caption=caption,
            )
        if "error" in result:
            reason = result["error"]
        elif worker.is_alive():
            reason = f"exceeded the {budget:g}s diagnostic render budget"
        else:
            reason = "the render worker produced no image"
        return ErrorEvidence(
            kind="render-unavailable",
            path="",
            view=view,
            caption=f"diagnostic render unavailable: {reason}",
        )
    except Exception as exc:
        return ErrorEvidence(
            kind="render-unavailable",
            path="",
            view=view,
            caption=f"diagnostic render unavailable: {type(exc).__name__}: {exc}",
        )


@dataclass(frozen=True)
class ClosestApproach:
    """Exact minimum distance between two shapes with the supporting points."""

    gap: float
    point_a: Tuple[float, float, float]
    point_b: Tuple[float, float, float]


@dataclass(frozen=True)
class WireGapDiagnosis:
    """Measured facts about why a wire is not closed (profile-gap probe).

    ``gap_distance``/``point_a``/``point_b`` describe the smallest dangling
    end-to-end gap; ``gap_edge_a``/``gap_edge_b`` are the edges owning those
    ends (evidence-render highlight targets).  ``chain_count`` > 1 means the
    wire is not even connected — a different repair than a missing segment.
    """

    gap_distance: float
    point_a: Tuple[float, float, float]
    point_b: Tuple[float, float, float]
    gap_edge_a: Any
    gap_edge_b: Any
    edge_count: int
    chain_count: int
    dangling_count: int


def diagnose_open_wire(wire: Any) -> Optional[WireGapDiagnosis]:
    """Locate and measure the gap of an open wire.

    Chains edges by endpoint proximity (coordinate tolerance scaled to the
    wire's extent), collects the dangling ends, and reports the closest
    dangling pair as the gap to close.  Returns None when endpoint probing
    fails for too many edges — the caller then degrades to an honest
    closedness-only message.
    """

    try:
        edges = list(wire._iter_edges())
        if not edges:
            return None
        endpoints: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = []
        for edge in edges:
            ends = _edge_endpoints(edge)
            if ends is None:
                return None
            endpoints.append(ends)

        # Endpoint-matching tolerance: kernel precision scaled to the wire
        # extent, with a floor so degenerate (single tiny edge) wires still
        # chain.
        coordinates = [
            value
            for ends in endpoints
            for point in ends
            for value in point
        ]
        scale = max(max(coordinates) - min(coordinates), 1e-9)
        tolerance = max(scale * 1e-6, 1e-9)

        def _close(point_a, point_b) -> bool:
            return math.dist(point_a, point_b) <= tolerance

        # Union-find over edges: two edges join when an endpoint pair of
        # one matches an endpoint pair of the other.
        parent = list(range(len(edges)))

        def _find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        matched = [[False, False] for _ in endpoints]
        for index_a in range(len(edges)):
            for end_a in (0, 1):
                for index_b in range(index_a + 1, len(edges)):
                    for end_b in (0, 1):
                        if (
                            not matched[index_a][end_a]
                            and not matched[index_b][end_b]
                            and _close(endpoints[index_a][end_a], endpoints[index_b][end_b])
                        ):
                            matched[index_a][end_a] = True
                            matched[index_b][end_b] = True
                            root_a, root_b = _find(index_a), _find(index_b)
                            if root_a != root_b:
                                parent[root_a] = root_b
        chain_count = len({_find(index) for index in range(len(edges))})

        dangling = [
            (index, end, endpoints[index][end])
            for index in range(len(edges))
            for end in (0, 1)
            if not matched[index][end]
        ]
        if not dangling:
            # Every endpoint matched but the wire reports open: a
            # vertex-ordering artifact; nothing measurable to report.
            return None
        if len(dangling) < 2:
            return None
        best = None
        for position_a in range(len(dangling)):
            for position_b in range(position_a + 1, len(dangling)):
                index_a, end_a, point_a = dangling[position_a]
                index_b, end_b, point_b = dangling[position_b]
                distance = math.dist(point_a, point_b)
                if best is None or distance < best[0]:
                    best = (distance, index_a, index_b, point_a, point_b)
        if best is None:
            return None
        # Same-edge pairs are legitimate: a lone segment's own two ends are
        # the gap to close (a single open segment reports its full length).
        distance, index_a, index_b, point_a, point_b = best
        return WireGapDiagnosis(
            gap_distance=distance,
            point_a=point_a,
            point_b=point_b,
            gap_edge_a=edges[index_a],
            gap_edge_b=edges[index_b],
            edge_count=len(edges),
            chain_count=chain_count,
            dangling_count=len(dangling),
        )
    except Exception:
        return None


def raise_open_wire_failure(operation: str, wire: Any, *, purpose: str) -> None:
    """Raise the structured 'wire must be closed' failure with measured gap facts.

    ``purpose`` names what the closed wire was for ("extrude it into a solid"
    / "create a face"), keeping the repair sentence anchored to the
    caller's intent.  The gap probe is best-effort: without it the error
    still states the violation, just without numbers.
    """

    diagnosis = diagnose_open_wire(wire)
    measurements: List[ErrorMeasurement] = []
    repair: List[str] = []
    inventory: Tuple = ()
    evidence: List[ErrorEvidence] = []
    if diagnosis is not None:
        measurements = [
            ErrorMeasurement("gap", diagnosis.gap_distance, "mm"),
            ErrorMeasurement("gap end P1", diagnosis.point_a, "mm"),
            ErrorMeasurement("gap end P2", diagnosis.point_b, "mm"),
            ErrorMeasurement("edge count", diagnosis.edge_count),
        ]
        p1 = _vector_display(diagnosis.point_a)
        p2 = _vector_display(diagnosis.point_b)
        repair.append(
            f"the gap is {diagnosis.gap_distance:.4g} mm between {p1} and "
            f"{p2}: add a segment (or arc) across the two ends to close the "
            "profile, then retry"
        )
        if diagnosis.chain_count > 1:
            measurements.append(ErrorMeasurement("chain count", diagnosis.chain_count))
            repair.append(
                f"the wire splits into {diagnosis.chain_count} disconnected "
                "chains — check for missing connecting geometry first "
                "instead of only patching the shortest gap"
            )
        if diagnosis.dangling_count > 2:
            repair.append(
                f"there are {diagnosis.dangling_count} dangling endpoints "
                "(more than one opening): close each of them before you "
                f"{purpose}"
            )
        rendered = render_wire_plan_evidence(
            [(wire, "ink"), (diagnosis.gap_edge_a, "highlight"), (diagnosis.gap_edge_b, "highlight")],
            operation=operation,
            caption=(
                f"orange edges mark the gap ends: {diagnosis.gap_distance:.4g} mm "
                f"apart at {p1} <-> {p2}"
            ),
            dedup_key=(operation, "open_wire", round(diagnosis.gap_distance, 4)),
            point_marks=(
                (diagnosis.point_a, "P1", "highlight"),
                (diagnosis.point_b, "P2", "highlight"),
            ),
        )
        if rendered is not None:
            evidence.append(rendered)
    else:
        repair.append(
            "check that the wire's endpoints meet head-to-tail in order"
        )

    raise_harness_error(
        operation=operation,
        what_happened=(
            f"the given wire is not closed, so it cannot be used to {purpose}"
            + (
                f"; measured gap {diagnosis.gap_distance:.4g} mm"
                if diagnosis is not None else ""
            )
        ),
        possible_causes=[
            "The wire's endpoints do not meet head-to-tail, leaving a gap.",
            "The wire consists of several disconnected pieces.",
            "A sketch profile was promoted before it was closed.",
        ],
        how_to_fix=[
            "Locate the gap ends from the P1/P2 coordinates in Measurements and bridge them.",
        ],
        measurements=measurements,
        evidence=evidence,
        repair=repair,
        inventory=inventory,
    )


def closest_approach(shape_a: Any, shape_b: Any) -> Optional[ClosestApproach]:
    try:
        tool = BRepExtrema_DistShapeShape(shape_a, shape_b)
        tool.Perform()
        if not tool.IsDone() or tool.NbSolution() < 1:
            return None
        pa: gp_Pnt = tool.PointOnShape1(1)
        pb: gp_Pnt = tool.PointOnShape2(1)
        return ClosestApproach(
            gap=float(tool.Value()),
            point_a=(float(pa.X()), float(pa.Y()), float(pa.Z())),
            point_b=(float(pb.X()), float(pb.Y()), float(pb.Z())),
        )
    except Exception:
        return None


@dataclass
class BooleanDiagnosis:
    """Classified boolean failure with measurements, repair steps, and evidence."""

    failure_kind: str  # "disjoint" | "non_manifold_contact" | "unknown"
    what_happened: Optional[str] = None
    possible_causes: Optional[List[str]] = None
    measurements: List[ErrorMeasurement] = field(default_factory=list)
    repair: List[str] = field(default_factory=list)
    evidence_shapes: List[Any] = field(default_factory=list)
    evidence_caption: str = ""


@dataclass
class BlendDiagnosis:
    """Classified fillet/chamfer failure (radius/distance vs local face room)."""

    failure_kind: str  # "size_exceeds_face" | "blends_tangency_critical" | "unknown"
    what_happened: Optional[str] = None
    possible_causes: Optional[List[str]] = None
    measurements: List[ErrorMeasurement] = field(default_factory=list)
    repair: List[str] = field(default_factory=list)
    evidence_shapes: List[Any] = field(default_factory=list)
    evidence_edges: List[Any] = field(default_factory=list)
    evidence_caption: str = ""


_MAX_RERUN_EDGES = 64  # per-edge diagnostic rerun cap (approved budget)


def _edge_face_adjacency(solid: Any) -> dict:
    """Map each TopoDS_Edge (hashable via __hash__) to its adjacent TopoDS_Face list."""

    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    mapping = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(solid.wrapped, TopAbs_EDGE, TopAbs_FACE, mapping)
    adjacency: dict = {}
    for index in range(1, mapping.Extent() + 1):
        edge = mapping.FindKey(index)
        faces = [face for face in mapping.FindFromIndex(index)]
        adjacency[edge.__hash__()] = (edge, faces)
    return adjacency


def _edge_endpoints(edge: Any) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    """Both endpoint coordinates of an edge; None for open/degenerate results."""

    try:
        from ..kernel.ocp_topology import vertex_point
        from OCP.TopAbs import TopAbs_VERTEX
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS

        points = []
        # SDK wrappers are not TopoDS_Shape subclasses; unwrap for OCP tools.
        raw_edge = edge.wrapped if hasattr(edge, "wrapped") else edge
        explorer = TopExp_Explorer(raw_edge, TopAbs_VERTEX)
        while explorer.More() and len(points) < 2:
            # Explorer yields TopoDS_Shape; vertex_point needs the typed cast.
            points.append(vertex_point(TopoDS.Vertex_s(explorer.Current())))
            explorer.Next()
        if len(points) != 2:
            return None
        return points[0], points[1]
    except Exception:
        return None


def _face_extent_from_edge(face: Any, edge: Any) -> Optional[float]:
    """Distance from ``edge`` to the nearest non-adjacent boundary edge of ``face``.

    This is the room a fillet radius (or chamfer leg) has on that face: for a
    rectangular face it is the distance to the opposite boundary edge.
    """

    try:
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_VERTEX
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS

        edge_vertices = set()
        vertex_explorer = TopExp_Explorer(edge, TopAbs_VERTEX)
        while vertex_explorer.More():
            edge_vertices.add(vertex_explorer.Current().__hash__())
            vertex_explorer.Next()

        best: Optional[float] = None
        boundary = TopExp_Explorer(face, TopAbs_EDGE)
        while boundary.More():
            other = TopoDS.Edge_s(boundary.Current())
            boundary.Next()
            if other.IsSame(edge):
                continue
            other_vertices = set()
            ve = TopExp_Explorer(other, TopAbs_VERTEX)
            while ve.More():
                other_vertices.add(ve.Current().__hash__())
                ve.Next()
            if edge_vertices & other_vertices:
                continue  # connected to the culprit edge: not an obstacle
            gap = closest_approach(edge, other)
            if gap is not None and (best is None or gap.gap < best):
                best = gap.gap
        return best
    except Exception:
        return None


def _solid_copy(shape: Any) -> Optional[Any]:
    """Fresh SDK wrapper around the same topology, for tag-free highlighting.

    Tags applied to the copy's faces never touch the user's original object
    (verified: wrapper-local bindings, zero pollution of the source shape).
    """

    try:
        from ..core import Solid

        if shape.__class__.__name__ != "Solid":
            return None
        return Solid(shape.wrapped)
    except Exception:
        return None


def _blend_size_label(operation_kind: str) -> Tuple[str, str]:
    if operation_kind == "chamfer":
        return "distance", "leg"
    return "radius", "fillet"


def _classify_blend_room(
    *,
    solid: Any,
    edges: Sequence[Any],
    size_value: float,
    operation_kind: str,
    adjacency: dict,
) -> Optional[BlendDiagnosis]:
    """Compare blend size against the room on the faces adjacent to each edge."""

    try:
        size_name, blend_name = _blend_size_label(operation_kind)
        for edge in edges:
            entry = adjacency.get(edge.wrapped.__hash__())
            if entry is None:
                continue
            _, faces = entry
            for face in faces:
                extent = _face_extent_from_edge(face, edge.wrapped)
                # Boundary counts as failure: r == room degenerates the
                # remaining face strip to zero width.
                if extent is None or extent <= 0 or size_value < extent:
                    continue
                endpoints = _edge_endpoints(edge.wrapped)
                measurements = [
                    ErrorMeasurement(size_name, size_value, "mm"),
                    ErrorMeasurement("available_face_room", extent, "mm"),
                ]
                if endpoints is not None:
                    measurements.append(ErrorMeasurement("edge_start", endpoints[0], "mm"))
                    measurements.append(ErrorMeasurement("edge_end", endpoints[1], "mm"))
                return (
                    BlendDiagnosis(
                        failure_kind="size_exceeds_face",
                        what_happened=(
                            f"{size_name} {size_value:.4g} mm meets or exceeds the "
                            f"{extent:.4g} mm of face room between the failing edge and "
                            f"the opposite boundary of an adjacent face"
                        ),
                        possible_causes=[
                            f"The {blend_name} {size_name} is larger than the adjacent face can carry.",
                            "The selected edge runs along a narrow face.",
                        ],
                        measurements=measurements,
                        repair=[
                            (
                                f"Reduce the {size_name} to below {extent:.4g} mm "
                                f"(e.g. {extent * 0.95:.4g}) and retry."
                            ),
                            "Or select a different edge with more room on its adjacent faces.",
                        ],
                        evidence_shapes=[solid],
            evidence_edges=[edge.wrapped],
                        evidence_caption=(
                            "orange line marks the failing edge; see measurements for its endpoints "
                            "and the available face room"
                        ),
                    )
                )
        return None
    except Exception:
        return None


def diagnose_blend_failure(
    solid: Any,
    edges: Sequence[Any],
    *,
    size_value: float,
    operation_kind: str,  # "fillet" | "chamfer"
    retry_single: Optional[Any] = None,
) -> Optional[BlendDiagnosis]:
    """Classify a fillet/chamfer failure; never raises.

    Probe order (cheapest explanation wins):

    1. Tangent adjacency — the two faces meeting at a selected edge are
       already tangent (dihedral ~180°), so the blend surface degenerates to
       zero width regardless of size.
    2. Room — blend size exceeds the distance from the edge to the opposite
       boundary of an adjacent face.
    3. Interaction — per-edge diagnostic rerun (``retry_single``, capped at
       64 edges) isolates edges that fail alone; when every edge passes
       alone but the joint blend fails, opposite blends on a shared face
       meeting tangentially (2×size >= face room) is the explanation.
    """

    try:
        if solid is None or not edges:
            return None
        adjacency = _edge_face_adjacency(solid)

        tiny = _classify_tiny_edges(
            solid=solid, edges=edges, operation_kind=operation_kind
        )
        if tiny is not None:
            return tiny

        tangent = _classify_tangent_adjacency(
            solid=solid, edges=edges, adjacency=adjacency, operation_kind=operation_kind
        )
        if tangent is not None:
            return tangent

        room = _classify_blend_room(
            solid=solid,
            edges=edges,
            size_value=size_value,
            operation_kind=operation_kind,
            adjacency=adjacency,
        )
        if room is not None:
            return room

        partial_chain = _classify_partial_smooth_chain(
            solid=solid, edges=edges, operation_kind=operation_kind, adjacency=adjacency
        )
        if partial_chain is not None:
            return partial_chain

        if retry_single is not None and 1 < len(edges) <= _MAX_RERUN_EDGES:
            failing_alone = [edge for edge in edges if not retry_single(edge)]
            if failing_alone:
                # An edge that fails alone should have been caught by the
                # probes above; an unexplained single-edge failure stays
                # silent rather than guessed at.
                return None

        for edge in edges:
            entry = adjacency.get(edge.wrapped.__hash__())
            if entry is None:
                continue
            for face in entry[1]:
                extent = _face_extent_from_edge(face, edge.wrapped)
                if extent is None or extent <= 0:
                    continue
                if 2 * size_value >= extent:
                    return _tangency_critical_diagnosis(
                        solid=solid,
                        edge=edge,
                        size_value=size_value,
                        extent=extent,
                        operation_kind=operation_kind,
                    )

        # Generic corner-blend conflict goes last: three convex edges at a
        # box corner are routine and must not shadow specific explanations.
        vertex_conflict = _classify_vertex_conflict(
            solid=solid, edges=edges, operation_kind=operation_kind, adjacency=adjacency
        )
        if vertex_conflict is not None:
            return vertex_conflict
        return None
    except Exception:
        return None


class BlendVolumeViolation(ValueError):
    """A blend op returned geometrically impossible output (mechanism E).

    Carries the measured volumes in the message so the blend failure wrapper
    can promote it to ``what_happened`` (mechanism-A style) instead of
    demoting the facts into technical details.
    """


def _edge_is_concave_side_probe(
    solid: Any, face_a: Any, face_b: Any, edge: Any
) -> Optional[bool]:
    """Edge convexity via side probes; ``None`` when undeterminable.

    The outward-normal bisector probe (``_edge_is_concave``) is blind
    between a 90° convex edge and its 270° concave supplement — the two
    configurations share identical face normals.  This probe offsets the
    edge midpoint along ``n_a - n_b`` (and ``n_b - n_a``): that direction
    lies in the material half-space only for the concave configuration
    (90° air wedge), and in air for the convex one (270° air wedge).

    Needed by the mechanism-E volume check: filleting a *concave* edge
    legitimately adds material (corner fill), so monotonicity only holds
    for all-convex selections.
    """

    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.BRepLProp import BRepLProp_SLProps
        from OCP.ShapeAnalysis import ShapeAnalysis_Surface
        from OCP.TopAbs import TopAbs_IN, TopAbs_REVERSED
        from OCP.TopoDS import TopoDS
        from OCP.gp import gp_Pnt

        topo_edge = TopoDS.Edge_s(edge.wrapped if hasattr(edge, "wrapped") else edge)
        curve = BRepAdaptor_Curve(topo_edge)
        mid3d = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2.0)
        normals = []
        for shape in (face_a, face_b):
            face = TopoDS.Face_s(shape.wrapped if hasattr(shape, "wrapped") else shape)
            projector = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face))
            uv = projector.ValueOfUV(mid3d, 1e-6)
            props = BRepLProp_SLProps(
                BRepAdaptor_Surface(face), uv.X(), uv.Y(), 1, 1e-6
            )
            if not props.IsNormalDefined():
                return None
            normal = props.Normal()
            components = [normal.X(), normal.Y(), normal.Z()]
            if face.Orientation() == TopAbs_REVERSED:
                components = [-c for c in components]
            normals.append(components)
        classifier = BRepClass3d_SolidClassifier(TopoDS.Solid_s(solid.wrapped))
        step = 1e-3
        for first, second in ((0, 1), (1, 0)):
            delta = [
                normals[first][axis] - normals[second][axis]
                for axis in range(3)
            ]
            length = sum(c * c for c in delta) ** 0.5
            if length < 1e-9:
                # Tangent faces (equal normals): undeterminable here; the
                # tangent-adjacency classifier handles that regime.
                continue
            probe = gp_Pnt(
                mid3d.X() + step * delta[0] / length,
                mid3d.Y() + step * delta[1] / length,
                mid3d.Z() + step * delta[2] / length,
            )
            classifier.Perform(probe, 1e-7)
            if classifier.State() == TopAbs_IN:
                return True
        return False
    except Exception:
        return None


def _all_edges_convex(solid: Any, edges: Sequence[Any]) -> Optional[bool]:
    """True when every edge reads convex; None when any edge is undeterminable.

    Mechanism E's monotonic-volume guard may only fire when the selection is
    provably all-convex: a single concave edge legitimizes a volume increase
    (corner fill), and an undeterminable edge means the check cannot prove
    impossibility — a garbage detector must not guess.
    """

    for edge in edges:
        faces = edge.get_incident_faces()
        if len(faces) < 2:
            return None
        concave = _edge_is_concave_side_probe(solid, faces[0], faces[1], edge)
        if concave is not False:
            return None
    return True


def assert_blend_volume_monotonic(
    source: Any,
    result: Any,
    *,
    operation: str,
    operation_kind: str,
    size_value: Optional[float],
    edges: Sequence[Any],
) -> None:
    """Mechanism E exit check: an all-convex blend may only remove material.

    Observed kernel behavior (and the reason this check exists): filleting
    every edge of a 10 mm cube with r=6 *succeeds* and returns a solid whose
    volume (1036.35) exceeds the input (1000) — geometrically impossible
    output that the kernel hands back without a word.  Fillet and chamfer
    outputs on convex edges are subsets of the input solid, so a volume
    increase beyond measurement noise means the kernel silently produced
    garbage; we name it instead of returning it.

    The increase check only fires for provably all-convex selections:
    blending a *concave* edge legitimately adds material (the corner fill —
    e.g. a bolt's underhead fillet gains exactly the quarter-circle deficit
    times its circumference), and undeterminable edges mean the check
    cannot prove impossibility.  A non-positive result volume is garbage
    regardless of convexity and always fires.

    The check runs on the success path, so it must stay cheap: two GProp
    volume evaluations plus one side-probe per selected edge.  Raised as a
    ``BlendVolumeViolation`` so the caller's ``_wrap_blend_failure`` handler
    promotes the measured facts and layers the standard blend diagnosis
    (probes, evidence render) on top.
    """

    try:
        # ``volume`` measures raw OCP shapes; SDK wrappers carry ``.wrapped``.
        source_shape = getattr(source, "wrapped", source)
        result_shape = getattr(result, "wrapped", result)
        source_volume = float(volume(source_shape))
        result_volume = float(volume(result_shape))
    except Exception:
        # Volume evaluation is best-effort: never block a legitimate result
        # because a measurement could not be taken.
        return
    if result_volume <= 0.0:
        raise BlendVolumeViolation(
            f"{operation_kind} result volume is {result_volume:.6g}: the "
            f"kernel returned an empty/degenerate solid "
            f"(size={size_value!r}, selected_edges={len(edges)})"
        )
    tolerance = max(1e-9, abs(source_volume) * 1e-6)
    if result_volume > source_volume + tolerance and _all_edges_convex(source, edges):
        raise BlendVolumeViolation(
            f"{operation_kind} result volume {result_volume:.6g} exceeds the "
            f"input volume {source_volume:.6g}: the blend can only remove "
            f"material, so the kernel silently returned degenerate geometry "
            f"(size={size_value!r}, selected_edges={len(edges)})"
        )


def _classify_tangent_adjacency(
    *,
    solid: Any,
    edges: Sequence[Any],
    adjacency: dict,
    operation_kind: str,
) -> Optional[BlendDiagnosis]:
    """Detect a selected edge whose adjacent faces are already tangent."""

    for edge in edges:
        entry = adjacency.get(edge.wrapped.__hash__())
        if entry is None:
            continue
        _topo_edge, faces = entry
        if len(faces) < 2:
            continue
        dihedral = _dihedral_angle_along_edge(faces[0], faces[1], edge.wrapped)
        if dihedral is None:
            continue
        # Interior dihedral near 180° = tangent (smooth) junction: the blend
        # wedge has zero opening angle and degenerates for any size.
        if abs(dihedral - 180.0) <= 1.0:
            endpoints = _edge_endpoints(edge.wrapped)
            measurements = [ErrorMeasurement("dihedral_angle", dihedral, "deg")]
            if endpoints is not None:
                measurements.append(ErrorMeasurement("edge_start", endpoints[0], "mm"))
                measurements.append(ErrorMeasurement("edge_end", endpoints[1], "mm"))
            size_name, blend_name = _blend_size_label(operation_kind)
            return BlendDiagnosis(
                failure_kind="tangent_adjacent_faces",
                what_happened=(
                    f"the faces meeting at a selected edge are already tangent "
                    f"(interior angle {dihedral:.2f}°), so the {blend_name} surface "
                    f"degenerates to zero width for any {size_name}"
                ),
                possible_causes=[
                    "The profile or upstream blend produced a smooth (G1) junction; "
                    "there is no corner for the blend to fill.",
                ],
                measurements=measurements,
                repair=[
                    "Remove that junction edge from the selection: there is no corner to blend.",
                    "If a visual transition is required there, it already exists — "
                    "the faces are tangent by construction.",
                ],
                evidence_shapes=[solid],
            evidence_edges=[edge.wrapped],
                evidence_caption="orange line marks the tangent junction edge; see measurements",
            )
    return None


def _classify_tiny_edges(
    *, solid: Any, edges: Sequence[Any], operation_kind: str
) -> Optional[BlendDiagnosis]:
    """Detect sliver edges in the selection — post-boolean topology debris."""

    try:
        lengths: List[Tuple[Any, float]] = []
        for edge in edges:
            try:
                lengths.append((edge, float(edge.get_length())))
            except Exception:
                return None
        if len(lengths) < 2:
            return None
        ordered = sorted(length for _, length in lengths)
        median = ordered[len(ordered) // 2]
        threshold = max(1e-3, median * 1e-3)  # sub-micron slivers vs selection scale
        tiny = [(edge, length) for edge, length in lengths if length <= threshold]
        if not tiny or len(tiny) == len(lengths):
            return None
        size_name, blend_name = _blend_size_label(operation_kind)
        shortest_edge, shortest_length = min(tiny, key=lambda item: item[1])
        return BlendDiagnosis(
            failure_kind="sliver_edges_in_selection",
            what_happened=(
                f"{len(tiny)} of {len(edges)} selected edges are slivers "
                f"(shortest {shortest_length:.2e} mm vs selection median "
                f"{median:.4g} mm); the kernel cannot blend degenerate edges"
            ),
            possible_causes=[
                "A boolean left splitter debris in the topology and the selection swept it in.",
                "The selector matched by a property that sliver edges also satisfy.",
            ],
            measurements=[
                ErrorMeasurement("shortest_selected_edge", shortest_length, "mm"),
                ErrorMeasurement("selection_median_edge", median, "mm"),
            ],
            repair=[
                "Drop the sliver edges from the selection (filter by feature intent, "
                "not by a blanket selector).",
                f"Re-select with a QL predicate that excludes sub-micron edges before "
                f"the {blend_name}.",
            ],
            evidence_shapes=[solid],
            evidence_edges=[shortest_edge.wrapped],
            evidence_caption="orange line marks the shortest sliver edge; see measurements",
        )
    except Exception:
        return None


def _edges_tangent_at_shared_vertex(edge_a: Any, edge_b: Any) -> bool:
    """True when two edges meet at a vertex with aligned tangents.

    Tangent continuity at the shared vertex is the structural signature of
    one smooth curve (typically a boolean seam) that the kernel split into
    several edges.
    """

    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.TopoDS import TopoDS
        import math as _math

        adaptor_a = BRepAdaptor_Curve(TopoDS.Edge_s(edge_a))
        adaptor_b = BRepAdaptor_Curve(TopoDS.Edge_s(edge_b))

        def endpoints(adaptor):
            return (
                adaptor.Value(adaptor.FirstParameter()),
                adaptor.Value(adaptor.LastParameter()),
            )

        # Match the shared vertex by position: pair each end of edge_a with
        # the nearest end of edge_b and keep the closest pair.
        a_first, a_last = endpoints(adaptor_a)
        b_first, b_last = endpoints(adaptor_b)
        point_a, point_b, at_a_start, at_b_start = min(
            (
                (a_first, b_last, True, False),
                (a_last, b_first, False, True),
                (a_first, b_first, True, True),
                (a_last, b_last, False, False),
            ),
            key=lambda pair: pair[0].Distance(pair[1]),
        )
        if point_a.Distance(point_b) > 1e-6:
            return False  # the edges do not actually share a vertex

        def tangent_direction(adaptor, at_start):
            """Unit tangent at one end, sampled inward by a small parameter step."""

            parameter = (
                adaptor.FirstParameter() if at_start else adaptor.LastParameter()
            )
            span = adaptor.LastParameter() - adaptor.FirstParameter()
            step = max(1e-6, span * 1e-4)
            inward = (
                min(parameter + step, adaptor.LastParameter())
                if at_start
                else max(parameter - step, adaptor.FirstParameter())
            )
            if inward == parameter:
                return None
            p1 = adaptor.Value(parameter)
            p2 = adaptor.Value(inward)
            vector = (p2.X() - p1.X(), p2.Y() - p1.Y(), p2.Z() - p1.Z())
            norm = _math.sqrt(sum(c * c for c in vector))
            if norm < 1e-12:
                return None
            return tuple(c / norm for c in vector)

        tangent_a = tangent_direction(adaptor_a, at_a_start)
        tangent_b = tangent_direction(adaptor_b, at_b_start)
        if tangent_a is None or tangent_b is None:
            return False
        dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(tangent_a, tangent_b))))
        angle = _math.degrees(_math.acos(dot))
        # Aligned (same direction) or anti-aligned (chain reversed) both mean
        # one smooth curve through the shared vertex.
        return angle <= 1.0 or angle >= 179.0
    except Exception:
        return False


def _classify_partial_smooth_chain(
    *,
    solid: Any,
    edges: Sequence[Any],
    operation_kind: str,
    adjacency: dict,
) -> Optional[BlendDiagnosis]:
    """A smooth edge chain on a periodic surface is partially selected.

    Boolean seams on cylinders/tori split into several edges; blending one
    segment of the chain fails — the verified repair is selecting the whole
    chain.
    """

    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Sphere, GeomAbs_Torus
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS

        periodic = (GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Sphere)
        selected_hashes = {edge.wrapped.__hash__() for edge in edges}
        for edge in edges:
            entry = adjacency.get(edge.wrapped.__hash__())
            if entry is None:
                continue
            _topo_edge, faces = entry
            for face in faces:
                adaptor = BRepAdaptor_Surface(face)
                if adaptor.GetType() not in periodic:
                    continue
                boundary = TopExp_Explorer(face, TopAbs_EDGE)
                while boundary.More():
                    other = TopoDS.Edge_s(boundary.Current())
                    boundary.Next()
                    if other.__hash__() in selected_hashes or other.IsSame(_topo_edge):
                        continue
                    if not _edges_tangent_at_shared_vertex(_topo_edge, other):
                        continue
                    endpoints = _edge_endpoints(edge.wrapped)
                    measurements: List[ErrorMeasurement] = []
                    if endpoints is not None:
                        measurements.append(ErrorMeasurement("edge_start", endpoints[0], "mm"))
                        measurements.append(ErrorMeasurement("edge_end", endpoints[1], "mm"))
                        return BlendDiagnosis(
                        failure_kind="partial_smooth_chain_on_periodic_face",
                        what_happened=(
                            "the selected edge is one segment of a smooth (tangent) "
                            "chain on a periodic face (cylinder/torus/sphere); blending "
                            "a partial chain fails because the blend cannot end "
                            "mid-chain"
                        ),
                        possible_causes=[
                            "A boolean seam split one smooth intersection curve into "
                            "several edges and the selection caught only part of it.",
                        ],
                        measurements=measurements,
                        repair=[
                            "Select the entire smooth chain: every tangent-continuous "
                            "segment of that curve, then blend them together in one call.",
                            "Enumerate with QL and extend the selection across the shared "
                            "vertices before retrying.",
                        ],
                        evidence_shapes=[solid],
            evidence_edges=[edge.wrapped],
                        evidence_caption="orange line marks the partially selected chain segment",
                    )
        return None
    except Exception:
        return None


def _classify_vertex_conflict(
    *,
    solid: Any,
    edges: Sequence[Any],
    operation_kind: str,
    adjacency: dict,
) -> Optional[BlendDiagnosis]:
    """Many selected edges (or mixed convexity) meeting at one vertex.

    Corner blending where several edges converge is the classic kernel
    failure; mixed convex/concave edges at a shared vertex cannot close a
    rolling-ball corner.
    """

    try:
        from OCP.TopAbs import TopAbs_VERTEX
        from OCP.TopExp import TopExp_Explorer

        by_vertex: dict = {}
        for edge in edges:
            explorer = TopExp_Explorer(edge.wrapped, TopAbs_VERTEX)
            while explorer.More():
                by_vertex.setdefault(explorer.Current().__hash__(), []).append(edge)
                explorer.Next()

        size_name, blend_name = _blend_size_label(operation_kind)
        for _vhash, incident in by_vertex.items():
            convexities: List[bool] = []
            for edge in incident:
                entry = adjacency.get(edge.wrapped.__hash__())
                if entry is None or len(entry[1]) < 2:
                    continue
                concave = _edge_is_concave(solid, entry[1][0], entry[1][1], edge.wrapped)
                if concave is not None:
                    convexities.append(not concave)
            mixed = bool(convexities) and (len(set(convexities)) > 1)
            # Three same-convexity edges at a corner (a plain box corner) are
            # routine; only crowded (>=4) or mixed-convexity corners explain
            # failures.
            if len(incident) < 4 and not mixed:
                continue
            counts = f"{len(incident)} selected edges meet at one vertex"
            if mixed:
                counts += " with mixed convex/concave edges"
            measurements: List[ErrorMeasurement] = [
                ErrorMeasurement("edges_at_vertex", float(len(incident)), ""),
            ]
            critical_edges = [edge.wrapped for edge in incident[:3]]
            return BlendDiagnosis(
                failure_kind="vertex_blend_conflict",
                what_happened=(
                    f"{counts}; blending such corners is where the rolling-ball "
                    f"{blend_name} fails to close"
                ),
                possible_causes=[
                    "Fillet/chamfer corner vertex with many converging blended edges.",
                ] + (
                    ["Convex and concave edges meet at the same vertex."]
                    if mixed
                    else []
                ),
                measurements=measurements,
                repair=[
                    "Blend the converging edges in separate passes: hardest edges "
                    "first, then the remainder with a smaller size.",
                    "Or drop the corner edge from this pass and blend it alone "
                    "afterwards.",
                ],
                evidence_shapes=[solid],
                evidence_edges=critical_edges,
                evidence_caption="orange lines mark the edges converging at the corner vertex",
            )
        return None
    except Exception:
        return None


def _tangency_critical_diagnosis(
    *,
    solid: Any,
    edge: Any,
    size_value: float,
    extent: float,
    operation_kind: str,
) -> BlendDiagnosis:
    size_name, blend_name = _blend_size_label(operation_kind)
    endpoints = _edge_endpoints(edge.wrapped)
    measurements = [
        ErrorMeasurement(size_name, size_value, "mm"),
        ErrorMeasurement("combined_blend_width", 2 * size_value, "mm"),
        ErrorMeasurement("available_face_room", extent, "mm"),
    ]
    if endpoints is not None:
        measurements.append(ErrorMeasurement("edge_start", endpoints[0], "mm"))
        measurements.append(ErrorMeasurement("edge_end", endpoints[1], "mm"))
    return BlendDiagnosis(
        failure_kind="blends_tangency_critical",
        what_happened=(
            f"adjacent {blend_name} surfaces meet tangentially: "
            f"2×{size_name} = {2 * size_value:.4g} mm equals or exceeds the "
            f"{extent:.4g} mm face room between opposite edges, leaving a "
            f"zero-width face strip (degenerate)"
        ),
        possible_causes=[
            f"Blending many edges with the same {size_name} consumes the shared faces entirely.",
            "The critical size equals half the narrowest adjacent face.",
        ],
        measurements=measurements,
        repair=[
            (
                f"Reduce the {size_name} below {extent / 2:.4g} mm "
                "(half the narrowest shared face) so adjacent blend "
                "surfaces leave material between them."
            ),
            "Or blend the edges in two passes with different sizes.",
        ],
        evidence_shapes=[solid],
            evidence_edges=[edge.wrapped],
        evidence_caption="orange line marks the critical edge; see measurements",
    )


def _dihedral_angle_along_edge(
    face_a: Any, face_b: Any, edge: Any
) -> Optional[float]:
    """Interior dihedral angle (deg) between two faces along their shared edge.

    180° = tangent junction; < 180° = convex edge. Concave edges read as
    their supplement here (270° reports as 90°); tangency — the case this
    probe exists for — is unaffected.
    """

    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.BRepLProp import BRepLProp_SLProps
        from OCP.ShapeAnalysis import ShapeAnalysis_Surface
        from OCP.TopAbs import TopAbs_REVERSED
        from OCP.TopoDS import TopoDS
        import math as _math

        topo_edge = TopoDS.Edge_s(edge)
        curve = BRepAdaptor_Curve(topo_edge)
        mid3d = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2.0)
        normals: List[Tuple[float, float, float]] = []
        for shape in (face_a, face_b):
            face = TopoDS.Face_s(shape)
            projector = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face))
            uv = projector.ValueOfUV(mid3d, 1e-6)
            props = BRepLProp_SLProps(
                BRepAdaptor_Surface(face), uv.X(), uv.Y(), 1, 1e-6
            )
            if not props.IsNormalDefined():
                return None
            normal = props.Normal()
            components = (normal.X(), normal.Y(), normal.Z())
            if face.Orientation() == TopAbs_REVERSED:
                components = tuple(-c for c in components)
            normals.append(components)
        dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(*normals))))
        normals_angle = _math.degrees(_math.acos(dot))
        return 180.0 - normals_angle
    except Exception:
        return None


def _edge_is_concave(solid: Any, face_a: Any, face_b: Any, edge: Any) -> Optional[bool]:
    """Convexity of an edge: offset the midpoint along the outward-normal
    bisector; inside the solid ⇒ concave, outside ⇒ convex."""

    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.BRepLProp import BRepLProp_SLProps
        from OCP.ShapeAnalysis import ShapeAnalysis_Surface
        from OCP.TopAbs import TopAbs_IN, TopAbs_REVERSED
        from OCP.TopoDS import TopoDS
        from OCP.gp import gp_Pnt

        topo_edge = TopoDS.Edge_s(edge)
        curve = BRepAdaptor_Curve(topo_edge)
        mid3d = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2.0)
        bisector = [0.0, 0.0, 0.0]
        for shape in (face_a, face_b):
            face = TopoDS.Face_s(shape)
            projector = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face))
            uv = projector.ValueOfUV(mid3d, 1e-6)
            props = BRepLProp_SLProps(
                BRepAdaptor_Surface(face), uv.X(), uv.Y(), 1, 1e-6
            )
            if not props.IsNormalDefined():
                return None
            normal = props.Normal()
            components = [normal.X(), normal.Y(), normal.Z()]
            if face.Orientation() == TopAbs_REVERSED:
                components = [-c for c in components]
            bisector = [b + c for b, c in zip(bisector, components)]
        length = sum(c * c for c in bisector) ** 0.5
        if length < 1e-9:
            return None
        step = 1e-3
        probe = gp_Pnt(
            mid3d.X() + step * bisector[0] / length,
            mid3d.Y() + step * bisector[1] / length,
            mid3d.Z() + step * bisector[2] / length,
        )
        classifier = BRepClass3d_SolidClassifier(TopoDS.Solid_s(solid.wrapped))
        classifier.Perform(probe, 1e-7)
        return classifier.State() == TopAbs_IN
    except Exception:
        return None


def _vector_display(vector: Sequence[float]) -> str:
    return "(" + ", ".join(f"{float(v):.4g}" for v in vector) + ")"


def _overlap_volume(shape_a: Any, shape_b: Any) -> float:
    """Positive-volume intersection of two shapes; 0.0 when disjoint or touching only."""

    try:
        common = common_shapes([shape_a, shape_b])
        total = 0.0
        explorer = TopExp_Explorer(common, TopAbs_SOLID)
        while explorer.More():
            total += volume(TopoDS.Solid_s(explorer.Current()))
            explorer.Next()
        return total
    except Exception:
        return 0.0


def _disjoint_diagnosis(
    index_a: int,
    index_b: int,
    solid_a: Any,
    solid_b: Any,
    approach: ClosestApproach,
    effective_tol: float,
    operation_kind: str = "union",
) -> BooleanDiagnosis:
    label_a = f"operand {index_a + 1}"
    label_b = f"operand {index_b + 1}"
    move_vector = tuple(pb - pa for pa, pb in zip(approach.point_a, approach.point_b))
    disjoint_causes = {
        "union": [
            "The operands are separated in space, so the union cannot produce exactly one solid.",
            "A placement/translation moved one operand away from the other.",
        ],
        "cut": [
            "The tool never reaches the base solid, so the cut removes nothing.",
            "A placement/translation moved the tool away from the base solid.",
        ],
        "intersect": [
            "The operands are separated in space, so the intersection is empty.",
            "A placement/translation moved one operand away from the other.",
        ],
    }
    disjoint_repair = {
        "union": [
            (
                f"Move {label_b} by {_vector_display(move_vector)} "
                f"(≥ {approach.gap:.4g} mm) so the operands touch, "
                "or extend one operand across the gap."
            ),
            "If the pieces are meant to stay separate, build an assembly "
            "(make_assembly_rassembly) instead of a single-solid union.",
        ],
        "cut": [
            (
                f"Move the tool {label_b} by {_vector_display(move_vector)} "
                f"(≥ {approach.gap:.4g} mm) so it reaches inside the base solid, "
                "or extend the tool across the gap."
            ),
            "Check the intended removal region: with this gap the cut is a no-op on the base solid.",
        ],
        "intersect": [
            (
                f"Move {label_b} by {_vector_display(move_vector)} "
                f"(≥ {approach.gap:.4g} mm) so the operands share a positive-volume overlap."
            ),
        ],
    }
    return BooleanDiagnosis(
        failure_kind="disjoint",
        what_happened=(
            f"separated solids: {label_a} and {label_b} never touch; "
            f"nearest detected gap is {approach.gap:.4g} mm "
            f"(tolerance {effective_tol:.4g})"
        ),
        possible_causes=disjoint_causes.get(operation_kind, disjoint_causes["union"]),
        measurements=[
            ErrorMeasurement("min_gap", approach.gap, "mm"),
            ErrorMeasurement("closest_point_a", approach.point_a, "mm"),
            ErrorMeasurement("closest_point_b", approach.point_b, "mm"),
            ErrorMeasurement("closure_vector_a_to_b", move_vector, "mm"),
        ],
        repair=disjoint_repair.get(operation_kind, disjoint_repair["union"]),
        evidence_shapes=[solid_a, solid_b],
        evidence_caption=(
            f"{label_a} and {label_b}; nearest gap {approach.gap:.4g} mm "
            "between the two closest points (see measurements)"
        ),
    )


def _contact_diagnosis(
    index_a: int,
    index_b: int,
    solid_a: Any,
    solid_b: Any,
    approach: ClosestApproach,
    effective_tol: float,
    operation_kind: str = "union",
) -> BooleanDiagnosis:
    label_a = f"operand {index_a + 1}"
    label_b = f"operand {index_b + 1}"
    move_vector = tuple(pb - pa for pa, pb in zip(approach.point_a, approach.point_b))
    contact_repair = {
        "cut": [
            (
                "The tool only grazes the base solid; translate the tool "
                f"along {_vector_display(move_vector)} by a working depth "
                "(e.g. 0.5 mm beyond touch) so it removes real volume."
            ),
        ],
        "intersect": [
            (
                "The operands only graze each other; translate one along "
                f"{_vector_display(move_vector)} by a working depth "
                "(e.g. 0.5 mm beyond touch) to create a positive-volume overlap."
            ),
        ],
    }
    default_contact_repair = [
        (
            "Give the contact a positive-volume overlap: translate one operand "
            f"along {_vector_display(move_vector)} by a working overlap "
            "(e.g. 0.5 mm beyond touch) and retry."
        ),
        "For intended face contact, make the shared face finite in area and "
        "coincident; no artificial overlap is required.",
    ]
    return BooleanDiagnosis(
        failure_kind="non_manifold_contact",
        what_happened=(
            f"operands meet only along an edge, vertex, or tangent "
            f"(measured gap {approach.gap:.4g} mm ≤ tol {effective_tol:.4g}), "
            "which is not one manifold solid"
        ),
        possible_causes=[
            "The operands touch without a finite-area face or positive-volume overlap.",
        ],
        measurements=[
            ErrorMeasurement("min_gap", approach.gap, "mm"),
            ErrorMeasurement("closest_point_a", approach.point_a, "mm"),
            ErrorMeasurement("closest_point_b", approach.point_b, "mm"),
        ],
        repair=contact_repair.get(operation_kind, default_contact_repair),
        evidence_shapes=[solid_a, solid_b],
        evidence_caption=f"{label_a} and {label_b} in edge/vertex/tangent-only contact",
    )


def diagnose_boolean_failure(
    operands: Optional[Sequence[Any]],
    *,
    effective_tol: Optional[float],
    operation_kind: str = "union",
) -> Optional[BooleanDiagnosis]:
    """Classify a boolean failure from its operands; never raises.

    Model: operands within ``tol`` of each other form one connected cluster
    (transitively). More than one cluster means the union is genuinely
    separated — report the nearest inter-cluster pair. A single cluster that
    still failed to fuse contains a touch-without-overlap pair — report it as
    non-manifold contact. Returns None when no pair explains the failure.
    """

    try:
        if not operands or len(operands) < 2:
            return None
        tol = float(effective_tol or 0.0)
        count = len(operands)
        total_pairs = count * (count - 1) // 2
        if total_pairs > _MAX_PAIR_PROBES:
            # Capped out: unprobed pairs might connect the clusters, so a
            # nearest-pair claim could misattribute. Report nothing.
            return None
        approaches: dict = {}
        for i in range(count):
            for j in range(i + 1, count):
                approach = closest_approach(operands[i].wrapped, operands[j].wrapped)
                if approach is not None:
                    approaches[(i, j)] = approach

        parent = list(range(count))

        def find(node: int) -> int:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for (i, j), approach in approaches.items():
            if approach.gap <= tol:
                root_i, root_j = find(i), find(j)
                if root_i != root_j:
                    parent[root_i] = root_j

        if len({find(i) for i in range(count)}) > 1:
            best_pair = None
            best_approach: Optional[ClosestApproach] = None
            for (i, j), approach in approaches.items():
                if find(i) != find(j) and (best_approach is None or approach.gap < best_approach.gap):
                    best_pair, best_approach = (i, j), approach
            if best_pair is None or best_approach is None:
                return None
            i, j = best_pair
            return _disjoint_diagnosis(
                i, j, operands[i], operands[j], best_approach, tol, operation_kind
            )

        for (i, j), approach in approaches.items():
            if approach.gap <= tol and _overlap_volume(
                operands[i].wrapped, operands[j].wrapped
            ) < 1e-12:
                return _contact_diagnosis(
                    i, j, operands[i], operands[j], approach, tol, operation_kind
                )
        return None
    except Exception:
        return None

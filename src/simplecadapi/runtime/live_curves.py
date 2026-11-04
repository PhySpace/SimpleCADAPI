"""The curves of a running notebook, for a viewer: every top-level wire and edge value, sampled by the SDK.

A part's preview draws its solids; a 3D path, a sweep rail or a sketch made into a wire is not a solid, so it would not
be seen.  :func:`curve_samples` gives each such value as polylines (one per edge, world mm), sampled with the SDK's own
``sample_curve_rcurvature`` along the curve's parameter, so what the viewer draws is the kernel's curve, not a guess.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from .._cpp import Edge, Wire, ql, sample_curve_rcurvature
from ._marimo import safe_get_context

_SAMPLES = 48
"""Points per edge: an arc or a spline reads smooth; a straight edge needs two, and gets them."""


def _edge_points(edge: Any) -> list[list[float]]:
    if edge._geom_type() == "LINE":
        start, end = edge.get_start_vertex().get_coordinates(), edge.get_end_vertex().get_coordinates()
        return [list(start), list(end)]
    samples = sample_curve_rcurvature(edge, _SAMPLES)
    return [list(point) for point in samples["points"]]


def curve_samples(values: Mapping[str, object]) -> list[dict[str, Any]]:
    """``{name, kind, edges: [[[x, y, z], ...], ...]}`` for each top-level wire or edge among *values* (private names
    left out); a value that cannot be sampled is left out rather than failing the preview."""
    out: list[dict[str, Any]] = []
    for name, value in values.items():
        if name.startswith("_") or not isinstance(value, (Wire, Edge)):
            continue
        try:
            edges = ql.edges().resolve(value) if isinstance(value, Wire) else [value]
            polylines = [_edge_points(edge) for edge in edges]
        except Exception:  # noqa: BLE001 - a curve the sampler refuses is not drawn
            continue
        if all(all(math.isfinite(c) for p in line for c in p) for line in polylines):
            out.append({"name": name, "kind": "wire" if isinstance(value, Wire) else "edge", "edges": polylines})
    return out


def live_curves() -> list[dict[str, Any]]:
    """:func:`curve_samples` of the running notebook's values; empty outside a kernel."""
    context = safe_get_context()
    if context is None:
        return []
    glbls = context.globals
    values = {name: glbls[name] for cell in context.graph.cells.values() for name in cell.defs if name in glbls}
    return curve_samples(values)


__all__ = ["curve_samples", "live_curves"]

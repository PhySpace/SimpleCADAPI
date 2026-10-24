"""Decide whether loft side faces are ruled between the two end caps."""

from __future__ import annotations

from typing import Any

import numpy as np
from OCP.BRep import BRep_Tool

_POLYNOMIAL_TYPES = {"BSPLINE", "BEZIER"}
_SAMPLES = (0.0, 0.25, 0.5, 0.75, 1.0)


def _cap_plane(fact: dict[str, Any] | None) -> tuple[np.ndarray, np.ndarray] | None:
    if not fact or fact["type"] != "PLANE" or fact["normal"] is None:
        return None
    return np.asarray(fact["centroid"], dtype=float), np.asarray(fact["normal"], dtype=float)


def _on_plane(point: np.ndarray, plane, tolerance: float) -> bool:
    origin, normal = plane
    return abs(float(np.dot(point - origin, normal))) <= tolerance


def _linear_direction_spans_caps(
    fact: dict[str, Any], linear_in_u: bool, caps, tolerance: float
) -> bool:
    """Every straight iso-line in the degree-1 direction must join the two caps."""

    parameters = fact["parameters"]
    surface = BRep_Tool.Surface_s(fact["shape"])
    u0, u1 = parameters["u_range"]
    v0, v1 = parameters["v_range"]
    for fraction in _SAMPLES:
        if linear_in_u:
            v = v0 + fraction * (v1 - v0)
            ends = (surface.Value(u0, v), surface.Value(u1, v))
        else:
            u = u0 + fraction * (u1 - u0)
            ends = (surface.Value(u, v0), surface.Value(u, v1))
        start, end = (np.array([p.X(), p.Y(), p.Z()]) for p in ends)
        joined = (
            _on_plane(start, caps[0], tolerance) and _on_plane(end, caps[1], tolerance)
        ) or (
            _on_plane(start, caps[1], tolerance) and _on_plane(end, caps[0], tolerance)
        )
        if not joined:
            return False
    return True


def _face_is_ruled(fact: dict[str, Any], caps, tolerance: float) -> bool:
    if fact["type"] == "PLANE":
        return True
    if fact["type"] not in _POLYNOMIAL_TYPES:
        return False
    u_degree = fact["parameters"].get("u_degree")
    v_degree = fact["parameters"].get("v_degree")
    if u_degree == 1 and v_degree == 1:
        return True
    if (u_degree == 1) == (v_degree == 1) or caps is None:
        return False
    # A degree-1 direction along the profile (polygonal sections blended
    # smoothly) is not a ruled loft; the straight lines must run cap to cap.
    return _linear_direction_spans_caps(fact, u_degree == 1, caps, tolerance)


def side_faces_are_ruled(
    facts: dict[str, dict[str, Any]],
    family: dict[str, Any],
    *,
    linear_tolerance: float,
) -> bool:
    """Return true when every side face is a ruled surface between the caps."""

    side_face_ids = family.get("side_face_ids") or []
    if not side_face_ids:
        return False
    start = _cap_plane(facts.get(family.get("start_face_id") or ""))
    end = _cap_plane(facts.get(family.get("end_face_id") or ""))
    caps = (start, end) if start is not None and end is not None else None
    tolerance = max(100.0 * linear_tolerance, 1.0e-6)
    return all(
        _face_is_ruled(facts[face_id], caps, tolerance) for face_id in side_face_ids
    )


__all__ = ["side_faces_are_ruled"]

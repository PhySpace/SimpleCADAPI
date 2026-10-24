"""Recover explicit longitudinal guide evidence for loft/sweep candidates."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from .common import entity_ids, unit, vector
from .profiles import local_axes, sample_edge_points


def _intersect_polyline_plane(
    points: np.ndarray,
    *,
    origin: Sequence[float],
    normal: Sequence[float],
    tolerance: float,
) -> dict[str, Any] | None:
    plane_origin = np.asarray(origin, dtype=float)
    plane_normal = unit(normal)
    signed = (points - plane_origin) @ plane_normal
    best: tuple[float, dict[str, Any]] | None = None
    for index in range(len(points) - 1):
        first = float(signed[index])
        second = float(signed[index + 1])
        if first * second > 0.0 and min(abs(first), abs(second)) > tolerance:
            continue
        denominator = first - second
        fraction = 0.0 if abs(denominator) <= 1.0e-15 else first / denominator
        fraction = min(1.0, max(0.0, fraction))
        point = points[index] + fraction * (points[index + 1] - points[index])
        residual = abs(float(np.dot(point - plane_origin, plane_normal)))
        tangent = points[index + 1] - points[index]
        if float(np.linalg.norm(tangent)) <= 1.0e-15:
            continue
        payload = {
            "point": vector(point),
            "tangent": vector(unit(tangent)),
            "curve_parameter": (index + fraction) / max(len(points) - 1, 1),
            "intersection_error": residual,
        }
        key = (residual, payload["curve_parameter"])
        if best is None or key < (best[0], best[1]["curve_parameter"]):
            best = (residual, payload)
    return None if best is None else best[1]


def _contour_points_3d(station: dict[str, Any]) -> np.ndarray | None:
    contours = station.get("contours") or []
    if not contours:
        return None
    samples = contours[0].get("samples_2d")
    plane = station.get("plane") or {}
    if not samples or plane.get("origin") is None or plane.get("normal") is None:
        return None
    origin = np.asarray(plane["origin"], dtype=float)
    x_axis, y_axis, _ = local_axes(plane["normal"])
    values = np.asarray(samples, dtype=float)
    if values.ndim != 2 or values.shape[1] != 2:
        return None
    return origin + np.outer(values[:, 0], x_axis) + np.outer(values[:, 1], y_axis)


def _candidate_edge_ids(
    facts: dict[str, dict[str, Any]], family: dict[str, Any]
) -> list[str]:
    cap_edges: set[str] = set()
    for key in ("start_loop", "end_loop"):
        loop = family.get(key) or {}
        cap_edges.update(loop.get("edge_ids") or ())
    return entity_ids(
        [
            edge_id
            for face_id in family.get("side_face_ids", ())
            for edge_id in facts[face_id].get("edges", ())
            if edge_id not in cap_edges
        ]
    )


def _cyclic_order(attachments: list[dict[str, Any]]) -> None:
    by_station: dict[str, list[dict[str, Any]]] = {}
    for attachment in attachments:
        by_station.setdefault(attachment["station_id"], []).append(attachment)
    for values in by_station.values():
        values.sort(
            key=lambda item: (
                item.get("profile_parameter", math.inf),
                item["guide_id"],
            )
        )
        for order, item in enumerate(values):
            item["cyclic_order"] = order


def _boundary_condition(
    guides: Sequence[dict[str, Any]],
    section_family: dict[str, Any],
    *,
    endpoint: str,
    angular_tolerance_degrees: float,
) -> dict[str, Any]:
    stations = section_family.get("stations") or []
    if not stations:
        return {"type": "unknown", "fit_error": None, "identifiability": "none"}
    station_index = 0 if endpoint == "start" else len(stations) - 1
    plane = stations[station_index].get("plane") or {}
    if plane.get("normal") is None:
        return {"type": "unknown", "fit_error": None, "identifiability": "none"}
    normal = unit(plane["normal"])
    tangents = []
    for guide in guides:
        intersections = guide.get("station_intersections") or []
        if station_index >= len(intersections):
            continue
        value = intersections[station_index]
        if value is None:
            continue
        tangent = unit(value["tangent"])
        if endpoint == "end":
            tangent = -tangent
        tangents.append(tangent)
    if not tangents:
        return {"type": "unknown", "fit_error": None, "identifiability": "none"}
    reference = tangents[0]
    tangents = [
        -value if float(np.dot(value, reference)) < 0.0 else value
        for value in tangents
    ]
    draft_angles = []
    for value in tangents:
        cosine = min(1.0, max(-1.0, abs(float(np.dot(value, normal)))))
        draft_angles.append(math.degrees(math.acos(cosine)))
    mean_tangent = unit(np.mean(np.asarray(tangents), axis=0))
    tangent_angles = []
    for value in tangents:
        cosine = min(1.0, max(-1.0, abs(float(np.dot(value, mean_tangent)))))
        tangent_angles.append(math.degrees(math.acos(cosine)))
    tangent_spread = max(tangent_angles)
    angle_spread = max(abs(value - float(np.mean(draft_angles))) for value in draft_angles)
    normal_limit = max(float(angular_tolerance_degrees), 1.0)
    if max(draft_angles) <= normal_limit:
        condition_type = "normal_to_section"
    elif tangent_spread <= max(2.0 * normal_limit, 3.0):
        condition_type = "fixed_direction"
    else:
        condition_type = "fitted_direction"
    return {
        "type": condition_type,
        "direction": vector(mean_tangent),
        "continuity": "G1_candidate",
        "draft_angle_degrees": float(np.mean(draft_angles)),
        "draft_angle_maximum_deviation_degrees": float(angle_spread),
        "effective_magnitude": None,
        "identifiability": "low",
        "fit_error": float(tangent_spread),
        "evidence_level": "explicit_brep_boundary_tangent",
    }


def recover_guides(
    model,
    facts: dict[str, dict[str, Any]],
    family: dict[str, Any],
    *,
    linear_tolerance: float,
    angular_tolerance_degrees: float,
    maximum_selected_guides: int = 4,
) -> dict[str, Any]:
    """Return explicit longitudinal edges and section attachment evidence."""

    section_family = family.get("section_family") or {}
    stations = section_family.get("stations") or []
    candidates = []
    attachments: list[dict[str, Any]] = []
    for edge_id in _candidate_edge_ids(facts, family):
        _, _, edge = model.resolve_entity(edge_id)
        try:
            points = sample_edge_points(edge, count=65)
        except (RuntimeError, ValueError):
            continue
        if points.ndim != 2 or points.shape[0] < 2 or points.shape[1] != 3:
            continue
        intersections = []
        guide_attachments = []
        for station_index, station in enumerate(stations):
            plane = station.get("plane") or {}
            if plane.get("origin") is None or plane.get("normal") is None:
                intersections.append(None)
                continue
            intersection = _intersect_polyline_plane(
                points,
                origin=plane["origin"],
                normal=plane["normal"],
                tolerance=max(20.0 * linear_tolerance, 1.0e-7),
            )
            intersections.append(intersection)
            if intersection is None:
                continue
            contour_points = _contour_points_3d(station)
            profile_parameter = None
            profile_error = None
            if contour_points is not None and len(contour_points):
                distances = np.linalg.norm(
                    contour_points - np.asarray(intersection["point"], dtype=float),
                    axis=1,
                )
                nearest = int(np.argmin(distances))
                profile_parameter = nearest / max(len(contour_points), 1)
                profile_error = float(distances[nearest])
            attachment = {
                "guide_id": edge_id,
                "station_id": f"station:{station_index}",
                "profile_id": f"station:{station_index}:contour:0",
                "curve_parameter": intersection["curve_parameter"],
                "profile_parameter": profile_parameter,
                "vertex_id": None,
                "intersection_point": intersection["point"],
                "intersection_error": max(
                    float(intersection["intersection_error"]),
                    float(profile_error or 0.0),
                ),
                "cyclic_order": None,
                "is_singular_attachment": False,
            }
            guide_attachments.append(attachment)
        coverage = sum(value is not None for value in intersections)
        if coverage < 2:
            continue
        candidates.append(
            {
                "guide_id": edge_id,
                "source": "brep_longitudinal_edge",
                "evidence_level": "explicit_brep",
                "curve_definition": {
                    "type": "sampled_brep_edge",
                    "points": [
                        vector(points[index])
                        for index in np.linspace(
                            0, len(points) - 1, min(17, len(points)), dtype=int
                        )
                    ],
                },
                "station_intersections": intersections,
                "covered_station_count": coverage,
                "coverage_fraction": coverage / max(len(stations), 1),
                "maximum_intersection_error": max(
                    float(value["intersection_error"])
                    for value in intersections
                    if value is not None
                ),
            }
        )
        attachments.extend(guide_attachments)
    candidates.sort(
        key=lambda item: (
            -item["covered_station_count"],
            item["maximum_intersection_error"],
            int(item["guide_id"].split(":", 1)[1]),
        )
    )
    selected = []
    used_parameters: set[int] = set()
    for candidate in candidates:
        own = [
            item
            for item in attachments
            if item["guide_id"] == candidate["guide_id"]
            and item["profile_parameter"] is not None
        ]
        parameter_key = (
            int(round(1000.0 * float(own[len(own) // 2]["profile_parameter"])))
            if own
            else int(candidate["guide_id"].split(":", 1)[1])
        )
        if parameter_key in used_parameters:
            continue
        used_parameters.add(parameter_key)
        selected.append(candidate)
        if len(selected) >= maximum_selected_guides:
            break
    selected_ids = {item["guide_id"] for item in selected}
    selected_attachments = [
        item for item in attachments if item["guide_id"] in selected_ids
    ]
    _cyclic_order(selected_attachments)
    boundary_conditions = {
        endpoint: _boundary_condition(
            selected,
            section_family,
            endpoint=endpoint,
            angular_tolerance_degrees=angular_tolerance_degrees,
        )
        for endpoint in ("start", "end")
    }
    return {
        "status": "recovered" if selected else "no_explicit_guides",
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "selection_policy": "maximum_coverage_unique_mid_profile_parameter",
        "guides": selected,
        "guide_attachment_map": selected_attachments,
        "boundary_conditions": boundary_conditions,
    }


__all__ = ["recover_guides"]

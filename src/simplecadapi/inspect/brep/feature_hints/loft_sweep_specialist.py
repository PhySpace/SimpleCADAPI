"""Second-pass loft/sweep analysis on an already bounded section family."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from .guide_recovery import recover_guides
from .path_recovery import recover_path


def _resample_closed(points: Sequence[Sequence[float]], count: int) -> np.ndarray:
    values = np.asarray(points, dtype=float)
    if values.ndim != 2 or values.shape[0] < 3:
        raise ValueError("closed profile requires at least three points")
    if not np.allclose(values[0], values[-1]):
        values = np.vstack([values, values[0]])
    segment_lengths = np.linalg.norm(np.diff(values, axis=0), axis=1)
    perimeter = float(np.sum(segment_lengths))
    if perimeter <= 1.0e-15:
        raise ValueError("closed profile has zero perimeter")
    cumulative = np.concatenate([[0.0], np.cumsum(segment_lengths)])
    targets = np.linspace(0.0, perimeter, count, endpoint=False)
    result = []
    for target in targets:
        index = min(int(np.searchsorted(cumulative, target, side="right") - 1), len(values) - 2)
        length = segment_lengths[index]
        fraction = 0.0 if length <= 1.0e-15 else (target - cumulative[index]) / length
        result.append(values[index] + fraction * (values[index + 1] - values[index]))
    return np.asarray(result, dtype=float)


def _normalized(points: np.ndarray) -> np.ndarray:
    centered = points - np.mean(points, axis=0)
    scale = float(np.sqrt(np.mean(np.sum(centered * centered, axis=1))))
    if scale <= 1.0e-15:
        raise ValueError("profile has zero extent")
    return centered / scale


def _procrustes(first: np.ndarray, second: np.ndarray) -> tuple[float, float]:
    covariance = first.T @ second
    left, _, right = np.linalg.svd(covariance)
    rotation = right.T @ left.T
    if float(np.linalg.det(rotation)) < 0.0:
        right[-1, :] *= -1.0
        rotation = right.T @ left.T
    fitted = first @ rotation.T
    distances = np.linalg.norm(fitted - second, axis=1)
    angle = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))
    return float(np.sqrt(np.mean(distances**2))), angle


def _states(points: np.ndarray) -> list[tuple[bool, int, np.ndarray]]:
    result = []
    for reversed_order in (False, True):
        ordered = points[::-1] if reversed_order else points
        for offset in range(len(points)):
            result.append((reversed_order, offset, np.roll(ordered, -offset, axis=0)))
    return result


def align_section_sequence(
    section_family: dict[str, Any],
    *,
    sample_count: int = 48,
) -> dict[str, Any]:
    """Choose profile directions and seams with one global chain objective."""

    stations = []
    for index, station in enumerate(section_family.get("stations", ())):
        contours = station.get("contours") or []
        if not contours or not contours[0].get("closed", False):
            continue
        samples = contours[0].get("samples_2d")
        if not samples:
            continue
        try:
            points = _normalized(_resample_closed(samples, sample_count))
        except ValueError:
            continue
        stations.append((index, float(station.get("station", index)), points))
    if len(stations) < 2:
        return {
            "status": "insufficient_profiles",
            "station_count": len(stations),
            "profiles": [],
            "global_cost": None,
        }
    anchor = stations[0][2]
    candidate_states = [_states(item[2]) for item in stations]
    costs = [0.0] + [math.inf] * (len(candidate_states[0]) - 1)
    predecessors: list[list[int]] = []
    for station_index in range(1, len(stations)):
        current_states = candidate_states[station_index]
        previous_states = candidate_states[station_index - 1]
        next_costs = [math.inf] * len(current_states)
        next_predecessors = [-1] * len(current_states)
        for current_index, (_, current_offset, current_points) in enumerate(current_states):
            anchor_error, _ = _procrustes(anchor, current_points)
            for previous_index, (_, previous_offset, previous_points) in enumerate(previous_states):
                if not math.isfinite(costs[previous_index]):
                    continue
                adjacent_error, _ = _procrustes(previous_points, current_points)
                jump = abs(current_offset - previous_offset)
                jump = min(jump, sample_count - jump) / sample_count
                total = (
                    costs[previous_index]
                    + adjacent_error
                    + 0.25 * anchor_error
                    + 0.01 * jump * jump
                )
                if total < next_costs[current_index]:
                    next_costs[current_index] = total
                    next_predecessors[current_index] = previous_index
        costs = next_costs
        predecessors.append(next_predecessors)
    state_index = min(range(len(costs)), key=lambda index: costs[index])
    selected = [state_index]
    for values in reversed(predecessors):
        state_index = values[state_index]
        selected.append(state_index)
    selected.reverse()
    profiles = []
    for (source_index, station_value, _), states, chosen in zip(
        stations, candidate_states, selected
    ):
        reversed_order, offset, points = states[chosen]
        anchor_error, rotation = _procrustes(anchor, points)
        profiles.append(
            {
                "source_station_index": source_index,
                "station": station_value,
                "reversed": reversed_order,
                "cyclic_offset": offset,
                "seam_parameter": offset / sample_count,
                "seam_angle_degrees": 360.0 * offset / sample_count,
                "rotation_from_start_degrees": rotation,
                "normalized_rms_error_to_start": anchor_error,
            }
        )
    return {
        "status": "aligned",
        "method": "global_anchor_and_adjacent_dynamic_programming",
        "sample_count": sample_count,
        "station_count": len(profiles),
        "profiles": profiles,
        "global_cost": float(min(costs)),
    }


def _linear_law(values: Sequence[float], stations: Sequence[float]) -> dict[str, Any]:
    if len(values) < 2 or len(values) != len(stations):
        return {"status": "insufficient_samples", "samples": list(values)}
    design = np.column_stack([np.asarray(stations, dtype=float), np.ones(len(stations))])
    coefficients, *_ = np.linalg.lstsq(design, np.asarray(values, dtype=float), rcond=None)
    predicted = design @ coefficients
    residual = float(np.sum((np.asarray(values) - predicted) ** 2))
    total = float(np.sum((np.asarray(values) - np.mean(values)) ** 2))
    r_squared = 1.0 if total <= 1.0e-30 else 1.0 - residual / total
    return {
        "status": "fitted",
        "model": "linear",
        "slope": float(coefficients[0]),
        "intercept": float(coefficients[1]),
        "r_squared": float(r_squared),
        "samples": [float(value) for value in values],
    }


def _profile_law(
    family: dict[str, Any], alignment: dict[str, Any]
) -> dict[str, Any]:
    stations = family["section_family"].get("stations") or []
    station_values = [float(item.get("station", index)) for index, item in enumerate(stations)]
    areas = [
        float((item.get("contours") or [{}])[0].get("area") or 0.0)
        for item in stations
    ]
    rotations = [
        float(item["rotation_from_start_degrees"])
        for item in alignment.get("profiles", ())
    ]
    rotation_stations = [
        float(item["station"]) for item in alignment.get("profiles", ())
    ]
    reference_area = next((value for value in areas if value > 1.0e-24), 0.0)
    scales = [
        math.sqrt(value / reference_area) if value > 0.0 and reference_area > 0.0 else 0.0
        for value in areas
    ]
    return {
        "type": "rigid" if family.get("rigid_profile") else "general_morph",
        "area_law": _linear_law(areas, station_values),
        "scale_law": _linear_law(scales, station_values),
        "rotation_law": _linear_law(rotations, rotation_stations),
    }


def _terminal_mode(family: dict[str, Any]) -> str:
    explicit = family.get("terminal_mode")
    if explicit:
        return str(explicit)
    if family.get("apex_vertex_ids"):
        return "both_points" if len(family["apex_vertex_ids"]) == 2 else "end_point"
    if family.get("apex_vertex_id"):
        return "end_point"
    return "none"


def _adaptive_station_plan(
    section_family: dict[str, Any], alignment: dict[str, Any], *, maximum_stations: int = 12
) -> dict[str, Any]:
    """Request bounded midpoint refinements where adjacent profile change is high."""

    stations = section_family.get("stations") or []
    if len(stations) < 2:
        return {
            "status": "insufficient_stations",
            "current_station_count": len(stations),
            "maximum_station_count": maximum_stations,
            "requests": [],
        }
    alignment_by_source = {
        int(item["source_station_index"]): item
        for item in alignment.get("profiles", ())
    }
    requests = []
    for index in range(len(stations) - 1):
        first = stations[index]
        second = stations[index + 1]
        first_area = float((first.get("contours") or [{}])[0].get("area") or 0.0)
        second_area = float((second.get("contours") or [{}])[0].get("area") or 0.0)
        area_scale = max(first_area, second_area, 1.0e-24)
        area_change = abs(second_area - first_area) / area_scale
        first_alignment = alignment_by_source.get(index) or {}
        second_alignment = alignment_by_source.get(index + 1) or {}
        rotation_change = abs(
            float(second_alignment.get("rotation_from_start_degrees") or 0.0)
            - float(first_alignment.get("rotation_from_start_degrees") or 0.0)
        )
        shape_error = max(
            float(first_alignment.get("normalized_rms_error_to_start") or 0.0),
            float(second_alignment.get("normalized_rms_error_to_start") or 0.0),
        )
        severity = max(area_change / 0.25, rotation_change / 15.0, shape_error / 0.1)
        if severity <= 1.0:
            continue
        first_station = float(first.get("station", index))
        second_station = float(second.get("station", index + 1))
        requests.append(
            {
                "station": 0.5 * (first_station + second_station),
                "source": "error_refinement",
                "span_indices": [index, index + 1],
                "severity": float(severity),
                "reasons": {
                    "relative_area_change": float(area_change),
                    "rotation_change_degrees": float(rotation_change),
                    "normalized_shape_error": float(shape_error),
                },
            }
        )
    available = max(maximum_stations - len(stations), 0)
    requests.sort(key=lambda item: (-item["severity"], item["station"]))
    requests = sorted(requests[:available], key=lambda item: item["station"])
    return {
        "status": "refinement_requested" if requests else "adequate",
        "current_station_count": len(stations),
        "maximum_station_count": maximum_stations,
        "requests": requests,
        "stop_conditions": ["error_threshold", "station_budget", "time_budget"],
    }


def _implied_by_ruled(conditions: dict[str, Any]) -> dict[str, Any]:
    """Mark end tangents of a ruled loft as consequences, not extra constraints.

    On a ruled span the side direction at each end is the straight ruling to
    the next section, so the sections alone reproduce it. The measured values
    stay as evidence under ``measured_type``.
    """

    result = {}
    for endpoint, condition in conditions.items():
        if isinstance(condition, dict) and condition.get("type") not in {
            None,
            "free",
            "unknown",
            "singular",
        }:
            condition = {
                **condition,
                "type": "implied_by_ruled",
                "measured_type": condition.get("type"),
            }
        result[endpoint] = condition
    return result


def analyze_loft_sweep_family(
    model,
    facts: dict[str, dict[str, Any]],
    family: dict[str, Any],
    *,
    linear_tolerance: float,
    angular_tolerance_degrees: float,
    feature_family: str,
    side_types: Sequence[str],
    interpolation: str | None = None,
) -> dict[str, Any]:
    """Run the bounded specialist pass after coarse family recognition.

    ``interpolation`` is the caller's ruled/smooth decision; without it the
    side carrier types decide (planes only means ruled).
    """

    section_family = family.get("section_family") or {}
    alignment = align_section_sequence(section_family)
    path = recover_path(section_family, linear_tolerance=linear_tolerance)
    guides = recover_guides(
        model,
        facts,
        family,
        linear_tolerance=linear_tolerance,
        angular_tolerance_degrees=angular_tolerance_degrees,
    )
    path_type = ((path.get("recommended") or {}).get("curve_type"))
    terminal_mode = _terminal_mode(family)
    path_profile_mode = "rigid" if family.get("rigid_profile") else "variable"
    if feature_family == "sweep":
        control_mode = "path"
        strategy = "path_constrained"
    elif path_type not in {None, "line"} and terminal_mode == "none":
        control_mode = "path"
        strategy = "path_constrained"
    else:
        control_mode = "sections_only"
        strategy = "section_only"
    station_count = len(section_family.get("stations") or [])
    if interpolation is None:
        interpolation = "ruled" if set(side_types) <= {"PLANE"} else "smooth"
    boundary_conditions = guides["boundary_conditions"]
    if interpolation == "ruled" and feature_family == "loft":
        boundary_conditions = _implied_by_ruled(boundary_conditions)
    adaptive_station_plan = _adaptive_station_plan(section_family, alignment)
    frame_law = {
        "type": (
            "translation_frame"
            if path_type == "line"
            else "corrected_frenet_frame"
        ),
        "source": "section_orientation_and_recovered_path",
        "native_api_policy": "corrected_frenet",
    }
    return {
        "version": "1.0",
        "status": "complete" if station_count >= 2 else "partial",
        "loft_control_mode": control_mode,
        "construction_strategy": strategy,
        "result_kind": "solid",
        "path_profile_mode": path_profile_mode,
        "terminal_mode": terminal_mode,
        "interpolation": interpolation,
        "interpolation_by_span": [
            {
                "start_station_index": index,
                "end_station_index": index + 1,
                "mode": interpolation,
                "evidence": "side_carrier_types",
            }
            for index in range(max(station_count - 1, 0))
        ],
        "section_alignment": alignment,
        "profile_law": _profile_law(family, alignment),
        "frame_law": frame_law,
        "adaptive_station_plan": adaptive_station_plan,
        "spine": path,
        "guides": guides["guides"],
        "guide_attachment_map": guides["guide_attachment_map"],
        "boundary_conditions": boundary_conditions,
        "guide_recovery_status": guides["status"],
        "specialist_trigger": {
            "decision": "accepted" if station_count >= 2 else "incomplete",
            "reason": (
                "bounded_candidate_has_trackable_section_family"
                if station_count >= 2
                else "fewer_than_two_recoverable_stations"
            ),
            "roi_face_count": len(family.get("side_face_ids") or []),
            "budget": {
                "maximum_station_count": 12,
                "maximum_selected_guides": 4,
                "maximum_path_candidates": 4,
            },
        },
        "reconstruction_support": "native",
    }


__all__ = ["align_section_sequence", "analyze_loft_sweep_family"]

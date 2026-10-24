"""Recover bounded path hypotheses from ordered section stations."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from .common import unit, vector
from .profiles import local_axes


def _station_points(section_family: dict[str, Any]) -> tuple[list[float], np.ndarray]:
    stations: list[float] = []
    points: list[list[float]] = []
    for item in section_family.get("stations", ()):
        plane = item.get("plane") or {}
        origin = plane.get("origin")
        if origin is None or len(origin) != 3:
            continue
        point = np.asarray(origin, dtype=float)
        if not np.all(np.isfinite(point)):
            continue
        stations.append(float(item.get("station", len(stations))))
        points.append(point.tolist())
    if not points:
        return [], np.empty((0, 3), dtype=float)
    order = np.argsort(np.asarray(stations, dtype=float))
    ordered_stations = [stations[int(index)] for index in order]
    ordered_points = np.asarray([points[int(index)] for index in order], dtype=float)
    return ordered_stations, ordered_points


def _canonical_direction(
    direction: Sequence[float], points: np.ndarray
) -> np.ndarray:
    value = unit(direction)
    if len(points) >= 2 and float(np.dot(value, points[-1] - points[0])) < 0.0:
        value = -value
    return value


def _line_candidate(points: np.ndarray) -> dict[str, Any]:
    center = np.mean(points, axis=0)
    _, _, right = np.linalg.svd(points - center, full_matrices=False)
    direction = _canonical_direction(right[0], points)
    projected = center + np.outer((points - center) @ direction, direction)
    distances = np.linalg.norm(points - projected, axis=1)
    return {
        "curve_type": "line",
        "curve_definition": {
            "start": vector(points[0]),
            "end": vector(points[-1]),
            "point": vector(center),
            "direction": vector(direction),
        },
        "rms_error": float(np.sqrt(np.mean(distances**2))),
        "maximum_error": float(np.max(distances)),
        "complexity": 2,
    }


def _circle_candidate(points: np.ndarray) -> dict[str, Any] | None:
    if len(points) < 3:
        return None
    center = np.mean(points, axis=0)
    _, _, right = np.linalg.svd(points - center, full_matrices=False)
    normal = unit(right[-1])
    x_axis, y_axis, _ = local_axes(normal)
    relative = points - center
    x = relative @ x_axis
    y = relative @ y_axis
    matrix = np.column_stack([2.0 * x, 2.0 * y, np.ones(len(points))])
    try:
        solution, *_ = np.linalg.lstsq(matrix, x * x + y * y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    radius_squared = float(solution[2] + solution[0] ** 2 + solution[1] ** 2)
    if radius_squared <= 1.0e-24:
        return None
    radius = math.sqrt(radius_squared)
    circle_center = center + solution[0] * x_axis + solution[1] * y_axis
    radial = points - circle_center
    plane_offsets = radial @ normal
    planar = radial - np.outer(plane_offsets, normal)
    radii = np.linalg.norm(planar, axis=1)
    distances = np.sqrt((radii - radius) ** 2 + plane_offsets**2)
    angles = np.unwrap(np.arctan2(planar @ y_axis, planar @ x_axis))
    angle_span = float(angles[-1] - angles[0])
    if abs(angle_span) <= math.radians(1.0):
        return None
    return {
        "curve_type": "circular_arc",
        "curve_definition": {
            "center": vector(circle_center),
            "normal": vector(normal),
            "radius": radius,
            "start": vector(points[0]),
            "end": vector(points[-1]),
            "angle_span_degrees": math.degrees(angle_span),
        },
        "rms_error": float(np.sqrt(np.mean(distances**2))),
        "maximum_error": float(np.max(distances)),
        "complexity": 5,
    }


def _helix_candidate(points: np.ndarray) -> dict[str, Any] | None:
    if len(points) < 5:
        return None
    center = np.mean(points, axis=0)
    covariance = (points - center).T @ (points - center)
    _, axes = np.linalg.eigh(covariance)
    best: tuple[tuple[float, float], dict[str, Any]] | None = None
    for column in range(3):
        axis = _canonical_direction(axes[:, column], points)
        x_axis, y_axis, _ = local_axes(axis)
        relative = points - center
        x = relative @ x_axis
        y = relative @ y_axis
        matrix = np.column_stack([2.0 * x, 2.0 * y, np.ones(len(points))])
        solution, *_ = np.linalg.lstsq(matrix, x * x + y * y, rcond=None)
        radius_squared = float(solution[2] + solution[0] ** 2 + solution[1] ** 2)
        if radius_squared <= 1.0e-24:
            continue
        helix_center = center + solution[0] * x_axis + solution[1] * y_axis
        relative = points - helix_center
        axial = relative @ axis
        planar = relative - np.outer(axial, axis)
        radii = np.linalg.norm(planar, axis=1)
        radius = float(np.mean(radii))
        angles = np.unwrap(np.arctan2(planar @ y_axis, planar @ x_axis))
        angle_span = float(angles[-1] - angles[0])
        if abs(angle_span) <= math.radians(20.0):
            continue
        design = np.column_stack([angles, np.ones(len(points))])
        coefficients, *_ = np.linalg.lstsq(design, axial, rcond=None)
        predicted_axial = design @ coefficients
        radial_error = radii - radius
        axial_error = axial - predicted_axial
        distances = np.sqrt(radial_error**2 + axial_error**2)
        pitch = abs(float(coefficients[0])) * 2.0 * math.pi
        candidate = {
            "curve_type": "helix",
            "curve_definition": {
                "axis": {
                    "point": vector(helix_center),
                    "direction": vector(axis),
                },
                "radius": radius,
                "pitch": pitch,
                "turn_count": abs(angle_span) / (2.0 * math.pi),
                "handedness": "right" if coefficients[0] >= 0.0 else "left",
                "start": vector(points[0]),
                "end": vector(points[-1]),
            },
            "rms_error": float(np.sqrt(np.mean(distances**2))),
            "maximum_error": float(np.max(distances)),
            "complexity": 7,
        }
        key = (candidate["maximum_error"], candidate["rms_error"])
        if best is None or key < best[0]:
            best = (key, candidate)
    return None if best is None else best[1]


def recover_path(
    section_family: dict[str, Any],
    *,
    linear_tolerance: float,
) -> dict[str, Any]:
    """Return deterministic path candidates from section-plane origins.

    The recovered path is a geometric hypothesis.  It is never described as
    the original authoring spine unless an explicit BRep curve later proves it.
    """

    stations, points = _station_points(section_family)
    if len(points) < 2:
        return {
            "status": "insufficient_stations",
            "source": "section_plane_origins",
            "station_count": len(points),
            "recommended": None,
            "candidates": [],
        }
    scale = max(float(np.linalg.norm(points[-1] - points[0])), 1.0)
    error_limit = max(50.0 * float(linear_tolerance), 1.0e-3 * scale)
    candidates = [_line_candidate(points)]
    circle = _circle_candidate(points)
    if circle is not None:
        candidates.append(circle)
    helix = _helix_candidate(points)
    if helix is not None:
        candidates.append(helix)
    candidates.sort(
        key=lambda item: (
            item["maximum_error"] > error_limit,
            item["complexity"],
            item["maximum_error"],
            item["rms_error"],
        )
    )
    recommended = candidates[0]
    if recommended["maximum_error"] > error_limit:
        recommended = {
            "curve_type": "spatial_bspline_proxy",
            "curve_definition": {
                "interpolation_points": [vector(point) for point in points],
                "parameters": stations,
            },
            "rms_error": 0.0,
            "maximum_error": 0.0,
            "complexity": len(points),
            "proxy_reason": "simple_path_models_exceed_error_limit",
        }
        candidates.append(recommended)
    return {
        "status": "recovered",
        "source": "section_plane_origins",
        "evidence_level": "reconstruction_proxy",
        "path_role": "section_reference_curve",
        "station_count": len(points),
        "error_limit": error_limit,
        "recommended": recommended,
        "candidates": candidates,
    }


__all__ = ["recover_path"]

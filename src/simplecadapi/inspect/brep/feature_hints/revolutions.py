"""Whole-body and local constant-meridian revolution recognition."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from ..queries import inspect_section_rdescriptor
from .common import (
    axial_radial_coordinates,
    body_face_ids,
    cluster_axes,
    confidence,
    entity_ids,
    entity_index,
    evidence,
    fact_axis,
    face_vertices,
    parallel,
    plane_contains_axis,
    unit,
    vector,
)
from .profiles import measure_meridian_profile


_AXIAL_CARRIERS = {"CYLINDER", "CONE", "TORUS", "REVOLUTION"}


def _face_sweep_degrees(fact: dict[str, Any]) -> float:
    value = fact["parameters"].get("u_range") or (0.0, 0.0)
    return min(360.0, math.degrees(abs(float(value[1]) - float(value[0]))))


def _face_axial_span(
    fact: dict[str, Any], axis: dict[str, Sequence[float]]
) -> tuple[float, float]:
    values = [
        axial_radial_coordinates(point, axis)[0]
        for point in face_vertices(fact["shape"])
    ]
    if not values:
        center = axial_radial_coordinates(fact["centroid"], axis)[0]
        return center, center
    return min(values), max(values)


def _body_axial_span(
    face_ids: Sequence[str],
    facts: dict[str, dict[str, Any]],
    axis: dict[str, Sequence[float]],
) -> float:
    values = [
        axial_radial_coordinates(point, axis)[0]
        for face_id in face_ids
        for point in face_vertices(facts[face_id]["shape"])
    ]
    return max(values) - min(values) if values else 0.0


def _angular_consistency(
    *,
    model,
    axis: dict[str, Sequence[float]],
    sweep_angle_degrees: float,
    full: bool,
    carrier_face_ids: Sequence[str],
    section_face_ids: Sequence[str],
    facts: dict[str, dict[str, Any]],
    linear_tolerance: float,
) -> dict[str, Any]:
    stations = (
        [0.0, 90.0, 180.0, 270.0]
        if full
        else [
            0.0,
            0.25 * sweep_angle_degrees,
            0.5 * sweep_angle_degrees,
            0.75 * sweep_angle_degrees,
            sweep_angle_degrees,
        ]
    )
    axis_point = np.asarray(vector(axis["point"]), dtype=float)
    axis_direction = np.asarray(unit(axis["direction"]), dtype=float)
    reference = min(
        np.eye(3), key=lambda value: abs(float(np.dot(value, axis_direction)))
    )
    first_basis = unit(np.cross(axis_direction, reference))
    second_basis = unit(np.cross(axis_direction, first_basis))
    radial_vectors = []
    for face_id in carrier_face_ids:
        for point in face_vertices(facts[face_id]["shape"]):
            offset = np.asarray(vector(point), dtype=float) - axis_point
            radial = offset - float(np.dot(offset, axis_direction)) * axis_direction
            if np.linalg.norm(radial) > max(linear_tolerance, 1.0e-12):
                radial_vectors.append(unit(radial))
    if not radial_vectors:
        raise ValueError("revolution carrier has no measurable radial direction")
    if full:
        start_angle = math.atan2(
            float(np.dot(radial_vectors[0], second_basis)),
            float(np.dot(radial_vectors[0], first_basis)),
        )
    else:
        angles = sorted(
            (
                math.atan2(
                    float(np.dot(radial, second_basis)),
                    float(np.dot(radial, first_basis)),
                )
                % (2.0 * math.pi)
            )
            for radial in radial_vectors
        )
        gaps = [
            ((angles[(index + 1) % len(angles)] - angle) % (2.0 * math.pi), index)
            for index, angle in enumerate(angles)
        ]
        _, gap_index = max(gaps)
        start_angle = angles[(gap_index + 1) % len(angles)]

    section_planes: dict[float, dict[str, list[float]]] = {}

    def section_polylines(angle_degrees: float) -> list[np.ndarray]:
        angle = start_angle + math.radians(angle_degrees)
        radial = math.cos(angle) * first_basis + math.sin(angle) * second_basis
        normal = unit(np.cross(axis_direction, radial))
        section_planes[angle_degrees] = {
            "origin": [round(float(value), 9) for value in axis_point],
            "normal": [round(float(value), 9) for value in normal],
        }
        section = inspect_section_rdescriptor(
            model_or_path=model,
            origin=axis_point,
            normal=normal,
            tolerance=max(linear_tolerance, 1.0e-9),
            samples_per_edge=64,
            connection_tolerance=max(20.0 * linear_tolerance, 1.0e-7),
            compact=False,
            face_ids=section_face_ids,
        )
        values = []
        for edge in section["edges"]:
            points = np.asarray(edge["samples_3d"], dtype=float)
            offsets = points - axis_point
            axial = offsets @ axis_direction
            radial_distance = np.linalg.norm(
                offsets - axial[:, None] * axis_direction, axis=1
            )
            values.append(np.column_stack((axial, radial_distance)))
        return values

    def directed_distance(points: np.ndarray, polylines: list[np.ndarray]) -> float:
        maximum = 0.0
        segments = [
            (polyline[:-1], polyline[1:])
            for polyline in polylines
            if len(polyline) >= 2
        ]
        if not segments:
            return math.inf
        for point in points:
            minimum = math.inf
            for starts, ends in segments:
                vectors = ends - starts
                squared = np.sum(vectors * vectors, axis=1)
                projection = np.zeros(len(vectors), dtype=float)
                nonzero = squared > 1.0e-30
                projection[nonzero] = (
                    np.sum((point - starts[nonzero]) * vectors[nonzero], axis=1)
                    / squared[nonzero]
                )
                closest = starts + np.clip(projection, 0.0, 1.0)[:, None] * vectors
                minimum = min(
                    minimum, float(np.min(np.linalg.norm(closest - point, axis=1)))
                )
            maximum = max(maximum, minimum)
        return maximum

    measured = {station: section_polylines(station) for station in stations}
    empty_stations = [station for station, polylines in measured.items() if not polylines]
    if empty_stations:
        return {
            "stations": stations,
            "measurements": [],
            "maximum_correspondence_error": None,
            "tolerance": None,
            "passed": False,
            "unavailable_reason": "angular section produced no meridian boundary",
            "empty_stations": empty_stations,
        }
    reference_station = 0.0 if full else 0.5 * sweep_angle_degrees
    reference_polylines = measured[reference_station]
    reference_points = np.vstack(reference_polylines)
    measurements = []
    for station in stations:
        observed = measured[station]
        observed_points = np.vstack(observed)
        forward = directed_distance(reference_points, observed)
        reverse = directed_distance(observed_points, reference_polylines)
        maximum_error = round(max(forward, reverse), 9)
        measurements.append(
            {
                "angle_degrees": station,
                "source": "actual_brep_section",
                "forward_deviation": round(float(forward), 9),
                "reverse_deviation": round(float(reverse), 9),
                "maximum_correspondence_error": maximum_error,
                "plane": section_planes[station],
            }
        )
    maximum = max(item["maximum_correspondence_error"] for item in measurements)
    maximum_radius = max(
        axial_radial_coordinates(point, axis)[1]
        for face_id in carrier_face_ids
        for point in face_vertices(facts[face_id]["shape"])
    )
    tolerance = max(50.0 * linear_tolerance, 1.0e-3 * maximum_radius)
    return {
        "stations": stations,
        "measurements": measurements,
        "maximum_correspondence_error": maximum,
        "tolerance": tolerance,
        "passed": maximum <= tolerance,
    }


def _whole_candidate(
    *,
    model,
    body_id: str,
    local_face_ids: list[str],
    cluster: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> dict[str, Any] | None:
    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    axis = cluster["axis"]
    carrier_face_ids = entity_ids(cluster["entity_ids"])
    nonplanar = [
        face_id
        for face_id in local_face_ids
        if facts[face_id]["type"] != "PLANE" and facts[face_id]["type"] != "SPHERE"
    ]
    if set(nonplanar) != set(carrier_face_ids):
        return None
    angular_caps = []
    axial_caps = []
    unsupported_planes = []
    for face_id in local_face_ids:
        fact = facts[face_id]
        if fact["type"] != "PLANE" or fact["normal"] is None:
            continue
        if parallel(fact["normal"], axis["direction"], angular):
            axial_caps.append(face_id)
        elif plane_contains_axis(
            plane_point=fact["centroid"],
            plane_normal=fact["normal"],
            axis=axis,
            linear_tolerance=max(20.0 * linear, 1.0e-7),
            angular_tolerance_degrees=angular,
        ):
            angular_caps.append(face_id)
        else:
            unsupported_planes.append(face_id)
    if unsupported_planes:
        return None
    sweeps = [_face_sweep_degrees(facts[face_id]) for face_id in carrier_face_ids]
    if not sweeps:
        return None
    full = all(value >= 360.0 - angular for value in sweeps)
    if full:
        if angular_caps:
            return None
        sweep = 360.0
        form = "whole_body_full_revolution"
    else:
        sweep = max(sweeps)
        if (
            sweep <= angular
            or sweep >= 360.0 - angular
            or len(angular_caps) < 2
            or max(sweeps) - min(sweeps) > angular
        ):
            return None
        form = "whole_body_partial_revolution"
    profile = measure_meridian_profile(local_face_ids, facts, axis=axis)
    consistency = _angular_consistency(
        model=model,
        axis=axis,
        sweep_angle_degrees=sweep,
        full=full,
        carrier_face_ids=carrier_face_ids,
        section_face_ids=entity_ids([*carrier_face_ids, *axial_caps]),
        facts=facts,
        linear_tolerance=linear,
    )
    if not consistency["passed"]:
        return None
    return {
        "kind": "revolution_region_candidate",
        "claim": "geometric_candidate",
        "body_id": body_id,
        "entity_ids": entity_ids(local_face_ids),
        "highlight_entity_ids": entity_ids(local_face_ids),
        "support_entity_ids": entity_ids([*axial_caps, *angular_caps]),
        "geometry": {
            "form": form,
            "region_role": "neutral",
            "axis": axis,
            "sweep_angle_degrees": sweep,
            "minimum_radius": profile["minimum_radius"],
            "maximum_radius": profile["maximum_radius"],
            "axial_span": profile["axial_span"],
            "carrier_face_ids": carrier_face_ids,
            "angular_cap_face_ids": entity_ids(angular_caps),
            "axial_cap_face_ids": entity_ids(axial_caps),
            "profile": profile,
            "angular_section_consistency": consistency,
        },
        "confidence": confidence("strong"),
        "evidence": [
            evidence(
                "revolution.axis_cluster",
                entity_ids_value=carrier_face_ids,
                observed={"axis": axis, "carrier_count": len(carrier_face_ids)},
            ),
            evidence(
                "revolution.angular_domain",
                entity_ids_value=entity_ids(angular_caps),
                observed={
                    "sweep_angle_degrees": sweep,
                    "full": full,
                    "angular_cap_count": len(angular_caps),
                },
            ),
            evidence(
                "revolution.meridian_correspondence",
                entity_ids_value=carrier_face_ids,
                observed=consistency,
            ),
            evidence(
                "revolution.region_boundary_and_material_side",
                entity_ids_value=entity_ids(local_face_ids),
                observed={"coverage": "whole_body", "material_side": "neutral"},
            ),
        ],
    }


def _radius_groups(
    carrier_face_ids: Sequence[str],
    facts: dict[str, dict[str, Any]],
    radius_tolerance: float,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for face_id in carrier_face_ids:
        fact = facts[face_id]
        if fact["type"] != "CYLINDER":
            continue
        radius = float(fact["parameters"]["radius"])
        group = next(
            (
                item
                for item in groups
                if abs(float(item["radius"]) - radius) <= radius_tolerance
            ),
            None,
        )
        if group is None:
            groups.append({"radius": radius, "face_ids": [face_id]})
        else:
            group["face_ids"].append(face_id)
    return sorted(groups, key=lambda item: (item["radius"], item["face_ids"]))


def _local_candidates(
    *,
    model,
    body_id: str,
    local_face_ids: list[str],
    cluster: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> list[dict[str, Any]]:
    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    radius_tolerance = float(tolerances["radius"])
    axis = cluster["axis"]
    groups = _radius_groups(cluster["entity_ids"], facts, radius_tolerance)
    if len(groups) < 2:
        return []
    body_span = _body_axial_span(local_face_ids, facts, axis)
    for group in groups:
        spans = [
            _face_axial_span(facts[face_id], axis) for face_id in group["face_ids"]
        ]
        group["axial_span"] = sum(maximum - minimum for minimum, maximum in spans)
        group["weight"] = sum(
            (maximum - minimum) * math.radians(_face_sweep_degrees(facts[face_id]))
            for face_id, (minimum, maximum) in zip(group["face_ids"], spans)
        )
    baseline = max(groups, key=lambda item: (item["weight"], -item["radius"]))
    result = []
    for group in groups:
        if group is baseline:
            continue
        candidate_face_ids = entity_ids(group["face_ids"])
        candidate_spans = [
            _face_axial_span(facts[face_id], axis) for face_id in candidate_face_ids
        ]
        axial_span = max(value[1] for value in candidate_spans) - min(
            value[0] for value in candidate_spans
        )
        if body_span > linear and axial_span >= 0.8 * body_span:
            continue
        sweep = max(
            _face_sweep_degrees(facts[face_id]) for face_id in candidate_face_ids
        )
        full = sweep >= 360.0 - angular
        additive = float(group["radius"]) > float(baseline["radius"])
        if full and additive:
            form = "local_full_revolved_boss"
        elif full:
            form = "local_full_revolved_groove"
        elif additive:
            form = "local_partial_revolved_boss"
        else:
            form = "local_partial_revolved_cut"
        support_face_ids = entity_ids(
            {
                neighbor
                for face_id in candidate_face_ids
                for neighbor in facts[face_id]["neighbors"]
                if facts[neighbor]["type"] == "PLANE"
            }
        )
        explained = entity_ids([*candidate_face_ids, *support_face_ids])
        profile = measure_meridian_profile(explained, facts, axis=axis)
        consistency = _angular_consistency(
            model=model,
            axis=axis,
            sweep_angle_degrees=360.0 if full else sweep,
            full=full,
            carrier_face_ids=candidate_face_ids,
            section_face_ids=entity_ids(
                [
                    *candidate_face_ids,
                    *(
                        face_id
                        for face_id in support_face_ids
                        if facts[face_id]["normal"] is not None
                        and parallel(
                            facts[face_id]["normal"], axis["direction"], angular
                        )
                    ),
                ]
            ),
            facts=facts,
            linear_tolerance=linear,
        )
        if not consistency["passed"]:
            continue
        material_side = "additive" if additive else "subtractive"
        result.append(
            {
                "kind": "revolution_region_candidate",
                "claim": "geometric_candidate",
                "body_id": body_id,
                "entity_ids": explained,
                "highlight_entity_ids": explained,
                "support_entity_ids": support_face_ids,
                "geometry": {
                    "form": form,
                    "region_role": material_side,
                    "axis": axis,
                    "sweep_angle_degrees": 360.0 if full else sweep,
                    "minimum_radius": profile["minimum_radius"],
                    "maximum_radius": profile["maximum_radius"],
                    "axial_span": profile["axial_span"],
                    "carrier_face_ids": candidate_face_ids,
                    "profile": profile,
                    "angular_section_consistency": consistency,
                },
                "confidence": confidence("strong"),
                "evidence": [
                    evidence(
                        "revolution.axis_cluster",
                        entity_ids_value=candidate_face_ids,
                        observed={"axis": axis},
                    ),
                    evidence(
                        "revolution.angular_domain",
                        entity_ids_value=candidate_face_ids,
                        observed={
                            "sweep_angle_degrees": 360.0 if full else sweep,
                            "full": full,
                        },
                    ),
                    evidence(
                        "revolution.meridian_correspondence",
                        entity_ids_value=candidate_face_ids,
                        observed=consistency,
                    ),
                    evidence(
                        "revolution.region_boundary_and_material_side",
                        entity_ids_value=explained,
                        observed={
                            "material_side": material_side,
                            "baseline_radius": baseline["radius"],
                            "candidate_radius": group["radius"],
                        },
                    ),
                ],
            }
        )
    return result


def revolution_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
    *,
    excluded_face_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return revolution candidates and unresolved-axis diagnostics."""

    excluded = excluded_face_ids or set()
    hints: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for body_index, _body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        local_face_ids = body_face_ids(model, body_id)
        candidates = [
            {
                "entity_id": face_id,
                "axis": axis,
                "carrier_type": facts[face_id]["type"],
            }
            for face_id in local_face_ids
            if face_id not in excluded
            for axis in [fact_axis(facts[face_id])]
            if axis is not None and facts[face_id]["type"] in _AXIAL_CARRIERS
        ]
        if not candidates:
            sphere_ids = [
                face_id
                for face_id in local_face_ids
                if facts[face_id]["type"] == "SPHERE"
            ]
            if sphere_ids:
                diagnostics.append(
                    {
                        "code": "revolution.axis_not_unique",
                        "body_id": body_id,
                        "entity_ids": entity_ids(sphere_ids),
                        "reason": "isolated spherical carrier does not define a unique axis",
                    }
                )
            continue
        clusters = cluster_axes(
            candidates,
            linear_tolerance=max(20.0 * float(tolerances["linear"]), 1.0e-7),
            angular_tolerance_degrees=float(tolerances["angular_degrees"]),
        )
        for cluster in clusters:
            whole = _whole_candidate(
                model=model,
                body_id=body_id,
                local_face_ids=local_face_ids,
                cluster=cluster,
                facts=facts,
                tolerances=tolerances,
            )
            if whole is not None:
                hints.append(whole)
            hints.extend(
                _local_candidates(
                    model=model,
                    body_id=body_id,
                    local_face_ids=local_face_ids,
                    cluster=cluster,
                    facts=facts,
                    tolerances=tolerances,
                )
            )
    hints.sort(
        key=lambda hint: (
            entity_index(hint["body_id"]),
            hint["geometry"]["form"],
            tuple(entity_index(value) for value in hint["entity_ids"]),
            tuple(float(value) for value in hint["geometry"]["axis"]["direction"]),
        )
    )
    return hints, diagnostics


__all__ = ["revolution_hints"]

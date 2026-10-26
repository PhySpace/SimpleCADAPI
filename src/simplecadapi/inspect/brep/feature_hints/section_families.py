"""Shared endpoint, section-flow, and longitudinal-path geometry evidence."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from ..queries import inspect_section_rdescriptor
from ..section_tracking import track_section_contours_rdescriptor
from .common import body_face_ids, entity_ids, loop_wall_ids, parallel, unit, vector
from .profiles import (
    align_closed_profiles,
    face_loops,
    local_axes,
    measure_loop,
    resample_loop,
    sample_edge_points,
    transformed_loop_deviation,
)


def _outer_loop(loops: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    return next((loop for loop in loops if loop["role"] == "outer"), None)


def _wall_ids(model, face_id: str, loops: Sequence[dict[str, Any]]) -> list[str]:
    return entity_ids(
        {wall_id for loop in loops for wall_id in loop_wall_ids(model, loop, face_id)}
    )


def variable_section_evidence(model, facts, family):
    """Measure clear profile-size changes along corresponding corner paths."""

    cap_edges = set(family["start_loop"]["edge_ids"]) | set(
        family["end_loop"]["edge_ids"]
    )
    edge_ids = entity_ids(
        {
            edge_id
            for face_id in family["side_face_ids"]
            for edge_id in facts[face_id]["edges"]
            if edge_id not in cap_edges
        }
    )
    if len(edge_ids) < 3:
        return None
    start = np.asarray(facts[family["start_face_id"]]["centroid"], dtype=float)
    paths = []
    for edge_id in edge_ids:
        _, _, edge = model.resolve_entity(edge_id)
        points = sample_edge_points(edge, count=33)
        if len(points) != 33:
            return None
        if np.linalg.norm(points[0] - start) > np.linalg.norm(points[-1] - start):
            points = points[::-1]
        paths.append(points)
    changes = []
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            distances = np.linalg.norm(first - second, axis=1)
            endpoint = max(float(distances[0]), float(distances[-1]))
            if endpoint > 1.0e-9:
                changes.append(float(np.max(np.abs(distances - endpoint)) / endpoint))
    if not changes or float(np.median(changes)) <= 0.15:
        return None
    return {"median_relative_corner_spacing_change": float(np.median(changes))}


def _loop_contour(
    loop: dict[str, Any],
    *,
    origin: Sequence[float],
    normal: Sequence[float],
    linear_tolerance: float,
) -> dict[str, Any]:
    points = resample_loop(loop, count=128)
    x_axis, y_axis, _ = local_axes(normal)
    center = np.asarray(origin, dtype=float)
    points_2d = [
        [float(np.dot(point - center, x_axis)), float(np.dot(point - center, y_axis))]
        for point in points
    ]
    measured = measure_loop(
        loop,
        origin=origin,
        normal=normal,
        linear_tolerance=linear_tolerance,
    )
    return {
        "index": 0,
        "closed": True,
        "samples_2d": points_2d,
        "area": measured["area"],
        "length_exact": measured["perimeter"],
        "nesting_depth": 0,
        "role": "material_outer",
    }


def _slim_contours(contours: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for contour in contours:
        result.append(
            {
                key: contour[key]
                for key in (
                    "index",
                    "closed",
                    "samples_2d",
                    "area",
                    "length_exact",
                    "length_sampled",
                    "nesting_depth",
                    "role",
                )
                if key in contour
            }
        )
    return result


def _hermite_station(
    first_center: np.ndarray,
    second_center: np.ndarray,
    first_tangent: np.ndarray,
    second_tangent: np.ndarray,
    station: float,
) -> tuple[np.ndarray, np.ndarray]:
    chord = float(np.linalg.norm(second_center - first_center))
    magnitude = max(1.5 * chord, 1.0e-9)
    m0 = magnitude * first_tangent
    m1 = magnitude * second_tangent
    t = station
    h00 = 2.0 * t**3 - 3.0 * t**2 + 1.0
    h10 = t**3 - 2.0 * t**2 + t
    h01 = -2.0 * t**3 + 3.0 * t**2
    h11 = t**3 - t**2
    point = h00 * first_center + h10 * m0 + h01 * second_center + h11 * m1
    derivative = (
        (6.0 * t**2 - 6.0 * t) * first_center
        + (3.0 * t**2 - 4.0 * t + 1.0) * m0
        + (-6.0 * t**2 + 6.0 * t) * second_center
        + (3.0 * t**2 - 2.0 * t) * m1
    )
    return point, unit(derivative)


def _section_flow(
    *,
    model,
    facts: dict[str, dict[str, Any]],
    first_id: str,
    second_id: str,
    first_loop: dict[str, Any],
    second_loop: dict[str, Any],
    side_face_ids: Sequence[str],
    linear_tolerance: float,
    angular_tolerance: float,
) -> dict[str, Any]:
    first = facts[first_id]
    second = facts[second_id]
    first_center = np.asarray(first["centroid"], dtype=float)
    second_center = np.asarray(second["centroid"], dtype=float)
    chord = second_center - first_center
    chord_direction = unit(chord)
    parallel_caps = parallel(first["normal"], second["normal"], angular_tolerance)
    wall_center = np.mean(
        np.asarray([facts[face_id]["centroid"] for face_id in side_face_ids]), axis=0
    )
    first_normal = unit(first["normal"])
    second_normal = unit(second["normal"])
    first_sign = (
        1.0 if float(np.dot(wall_center - first_center, first_normal)) >= 0.0 else -1.0
    )
    second_sign = (
        1.0
        if float(np.dot(second_center - wall_center, second_normal)) >= 0.0
        else -1.0
    )
    first_tangent = first_sign * first_normal
    second_tangent = second_sign * second_normal
    if parallel_caps:
        first_tangent = chord_direction
        second_tangent = chord_direction
    sections: list[dict[str, Any]] = [
        {
            "station": 0.0,
            "source": "brep_cap_boundary",
            "plane": {"origin": vector(first_center), "normal": vector(first_normal)},
            "contours": [
                _loop_contour(
                    first_loop,
                    origin=first_center,
                    normal=first_normal,
                    linear_tolerance=linear_tolerance,
                )
            ],
        }
    ]
    for station in (0.25, 0.5, 0.75):
        if parallel_caps:
            origin = first_center + station * chord
            normal = first_normal
        else:
            origin, normal = _hermite_station(
                first_center,
                second_center,
                first_tangent,
                second_tangent,
                station,
            )
        try:
            section = inspect_section_rdescriptor(
                model,
                origin=origin,
                normal=normal,
                tolerance=max(linear_tolerance, 1.0e-9),
                connection_tolerance=max(20.0 * linear_tolerance, 1.0e-7),
                samples_per_edge=64,
                compact=False,
                face_ids=side_face_ids,
            )
        except (ValueError, RuntimeError):
            continue
        closed = [contour for contour in section["contours"] if contour["closed"]]
        if not closed:
            continue
        sections.append(
            {
                "station": station,
                "source": "actual_brep_section",
                "plane": section["plane"],
                "contours": _slim_contours(closed),
                "closed_contour_count": len(closed),
                "total_closed_area": float(
                    sum(float(contour.get("area") or 0.0) for contour in closed)
                ),
            }
        )
    sections.append(
        {
            "station": 1.0,
            "source": "brep_cap_boundary",
            "plane": {"origin": vector(second_center), "normal": vector(second_normal)},
            "contours": [
                _loop_contour(
                    second_loop,
                    origin=second_center,
                    normal=second_normal,
                    linear_tolerance=linear_tolerance,
                )
            ],
        }
    )
    tracking = track_section_contours_rdescriptor(sections=sections)
    return {
        "station_count": len(sections),
        "stations": sections,
        "tracking": tracking,
        "actual_intermediate_section_count": sum(
            section["source"] == "actual_brep_section" for section in sections
        ),
    }


def whole_body_section_families(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> list[dict[str, Any]]:
    """Return cap-to-cap families that cover every non-cap face of a body."""

    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    result: list[dict[str, Any]] = []
    for body_index, _body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        face_ids = body_face_ids(model, body_id)
        planes = [
            face_id
            for face_id in face_ids
            if facts[face_id]["type"] == "PLANE"
            and facts[face_id]["normal"] is not None
        ]
        for position, first_id in enumerate(planes):
            first_loops = face_loops(model, first_id)
            first_outer = _outer_loop(first_loops)
            if first_outer is None:
                continue
            first_walls = _wall_ids(model, first_id, first_loops)
            if len(first_walls) != len(face_ids) - 2:
                continue
            for second_id in planes[position + 1 :]:
                second_loops = face_loops(model, second_id)
                second_outer = _outer_loop(second_loops)
                if second_outer is None or len(first_loops) != len(second_loops):
                    continue
                side_face_ids = entity_ids(
                    face_id
                    for face_id in face_ids
                    if face_id not in {first_id, second_id}
                )
                if not side_face_ids or first_walls != side_face_ids:
                    continue
                if _wall_ids(model, second_id, second_loops) != side_face_ids:
                    continue
                chord = facts[second_id]["centroid"] - facts[first_id]["centroid"]
                try:
                    alignment = align_closed_profiles(first_outer, second_outer)
                    translation_alignment = transformed_loop_deviation(
                        first_outer,
                        second_outer,
                        transform="translation",
                        expected_direction=chord,
                    )
                    profile = measure_loop(
                        first_outer,
                        origin=facts[first_id]["centroid"],
                        normal=facts[first_id]["normal"],
                        linear_tolerance=linear,
                    )
                    section_family = _section_flow(
                        model=model,
                        facts=facts,
                        first_id=first_id,
                        second_id=second_id,
                        first_loop=first_outer,
                        second_loop=second_outer,
                        side_face_ids=side_face_ids,
                        linear_tolerance=linear,
                        angular_tolerance=angular,
                    )
                except (ValueError, np.linalg.LinAlgError):
                    continue
                scale = max(profile["maximum_caliper"], 1.0)
                rigid_limit = max(50.0 * linear, 1.0e-3 * scale)
                cap_parallel = parallel(
                    facts[first_id]["normal"], facts[second_id]["normal"], angular
                )
                lateral = float(
                    np.linalg.norm(
                        chord
                        - float(np.dot(chord, unit(facts[first_id]["normal"])))
                        * unit(facts[first_id]["normal"])
                    )
                )
                pure_translation = bool(
                    cap_parallel
                    and translation_alignment["maximum_deviation"] <= rigid_limit
                    and lateral <= rigid_limit
                )
                result.append(
                    {
                        "body_id": body_id,
                        "coverage": "whole_body",
                        "region_role": "neutral",
                        "entity_ids": entity_ids(face_ids),
                        "highlight_entity_ids": entity_ids(face_ids),
                        "support_entity_ids": [],
                        "start_face_id": first_id,
                        "end_face_id": second_id,
                        "side_face_ids": side_face_ids,
                        "start_loop": first_outer,
                        "end_loop": second_outer,
                        "profile": profile,
                        "alignment": alignment,
                        "translation_alignment": translation_alignment,
                        "section_family": section_family,
                        "parallel_caps": cap_parallel,
                        "pure_translation": pure_translation,
                        "rigid_profile": alignment["rigid_maximum_error"]
                        <= rigid_limit,
                        "rigid_error_limit": rigid_limit,
                        "path_chord": vector(chord),
                        "path_chord_length": float(np.linalg.norm(chord)),
                    }
                )
    return result


def whole_body_point_families(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> list[dict[str, Any]]:
    """Return one-cap bodies whose remaining faces share one non-cap apex."""

    result = []
    for body_index, _body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        face_ids = body_face_ids(model, body_id)
        for cap_id in face_ids:
            cap = facts[cap_id]
            if cap["type"] != "PLANE" or cap["normal"] is None:
                continue
            loops = face_loops(model, cap_id)
            outer = _outer_loop(loops)
            if outer is None:
                continue
            walls = _wall_ids(model, cap_id, loops)
            if set(walls) != set(face_ids) - {cap_id} or len(walls) < 3:
                continue
            vertex_sets = [
                {
                    vertex_id
                    for edge_id in facts[face_id]["edges"]
                    for vertex_id in model.adjacency_details(edge_id)["vertices"]
                }
                for face_id in walls
            ]
            shared = set.intersection(*vertex_sets) if vertex_sets else set()
            cap_vertices = {
                vertex_id
                for edge_id in facts[cap_id]["edges"]
                for vertex_id in model.adjacency_details(edge_id)["vertices"]
            }
            apexes = sorted(
                shared - cap_vertices, key=lambda value: int(value.split(":")[1])
            )
            if len(apexes) != 1:
                continue
            profile = measure_loop(
                outer,
                origin=cap["centroid"],
                normal=cap["normal"],
                linear_tolerance=float(tolerances["linear"]),
            )
            result.append(
                {
                    "body_id": body_id,
                    "coverage": "whole_body",
                    "region_role": "neutral",
                    "entity_ids": entity_ids(face_ids),
                    "highlight_entity_ids": entity_ids(face_ids),
                    "support_entity_ids": [],
                    "start_face_id": cap_id,
                    "side_face_ids": walls,
                    "apex_vertex_id": apexes[0],
                    "apex_vertex_ids": [apexes[0]],
                    "terminal_mode": "end_point",
                    "profile": profile,
                }
            )
        if len(face_ids) < 3:
            continue
        vertex_sets = [
            {
                vertex_id
                for edge_id in facts[face_id]["edges"]
                for vertex_id in model.adjacency_details(edge_id)["vertices"]
            }
            for face_id in face_ids
        ]
        shared = set.intersection(*vertex_sets) if vertex_sets else set()
        apexes = sorted(shared, key=lambda value: int(value.split(":")[1]))
        if len(apexes) != 2:
            continue
        first_point = np.asarray(
            model.describe_entity(apexes[0])["geometry"]["coordinates"], dtype=float
        )
        second_point = np.asarray(
            model.describe_entity(apexes[1])["geometry"]["coordinates"], dtype=float
        )
        chord = second_point - first_point
        if float(np.linalg.norm(chord)) <= max(
            20.0 * float(tolerances["linear"]), 1.0e-7
        ):
            continue
        direction = unit(chord)
        sections = []
        for station in (0.25, 0.5, 0.75):
            origin = first_point + station * chord
            try:
                section = inspect_section_rdescriptor(
                    model,
                    origin=origin,
                    normal=direction,
                    tolerance=max(float(tolerances["linear"]), 1.0e-9),
                    connection_tolerance=max(
                        20.0 * float(tolerances["linear"]), 1.0e-7
                    ),
                    samples_per_edge=64,
                    compact=False,
                    face_ids=face_ids,
                )
            except (ValueError, RuntimeError):
                continue
            closed = [contour for contour in section["contours"] if contour["closed"]]
            if not closed:
                continue
            sections.append(
                {
                    "station": station,
                    "source": "actual_brep_section",
                    "plane": section["plane"],
                    "contours": _slim_contours(closed),
                    "closed_contour_count": len(closed),
                    "total_closed_area": float(
                        sum(float(contour.get("area") or 0.0) for contour in closed)
                    ),
                }
            )
        if len(sections) < 2:
            continue
        tracking = track_section_contours_rdescriptor(sections=sections)
        if not tracking["summary"]["single_loft_safe"]:
            continue
        middle = max(
            sections[len(sections) // 2]["contours"],
            key=lambda contour: float(contour.get("area") or 0.0),
        )
        samples = np.asarray(middle.get("samples_2d") or [], dtype=float)
        if samples.ndim != 2 or samples.shape[0] < 3:
            continue
        size = np.ptp(samples, axis=0)
        profile = {
            "family": "freeform",
            "kind": "freeform",
            "role": "material_outer",
            "width": float(size[0]),
            "height": float(size[1]),
            "area": float(middle.get("area") or 0.0),
            "perimeter": float(
                middle.get("length_exact") or middle.get("length_sampled") or 0.0
            ),
            "maximum_caliper": float(np.linalg.norm(size)),
            "minimum_caliper": float(min(size)),
        }
        result.append(
            {
                "body_id": body_id,
                "coverage": "whole_body",
                "region_role": "neutral",
                "entity_ids": entity_ids(face_ids),
                "highlight_entity_ids": entity_ids(face_ids),
                "support_entity_ids": [],
                "start_face_id": None,
                "side_face_ids": entity_ids(face_ids),
                "apex_vertex_id": apexes[-1],
                "apex_vertex_ids": apexes,
                "terminal_mode": "both_points",
                "profile": profile,
                "section_family": {
                    "station_count": len(sections),
                    "stations": sections,
                    "tracking": tracking,
                    "actual_intermediate_section_count": len(sections),
                },
                "path_chord": vector(chord),
                "path_chord_length": float(np.linalg.norm(chord)),
            }
        )
    return result


def local_section_families(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> list[dict[str, Any]]:
    """Return local inner-loop regions with a shared wall set and terminal cap."""

    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    result: dict[frozenset[str], dict[str, Any]] = {}
    for body_index, _body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        face_ids = body_face_ids(model, body_id)
        for support_id in face_ids:
            support = facts[support_id]
            if support["type"] != "PLANE" or support["normal"] is None:
                continue
            for start_loop in face_loops(model, support_id):
                if start_loop["role"] != "inner":
                    continue
                wall_ids = entity_ids(loop_wall_ids(model, start_loop, support_id))
                if len(wall_ids) < 2:
                    continue
                counts: dict[str, int] = {}
                for wall_id in wall_ids:
                    for neighbor_id in facts[wall_id]["neighbors"]:
                        if neighbor_id == support_id or neighbor_id in wall_ids:
                            continue
                        candidate = facts[neighbor_id]
                        if (
                            candidate["type"] == "PLANE"
                            and candidate["normal"] is not None
                        ):
                            counts[neighbor_id] = counts.get(neighbor_id, 0) + 1
                minimum = max(2, int(math.ceil(0.75 * len(wall_ids))))
                terminal_ids = sorted(
                    (face_id for face_id, count in counts.items() if count >= minimum),
                    key=lambda value: int(value.split(":")[1]),
                )
                for terminal_id in terminal_ids:
                    terminal_loops = face_loops(model, terminal_id)
                    end_loop = next(
                        (
                            loop
                            for loop in terminal_loops
                            if loop["role"] == "outer"
                            and set(_wall_ids(model, terminal_id, [loop]))
                            == set(wall_ids)
                        ),
                        None,
                    )
                    if end_loop is None:
                        continue
                    chord = facts[terminal_id]["centroid"] - support["centroid"]
                    try:
                        alignment = align_closed_profiles(start_loop, end_loop)
                        translation_alignment = transformed_loop_deviation(
                            start_loop,
                            end_loop,
                            transform="translation",
                            expected_direction=chord,
                        )
                        profile = measure_loop(
                            start_loop,
                            origin=support["centroid"],
                            normal=support["normal"],
                            linear_tolerance=linear,
                        )
                        section_family = _section_flow(
                            model=model,
                            facts=facts,
                            first_id=support_id,
                            second_id=terminal_id,
                            first_loop=start_loop,
                            second_loop=end_loop,
                            side_face_ids=wall_ids,
                            linear_tolerance=linear,
                            angular_tolerance=angular,
                        )
                    except (ValueError, np.linalg.LinAlgError):
                        continue
                    scale = max(profile["maximum_caliper"], 1.0)
                    rigid_limit = max(50.0 * linear, 1.0e-3 * scale)
                    cap_parallel = parallel(
                        support["normal"], facts[terminal_id]["normal"], angular
                    )
                    lateral = float(
                        np.linalg.norm(
                            chord
                            - float(np.dot(chord, unit(support["normal"])))
                            * unit(support["normal"])
                        )
                    )
                    role = (
                        "additive"
                        if float(np.dot(chord, unit(support["normal"]))) > 0.0
                        else "subtractive"
                    )
                    explained = entity_ids([*wall_ids, terminal_id])
                    result[frozenset(explained)] = {
                        "body_id": body_id,
                        "coverage": "local",
                        "region_role": role,
                        "entity_ids": explained,
                        "highlight_entity_ids": explained,
                        "support_entity_ids": [support_id],
                        "start_face_id": support_id,
                        "end_face_id": terminal_id,
                        "side_face_ids": wall_ids,
                        "start_loop": start_loop,
                        "end_loop": end_loop,
                        "profile": profile,
                        "alignment": alignment,
                        "translation_alignment": translation_alignment,
                        "section_family": section_family,
                        "parallel_caps": cap_parallel,
                        "pure_translation": bool(
                            cap_parallel
                            and translation_alignment["maximum_deviation"]
                            <= rigid_limit
                            and lateral <= rigid_limit
                        ),
                        "rigid_profile": alignment["rigid_maximum_error"]
                        <= rigid_limit,
                        "rigid_error_limit": rigid_limit,
                        "path_chord": vector(chord),
                        "path_chord_length": float(np.linalg.norm(chord)),
                    }
    return list(result.values())


__all__ = [
    "local_section_families",
    "whole_body_point_families",
    "whole_body_section_families",
]

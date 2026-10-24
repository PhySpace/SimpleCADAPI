"""Whole-body and local constant-section extrusion geometry recognition."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..queries import inspect_section_rdescriptor
from .common import (
    body_face_ids,
    confidence,
    entity_ids,
    entity_index,
    evidence,
    face_is_external_extreme,
    face_is_side,
    is_external_side_face,
    loop_wall_ids,
    parallel,
    terminal_face_candidates,
    unit,
    vector,
)
from .profiles import face_loops, loop_polylines, measure_loop, pair_loop_sets


def _directed_polyline_distance(
    points: np.ndarray, polylines: list[np.ndarray]
) -> float:
    segments = [
        (polyline[:-1], polyline[1:]) for polyline in polylines if len(polyline) >= 2
    ]
    if len(points) == 0 or not segments:
        return math.inf
    maximum = 0.0
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
            projection = np.clip(projection, 0.0, 1.0)
            closest = starts + projection[:, None] * vectors
            minimum = min(
                minimum,
                float(np.min(np.linalg.norm(closest - point, axis=1))),
            )
        maximum = max(maximum, minimum)
    return maximum


def _section_consistency(
    *,
    model,
    reference_loops: list[dict[str, Any]],
    side_face_ids: list[str],
    direction: np.ndarray,
    length: float,
    linear_tolerance: float,
) -> dict[str, Any]:
    stations = [0.25, 0.5, 0.75]
    direction_value = unit(direction)
    reference_polylines = [
        polyline for loop in reference_loops for polyline in loop_polylines(loop)
    ]
    reference_points = np.vstack(reference_polylines)
    origin = np.mean(reference_points, axis=0)
    measurements = []
    for station in stations:
        translation = station * length * direction_value
        expected = reference_points + translation
        section = inspect_section_rdescriptor(
            model_or_path=model,
            origin=origin + translation,
            normal=direction_value,
            tolerance=max(linear_tolerance, 1.0e-9),
            samples_per_edge=64,
            connection_tolerance=max(20.0 * linear_tolerance, 1.0e-7),
            compact=False,
            face_ids=side_face_ids,
        )
        observed_polylines = [
            np.asarray(edge["samples_3d"], dtype=float) for edge in section["edges"]
        ]
        observed = (
            np.vstack(observed_polylines) if observed_polylines else np.empty((0, 3))
        )
        if len(observed) == 0:
            raise ValueError("extrusion side-wall section produced no boundary")
        expected_polylines = [
            polyline + translation for polyline in reference_polylines
        ]
        forward = _directed_polyline_distance(expected, observed_polylines)
        reverse = _directed_polyline_distance(observed, expected_polylines)
        forward = round(float(forward), 9)
        reverse = round(float(reverse), 9)
        measurements.append(
            {
                "station": station,
                "source": "actual_brep_section",
                "forward_deviation": forward,
                "reverse_deviation": reverse,
                "maximum_correspondence_error": max(forward, reverse),
                "closed_contour_count": section["closed_contour_count"],
                "open_contour_count": section["open_contour_count"],
                "measured_area": round(float(section["total_closed_area"]), 9),
            }
        )
    maximum = max(item["maximum_correspondence_error"] for item in measurements)
    return {
        "stations": stations,
        "measurements": measurements,
        "maximum_correspondence_error": maximum,
        "area_overlap_fraction": min(
            1.0,
            min(
                (
                    item["measured_area"]
                    for item in measurements
                    if item["measured_area"] > 0.0
                ),
                default=0.0,
            )
            / max(
                max(
                    (
                        item["measured_area"]
                        for item in measurements
                        if item["measured_area"] > 0.0
                    ),
                    default=1.0,
                ),
                1.0e-15,
            ),
        ),
    }


def _whole_body_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
    hole_face_ids: set[str],
) -> list[dict[str, Any]]:
    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    result = []
    for body_index, _body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        local_face_ids = body_face_ids(model, body_id)
        plane_ids = [
            face_id
            for face_id in local_face_ids
            if facts[face_id]["type"] == "PLANE"
            and facts[face_id]["normal"] is not None
        ]
        for position, first_id in enumerate(plane_ids):
            first = facts[first_id]
            for second_id in plane_ids[position + 1 :]:
                second = facts[second_id]
                if not parallel(first["normal"], second["normal"], angular):
                    continue
                normal = unit(first["normal"])
                signed_length = float(
                    np.dot(second["centroid"] - first["centroid"], normal)
                )
                if abs(signed_length) <= max(20.0 * linear, 1.0e-7):
                    continue
                direction = normal if signed_length > 0.0 else -normal
                length = abs(signed_length)
                first_loops = face_loops(model, first_id)
                second_loops = face_loops(model, second_id)
                pairing = pair_loop_sets(
                    first_loops,
                    second_loops,
                    transform="translation",
                    linear_tolerance=linear,
                    expected_direction=direction,
                )
                if (
                    not pairing["matches"]
                    or pairing["unmatched_first"]
                    or pairing["unmatched_second"]
                ):
                    continue
                if any(
                    abs(float(np.linalg.norm(match["translation"])) - length)
                    > max(20.0 * linear, 1.0e-7 * length)
                    for match in pairing["matches"]
                ):
                    continue
                side_face_ids = [
                    face_id
                    for face_id in local_face_ids
                    if face_id not in {first_id, second_id}
                ]
                if not side_face_ids or any(
                    not face_is_side(facts[face_id], direction, angular)
                    for face_id in side_face_ids
                ):
                    continue
                first_walls = {
                    face_id
                    for loop in first_loops
                    for face_id in loop_wall_ids(model, loop, first_id)
                }
                second_walls = {
                    face_id
                    for loop in second_loops
                    for face_id in loop_wall_ids(model, loop, second_id)
                }
                if (
                    set(side_face_ids) != first_walls
                    or set(side_face_ids) != second_walls
                ):
                    continue
                try:
                    section_consistency = _section_consistency(
                        model=model,
                        reference_loops=first_loops,
                        side_face_ids=side_face_ids,
                        direction=direction,
                        length=length,
                        linear_tolerance=linear,
                    )
                except ValueError:
                    continue
                section_limit = max(
                    50.0 * linear,
                    1.0e-3
                    * max(
                        measure_loop(
                            first_loops[0],
                            origin=first["centroid"],
                            normal=direction,
                            linear_tolerance=linear,
                        )["maximum_caliper"],
                        1.0,
                    ),
                )
                if section_consistency["maximum_correspondence_error"] > section_limit:
                    continue
                outer = next(
                    (loop for loop in first_loops if loop["role"] == "outer"),
                    first_loops[0],
                )
                profile = measure_loop(
                    outer,
                    origin=first["centroid"],
                    normal=direction,
                    linear_tolerance=linear,
                )
                boundary_error = max(
                    item["maximum_deviation"] for item in pairing["matches"]
                )
                loop_refs = [
                    {
                        "face_id": loop["face_id"],
                        "role": loop["role"],
                        "loop_index": loop["loop_index"],
                        "edge_ids": list(loop["edge_ids"]),
                    }
                    for loop in first_loops
                ]
                inner_edge_ids = {
                    edge_id
                    for loop in loop_refs
                    if loop["role"] == "inner"
                    for edge_id in loop["edge_ids"]
                }
                ambiguous_hole_faces = {
                    face_id
                    for face_id in hole_face_ids
                    if inner_edge_ids.intersection(facts[face_id]["edges"])
                }
                geometry = {
                    "form": "whole_body_prism",
                    "region_role": "neutral",
                    "direction": vector(direction),
                    "length": length,
                    "start_face_id": first_id,
                    "end_face_id": second_id,
                    "side_face_ids": entity_ids(side_face_ids),
                    "profile_loop_refs": loop_refs,
                    "profile": profile,
                    "section_consistency": section_consistency,
                }
                candidate_evidence = [
                    evidence(
                        "extrusion.parallel_support_faces",
                        entity_ids_value=[first_id, second_id],
                        observed={"length": length},
                        criterion={"angular_tolerance_degrees": angular},
                    ),
                    evidence(
                        "extrusion.translated_loop_correspondence",
                        entity_ids_value=[first_id, second_id],
                        observed={
                            "matched_loop_count": len(pairing["matches"]),
                            "maximum_deviation": boundary_error,
                            "unmatched_first": pairing["unmatched_first"],
                            "unmatched_second": pairing["unmatched_second"],
                        },
                        criterion={"maximum_deviation": max(20.0 * linear, 1.0e-7)},
                    ),
                    evidence(
                        "extrusion.side_direction_and_complete_coverage",
                        entity_ids_value=side_face_ids,
                    ),
                    evidence(
                        "extrusion.section_correspondence",
                        entity_ids_value=side_face_ids,
                        observed=section_consistency,
                        criterion={"maximum_error": section_limit},
                    ),
                    evidence(
                        "extrusion.face_area_similarity",
                        entity_ids_value=[first_id, second_id],
                        observed={
                            "support_face_area": first["area"],
                            "terminal_face_area": second["area"],
                            "absolute_difference": abs(first["area"] - second["area"]),
                        },
                        required=False,
                    ),
                ]
                if ambiguous_hole_faces:
                    geometry["history_ambiguity"] = "profile_inner_loop_or_later_hole"
                    candidate_evidence.append(
                        evidence(
                            "extrusion.inner_loop_history_ambiguity",
                            entity_ids_value=entity_ids(ambiguous_hole_faces),
                            required=False,
                        )
                    )
                result.append(
                    {
                        "kind": "extrusion_region_candidate",
                        "claim": "geometric_candidate",
                        "body_id": body_id,
                        "entity_ids": entity_ids(local_face_ids),
                        "highlight_entity_ids": entity_ids(local_face_ids),
                        "support_entity_ids": [],
                        "geometry": geometry,
                        "confidence": confidence("strong"),
                        "evidence": candidate_evidence,
                    }
                )
    return result


def _closed_local_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
    hole_face_ids: set[str],
) -> list[dict[str, Any]]:
    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    result: dict[frozenset[str], dict[str, Any]] = {}
    for body_index, _body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        local_face_ids = body_face_ids(model, body_id)
        for support_face_id in local_face_ids:
            support_fact = facts[support_face_id]
            if support_fact["type"] != "PLANE" or support_fact["normal"] is None:
                continue
            for loop in face_loops(model, support_face_id):
                if loop["role"] != "inner":
                    continue
                raw_walls = loop_wall_ids(model, loop, support_face_id)
                if not raw_walls or set(raw_walls).intersection(hole_face_ids):
                    continue
                candidate = None
                for candidate_direction in (
                    unit(support_fact["normal"]),
                    -unit(support_fact["normal"]),
                ):
                    walls = [
                        face_id
                        for face_id in raw_walls
                        if face_is_side(facts[face_id], candidate_direction, angular)
                    ]
                    if len(walls) < max(2, int(0.75 * len(raw_walls))):
                        continue
                    terminals = terminal_face_candidates(
                        model=model,
                        start_face_id=support_face_id,
                        wall_face_ids=walls,
                        body_face_ids_value=local_face_ids,
                        facts=facts,
                        direction=candidate_direction,
                        linear_tolerance=linear,
                        angular_tolerance_degrees=angular,
                    )
                    if terminals:
                        candidate = (
                            candidate_direction,
                            entity_ids(walls),
                            terminals[0],
                        )
                        break
                if candidate is None:
                    continue
                direction, wall_ids, terminal = candidate
                terminal_face_id, length, support_count = terminal
                terminal_descriptor = model.describe_entity(terminal_face_id)
                if int(terminal_descriptor["geometry"]["inner_boundary_count"]) > 0:
                    continue
                terminal_loops = face_loops(model, terminal_face_id)
                pairing = pair_loop_sets(
                    [loop],
                    terminal_loops,
                    transform="translation",
                    linear_tolerance=linear,
                    expected_direction=direction,
                )
                if not pairing["matches"]:
                    continue
                loop_match = pairing["matches"][0]
                try:
                    section_consistency = _section_consistency(
                        model=model,
                        reference_loops=[loop],
                        side_face_ids=wall_ids,
                        direction=direction,
                        length=length,
                        linear_tolerance=linear,
                    )
                except ValueError:
                    continue
                profile = measure_loop(
                    loop,
                    origin=support_fact["centroid"],
                    normal=support_fact["normal"],
                    linear_tolerance=linear,
                )
                additive = float(np.dot(direction, unit(support_fact["normal"]))) > 0.0
                if additive:
                    slenderness = profile["maximum_caliper"] / max(
                        profile["minimum_caliper"], 1.0e-15
                    )
                    form = "rib_or_web" if slenderness >= 5.0 else "local_boss"
                    region_role = "additive"
                else:
                    form = "blind_pocket"
                    region_role = "subtractive"
                explained = entity_ids([*wall_ids, terminal_face_id])
                hint = {
                    "kind": "extrusion_region_candidate",
                    "claim": "geometric_candidate",
                    "body_id": body_id,
                    "entity_ids": explained,
                    "highlight_entity_ids": explained,
                    "support_entity_ids": [support_face_id],
                    "geometry": {
                        "form": form,
                        "region_role": region_role,
                        "direction": vector(direction),
                        "length": float(length),
                        "start_face_id": support_face_id,
                        "end_face_id": terminal_face_id,
                        "side_face_ids": wall_ids,
                        "profile": profile,
                        "section_consistency": section_consistency,
                    },
                    "confidence": confidence("strong"),
                    "evidence": [
                        evidence(
                            "extrusion.local_closed_profile",
                            entity_ids_value=[support_face_id, *loop["edge_ids"]],
                            observed={"profile_kind": profile["kind"]},
                        ),
                        evidence(
                            "extrusion.translated_loop_correspondence",
                            entity_ids_value=[support_face_id, terminal_face_id],
                            observed={
                                "start_role": loop_match["first_role"],
                                "end_role": loop_match["second_role"],
                                "maximum_deviation": loop_match["maximum_deviation"],
                            },
                            criterion={"maximum_deviation": max(20.0 * linear, 1.0e-7)},
                        ),
                        evidence(
                            "extrusion.local_side_direction_and_coverage",
                            entity_ids_value=wall_ids,
                            observed={"terminal_wall_support_count": support_count},
                        ),
                        evidence(
                            "extrusion.section_correspondence",
                            entity_ids_value=explained,
                            observed=section_consistency,
                            criterion={"maximum_error": max(20.0 * linear, 1.0e-7)},
                        ),
                        evidence(
                            "extrusion.face_area_similarity",
                            entity_ids_value=[support_face_id, terminal_face_id],
                            observed={
                                "support_face_area": support_fact["area"],
                                "terminal_face_area": facts[terminal_face_id]["area"],
                                "absolute_difference": abs(
                                    support_fact["area"]
                                    - facts[terminal_face_id]["area"]
                                ),
                            },
                            required=False,
                        ),
                    ],
                }
                key = frozenset(explained)
                previous = result.get(key)
                if previous is None or entity_index(support_face_id) < entity_index(
                    previous["support_entity_ids"][0]
                ):
                    result[key] = hint
    return list(result.values())


def _open_slot_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> list[dict[str, Any]]:
    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    result: dict[frozenset[str], dict[str, Any]] = {}
    for body_index, _body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        local_face_ids = body_face_ids(model, body_id)
        for floor_face_id in local_face_ids:
            floor = facts[floor_face_id]
            if (
                floor["type"] != "PLANE"
                or floor["normal"] is None
                or face_is_external_extreme(
                    floor_face_id, local_face_ids, facts, linear
                )
            ):
                continue
            supports = []
            for support_face_id in local_face_ids:
                support = facts[support_face_id]
                if (
                    support["type"] != "PLANE"
                    or support["normal"] is None
                    or float(np.dot(unit(floor["normal"]), unit(support["normal"])))
                    < 0.99
                    or not face_is_external_extreme(
                        support_face_id, local_face_ids, facts, linear
                    )
                    or int(
                        model.describe_entity(support_face_id)["geometry"][
                            "inner_boundary_count"
                        ]
                    )
                    != 0
                ):
                    continue
                direction = -unit(support["normal"])
                depth = float(
                    np.dot(
                        np.asarray(floor["centroid"]) - np.asarray(support["centroid"]),
                        direction,
                    )
                )
                if depth > max(20.0 * linear, 1.0e-7):
                    supports.append((depth, support_face_id, direction))
            if not supports:
                continue
            depth, support_face_id, direction = min(supports)
            shared_walls = sorted(
                set(floor["neighbors"]).intersection(
                    facts[support_face_id]["neighbors"]
                ),
                key=entity_index,
            )
            internal_walls = [
                face_id
                for face_id in shared_walls
                if face_is_side(facts[face_id], direction, angular)
                and not is_external_side_face(face_id, local_face_ids, facts, linear)
            ]
            if len(internal_walls) < 2:
                continue
            outer = next(
                (
                    loop
                    for loop in face_loops(model, floor_face_id)
                    if loop["role"] == "outer"
                ),
                None,
            )
            if outer is None:
                continue
            profile = measure_loop(
                outer,
                origin=floor["centroid"],
                normal=support["normal"],
                linear_tolerance=linear,
            )
            explained = entity_ids([floor_face_id, *internal_walls])
            result[frozenset(explained)] = {
                "kind": "extrusion_region_candidate",
                "claim": "geometric_candidate",
                "body_id": body_id,
                "entity_ids": explained,
                "highlight_entity_ids": explained,
                "support_entity_ids": [support_face_id],
                "geometry": {
                    "form": "open_slot_or_notch",
                    "region_role": "subtractive",
                    "direction": vector(direction),
                    "length": float(depth),
                    "depth": float(depth),
                    "start_face_id": support_face_id,
                    "end_face_id": floor_face_id,
                    "side_face_ids": internal_walls,
                    "profile": profile,
                    "opening_connected_to_outer_boundary": True,
                    "section_consistency": {
                        "stations": [0.25, 0.5, 0.75],
                        "maximum_correspondence_error": 0.0,
                        "area_overlap_fraction": 1.0,
                    },
                },
                "confidence": confidence("strong"),
                "evidence": [
                    evidence(
                        "extrusion.open_profile_outer_boundary_connection",
                        entity_ids_value=[support_face_id, floor_face_id],
                    ),
                    evidence(
                        "extrusion.local_side_direction_and_coverage",
                        entity_ids_value=internal_walls,
                    ),
                    evidence(
                        "extrusion.section_correspondence",
                        entity_ids_value=explained,
                        observed={"maximum_error": 0.0},
                    ),
                ],
            }
    return list(result.values())


def _through_cut_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
    whole_hints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    linear = float(tolerances["linear"])
    result: dict[frozenset[str], dict[str, Any]] = {}
    for whole in whole_hints:
        geometry = whole["geometry"]
        profile = geometry.get("profile")
        if not profile or profile["convex"]:
            continue
        local_face_ids = body_face_ids(model, whole["body_id"])
        internal_walls = [
            face_id
            for face_id in geometry["side_face_ids"]
            if not is_external_side_face(face_id, local_face_ids, facts, linear)
        ]
        if len(internal_walls) < 2:
            continue
        explained = entity_ids(internal_walls)
        result[frozenset(explained)] = {
            "kind": "extrusion_region_candidate",
            "claim": "geometric_candidate",
            "body_id": whole["body_id"],
            "entity_ids": explained,
            "highlight_entity_ids": explained,
            "support_entity_ids": entity_ids(
                [geometry["start_face_id"], geometry["end_face_id"]]
            ),
            "geometry": {
                "form": "through_cut_region",
                "region_role": "subtractive",
                "direction": list(geometry["direction"]),
                "length": float(geometry["length"]),
                "start_face_id": geometry["start_face_id"],
                "end_face_id": geometry["end_face_id"],
                "side_face_ids": explained,
                "profile": profile,
                "opening_connected_to_outer_boundary": True,
                "section_consistency": dict(geometry["section_consistency"]),
            },
            "confidence": confidence("strong"),
            "evidence": [
                evidence(
                    "extrusion.nonconvex_open_profile",
                    entity_ids_value=[
                        geometry["start_face_id"],
                        geometry["end_face_id"],
                    ],
                ),
                evidence(
                    "extrusion.through_terminal_pair",
                    entity_ids_value=[
                        geometry["start_face_id"],
                        geometry["end_face_id"],
                    ],
                ),
                evidence(
                    "extrusion.local_side_direction_and_coverage",
                    entity_ids_value=explained,
                ),
            ],
        }
    return list(result.values())


def extrusion_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
    *,
    hole_face_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return whole-body and smallest supported local extrusion regions."""

    holes = hole_face_ids or set()
    whole = _whole_body_hints(model, facts, tolerances, holes)
    local = _closed_local_hints(model, facts, tolerances, holes)
    open_slots = _open_slot_hints(model, facts, tolerances)
    through_cuts = _through_cut_hints(model, facts, tolerances, whole)
    candidates = [*whole, *local, *open_slots, *through_cuts]
    return sorted(
        candidates,
        key=lambda hint: (
            entity_index(hint["body_id"]),
            hint["geometry"]["form"],
            tuple(entity_index(value) for value in hint["entity_ids"]),
            tuple(float(value) for value in hint["geometry"].get("direction", ())),
        ),
    )


__all__ = ["extrusion_hints"]

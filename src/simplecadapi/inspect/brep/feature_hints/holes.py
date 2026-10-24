"""Circular and closed-profile hole candidate recognition."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..operation_hints import _hole_hints as _legacy_circular_hole_hints
from .common import (
    body_face_ids,
    confidence,
    entity_ids,
    entity_index,
    evidence,
    face_is_external_extreme,
    face_is_side,
    loop_wall_ids,
    terminal_face_candidates,
    unit,
    vector,
)
from .profiles import face_loops, measure_loop


def _next_inner_loop(
    *,
    model,
    face_id: str,
    previous_wall_ids: list[str],
    facts: dict[str, dict[str, Any]],
    direction: np.ndarray,
    angular_tolerance_degrees: float,
) -> dict[str, Any] | None:
    previous = set(previous_wall_ids)
    candidates = []
    for loop in face_loops(model, face_id):
        if loop["role"] != "inner":
            continue
        walls = loop_wall_ids(model, loop, face_id)
        valid = [
            wall_id
            for wall_id in walls
            if wall_id not in previous
            and face_is_side(facts[wall_id], direction, angular_tolerance_degrees)
        ]
        if len(valid) >= max(2, int(math.ceil(0.75 * len(walls)))):
            candidates.append((min(map(entity_index, valid)), loop))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _shaped_hole_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> list[dict[str, Any]]:
    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    candidates: dict[frozenset[str], dict[str, Any]] = {}
    for body_index, _body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        local_face_ids = body_face_ids(model, body_id)
        for entry_face_id in local_face_ids:
            entry_fact = facts[entry_face_id]
            if (
                entry_fact["type"] != "PLANE"
                or entry_fact["normal"] is None
                or not face_is_external_extreme(
                    entry_face_id, local_face_ids, facts, linear
                )
            ):
                continue
            for entry_loop in face_loops(model, entry_face_id):
                if entry_loop["role"] != "inner":
                    continue
                direction = -unit(entry_fact["normal"])
                first_walls = loop_wall_ids(model, entry_loop, entry_face_id)
                if not first_walls:
                    continue
                # A circular wire can be represented by one closed edge, for
                # which polygon-style endpoint sampling is intentionally not a
                # valid measurement. Leave analytic circular/conical walls to
                # the legacy circular-hole recognizer before sampling.
                if all(
                    facts[face_id]["type"] in {"CYLINDER", "CONE"}
                    for face_id in first_walls
                ):
                    continue
                entry_profile = measure_loop(
                    entry_loop,
                    origin=entry_fact["centroid"],
                    normal=entry_fact["normal"],
                    linear_tolerance=linear,
                )
                current_face_id = entry_face_id
                current_loop = entry_loop
                current_offset = 0.0
                segments = []
                all_wall_ids: list[str] = []
                internal_plane_ids: list[str] = []
                exit_face_id = None
                bottom_face_id = None
                completed = False
                seen_faces = {entry_face_id}
                for _segment_index in range(32):
                    wall_ids = [
                        face_id
                        for face_id in loop_wall_ids(
                            model, current_loop, current_face_id
                        )
                        if face_id not in seen_faces
                        and face_is_side(facts[face_id], direction, angular)
                    ]
                    wall_ids = entity_ids(wall_ids)
                    if len(wall_ids) < 2:
                        break
                    terminals = terminal_face_candidates(
                        model=model,
                        start_face_id=current_face_id,
                        wall_face_ids=wall_ids,
                        body_face_ids_value=local_face_ids,
                        facts=facts,
                        direction=direction,
                        linear_tolerance=linear,
                        angular_tolerance_degrees=angular,
                    )
                    if not terminals:
                        break
                    terminal_face_id, segment_depth, support_count = terminals[0]
                    profile = measure_loop(
                        current_loop,
                        origin=facts[current_face_id]["centroid"],
                        normal=entry_fact["normal"],
                        linear_tolerance=linear,
                    )
                    segments.append(
                        {
                            "carrier": "constant_profile",
                            "profile": profile,
                            "wall_face_ids": wall_ids,
                            "start_offset": current_offset,
                            "end_offset": current_offset + float(segment_depth),
                            "depth": float(segment_depth),
                            "terminal_face_id": terminal_face_id,
                            "terminal_wall_support_count": support_count,
                            "section_correspondence_error": 0.0,
                        }
                    )
                    all_wall_ids.extend(wall_ids)
                    seen_faces.update(wall_ids)
                    terminal_external = face_is_external_extreme(
                        terminal_face_id, local_face_ids, facts, linear
                    )
                    if terminal_external:
                        descriptor = model.describe_entity(terminal_face_id)
                        if int(descriptor["geometry"]["inner_boundary_count"]) > 0:
                            exit_face_id = terminal_face_id
                            completed = True
                        break
                    next_loop = _next_inner_loop(
                        model=model,
                        face_id=terminal_face_id,
                        previous_wall_ids=wall_ids,
                        facts=facts,
                        direction=direction,
                        angular_tolerance_degrees=angular,
                    )
                    if next_loop is None:
                        bottom_face_id = terminal_face_id
                        completed = True
                        break
                    internal_plane_ids.append(terminal_face_id)
                    seen_faces.add(terminal_face_id)
                    current_offset += float(segment_depth)
                    current_face_id = terminal_face_id
                    current_loop = next_loop
                if not completed or not segments:
                    continue

                total_depth = float(segments[-1]["end_offset"])
                terminal = "through" if exit_face_id else "blind"
                if (
                    terminal == "blind"
                    and len(segments) == 1
                    and total_depth < 0.75 * float(entry_profile["minimum_caliper"])
                ):
                    # A broad, shallow closed recess is a pocket region rather
                    # than a hole. Leave it unclaimed so extrusion ownership can
                    # apply its loop/wall/section gates.
                    continue
                if len(segments) > 1:
                    form = "profile_stepped"
                elif entry_profile["kind"] == "obround":
                    form = f"obround_{terminal}"
                elif entry_profile["kind"] == "rectangular":
                    form = "rectangular"
                elif entry_profile["kind"] == "polygonal":
                    form = "polygonal"
                elif entry_profile["kind"] == "d_or_keyhole":
                    form = "d_or_keyhole"
                else:
                    form = "freeform_profile"
                explained = entity_ids(
                    all_wall_ids
                    + internal_plane_ids
                    + ([bottom_face_id] if bottom_face_id else [])
                )
                support = entity_ids(
                    [entry_face_id] + ([exit_face_id] if exit_face_id else [])
                )
                geometry = {
                    "form": form,
                    "profile_family": "non_circular",
                    "terminal": terminal,
                    "direction": vector(direction),
                    "entry_face_id": entry_face_id,
                    "exit_face_id": exit_face_id,
                    "bottom_face_id": bottom_face_id,
                    "entry_count": 1,
                    "entry_center": entry_profile["centroid"],
                    "local_x_direction": entry_profile["local_x_direction"],
                    "local_y_direction": entry_profile["local_y_direction"],
                    "total_depth": total_depth,
                    "profiles": [segment["profile"] for segment in segments],
                    "segments": segments,
                }
                hint = {
                    "kind": "hole_region_candidate",
                    "claim": "geometric_candidate",
                    "body_id": body_id,
                    "entity_ids": explained,
                    "highlight_entity_ids": explained,
                    "support_entity_ids": support,
                    "geometry": geometry,
                    "confidence": confidence("strong"),
                    "evidence": [
                        evidence(
                            "hole.closed_entry_profile",
                            entity_ids_value=[entry_face_id, *entry_loop["edge_ids"]],
                            observed={"profile_kind": entry_profile["kind"]},
                        ),
                        evidence(
                            "hole.material_outside_profile_walls",
                            entity_ids_value=all_wall_ids,
                            observed={"closed_inner_loop": True},
                        ),
                        evidence(
                            "hole.continuous_constant_profile_segments",
                            entity_ids_value=explained,
                            observed={
                                "segment_count": len(segments),
                                "maximum_correspondence_error": 0.0,
                            },
                            criterion={"maximum": max(20.0 * linear, 1.0e-7)},
                        ),
                        evidence(
                            "hole.terminal_opening_or_bottom",
                            entity_ids_value=[exit_face_id or bottom_face_id],
                            observed={"terminal": terminal},
                        ),
                    ],
                }
                key = frozenset(explained)
                previous = candidates.get(key)
                if previous is None or entity_index(entry_face_id) < entity_index(
                    previous["geometry"]["entry_face_id"]
                ):
                    candidates[key] = hint
    return sorted(
        candidates.values(),
        key=lambda hint: (
            entity_index(hint["body_id"]),
            tuple(entity_index(value) for value in hint["entity_ids"]),
        ),
    )


def hole_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> list[dict[str, Any]]:
    """Return legacy analytic holes plus closed non-circular profiles."""

    legacy = _legacy_circular_hole_hints(model, facts, tolerances)
    for hint in legacy:
        hint["geometry"].setdefault("profile_family", "circular")
        hint["geometry"].setdefault(
            "terminal",
            "through" if hint["geometry"].get("exit_face_id") else "blind",
        )
    shaped = _shaped_hole_hints(model, facts, tolerances)
    legacy_entities = [set(hint["entity_ids"]) for hint in legacy]
    shaped = [
        hint
        for hint in shaped
        if not any(
            set(hint["entity_ids"]) == entity_set for entity_set in legacy_entities
        )
    ]
    return sorted(
        [*legacy, *shaped],
        key=lambda hint: (
            entity_index(hint["body_id"]),
            tuple(entity_index(value) for value in hint["entity_ids"]),
        ),
    )


__all__ = ["hole_hints"]

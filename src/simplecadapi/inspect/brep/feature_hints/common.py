"""Shared deterministic geometry facts for feature recognizers."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS


def entity_index(entity_id: str) -> int:
    return int(entity_id.split(":", 1)[1])


def entity_ids(values: Sequence[str]) -> list[str]:
    return sorted(set(values), key=entity_index)


def unit(values: Sequence[float]) -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    magnitude = float(np.linalg.norm(vector))
    if not math.isfinite(magnitude) or magnitude <= 1.0e-15:
        raise ValueError("direction must be finite and non-zero")
    return vector / magnitude


def vector(values: Sequence[float]) -> list[float]:
    return [round(float(value), 9) for value in values]


def parallel(
    first: Sequence[float],
    second: Sequence[float],
    angular_tolerance_degrees: float,
) -> bool:
    cosine = abs(float(np.dot(unit(first), unit(second))))
    angle = math.degrees(math.acos(min(1.0, max(-1.0, cosine))))
    return angle <= angular_tolerance_degrees


def angle_degrees(first: Sequence[float], second: Sequence[float]) -> float:
    cosine = abs(float(np.dot(unit(first), unit(second))))
    return math.degrees(math.acos(min(1.0, max(-1.0, cosine))))


def canonical_axis(
    point: Sequence[float], direction: Sequence[float]
) -> dict[str, list[float]]:
    direction_value = unit(direction)
    first_nonzero = next(
        (float(value) for value in direction_value if abs(float(value)) > 1.0e-12),
        1.0,
    )
    if first_nonzero < 0.0:
        direction_value = -direction_value
    point_value = np.asarray(point, dtype=float)
    closest = (
        point_value - float(np.dot(point_value, direction_value)) * direction_value
    )
    return {"point": vector(closest), "direction": vector(direction_value)}


def axes_coaxial(
    first: dict[str, Sequence[float]],
    second: dict[str, Sequence[float]],
    linear_tolerance: float,
    angular_tolerance_degrees: float,
) -> bool:
    if (
        angle_degrees(first["direction"], second["direction"])
        > angular_tolerance_degrees
    ):
        return False
    direction = unit(first["direction"])
    offset = np.asarray(second["point"], dtype=float) - np.asarray(
        first["point"], dtype=float
    )
    return float(np.linalg.norm(np.cross(offset, direction))) <= linear_tolerance


def cluster_axes(
    candidates: Sequence[dict[str, Any]],
    *,
    linear_tolerance: float,
    angular_tolerance_degrees: float,
) -> list[dict[str, Any]]:
    """Return deterministic transitive clusters of evidence-bearing axis lines."""

    ordered = sorted(candidates, key=lambda item: entity_index(item["entity_id"]))
    clusters: list[dict[str, Any]] = []
    for candidate in ordered:
        axis = canonical_axis(
            candidate["axis"]["point"], candidate["axis"]["direction"]
        )
        matching = next(
            (
                cluster
                for cluster in clusters
                if axes_coaxial(
                    cluster["axis"],
                    axis,
                    linear_tolerance,
                    angular_tolerance_degrees,
                )
            ),
            None,
        )
        if matching is None:
            clusters.append(
                {
                    "axis": axis,
                    "entity_ids": [candidate["entity_id"]],
                    "carrier_types": [candidate.get("carrier_type")],
                }
            )
            continue
        matching["entity_ids"].append(candidate["entity_id"])
        matching["carrier_types"].append(candidate.get("carrier_type"))
    return clusters


def rotate_points_about_axis(
    points: Sequence[Sequence[float]],
    *,
    axis: dict[str, Sequence[float]],
    angle_degrees_value: float,
) -> np.ndarray:
    values = np.asarray(points, dtype=float)
    if values.size == 0:
        return values.reshape((-1, 3))
    origin = np.asarray(axis["point"], dtype=float)
    direction = unit(axis["direction"])
    angle = math.radians(float(angle_degrees_value))
    relative = values - origin
    rotated = (
        relative * math.cos(angle)
        + np.cross(direction, relative) * math.sin(angle)
        + np.outer(relative @ direction, direction) * (1.0 - math.cos(angle))
    )
    return rotated + origin


def plane_contains_axis(
    *,
    plane_point: Sequence[float],
    plane_normal: Sequence[float],
    axis: dict[str, Sequence[float]],
    linear_tolerance: float,
    angular_tolerance_degrees: float,
) -> bool:
    normal = unit(plane_normal)
    direction = unit(axis["direction"])
    if abs(float(np.dot(normal, direction))) > math.sin(
        math.radians(angular_tolerance_degrees)
    ):
        return False
    distance = abs(
        float(
            np.dot(
                np.asarray(axis["point"], dtype=float)
                - np.asarray(plane_point, dtype=float),
                normal,
            )
        )
    )
    return distance <= linear_tolerance


def fact_axis(fact: dict[str, Any]) -> dict[str, list[float]] | None:
    if fact["type"] in {"CYLINDER", "CONE", "TORUS", "REVOLUTION"}:
        raw = fact["parameters"].get("axis")
        if raw:
            return canonical_axis(raw["point"], raw["direction"])
    return None


def axial_radial_coordinates(
    point: Sequence[float], axis: dict[str, Sequence[float]]
) -> tuple[float, float]:
    origin = np.asarray(axis["point"], dtype=float)
    direction = unit(axis["direction"])
    relative = np.asarray(point, dtype=float) - origin
    axial = float(np.dot(relative, direction))
    radial = float(np.linalg.norm(relative - axial * direction))
    return axial, radial


def evidence(
    code: str,
    *,
    entity_ids_value: Sequence[str] = (),
    observed: dict[str, Any] | None = None,
    criterion: dict[str, Any] | None = None,
    outcome: str = "pass",
    required: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "outcome": outcome,
        "required": required,
        "entity_ids": list(entity_ids_value),
        "observed": observed or {},
        "criterion": criterion or {},
    }


def confidence(level: str = "strong", support: float = 1.0) -> dict[str, Any]:
    return {
        "level": level,
        "support_fraction": float(support),
        "evaluated_fraction": 1.0,
        "calibrated_probability": False,
    }


def face_vertices(shape) -> list[np.ndarray]:
    points: list[np.ndarray] = []
    explorer = TopExp_Explorer(shape, TopAbs_VERTEX)
    while explorer.More():
        point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(explorer.Current()))
        points.append(np.asarray(point.Coord(), dtype=float))
        explorer.Next()
    return points


def plane_offset(fact: dict[str, Any], direction: Sequence[float]) -> float:
    return float(np.dot(np.asarray(fact["centroid"], dtype=float), unit(direction)))


def face_is_external_extreme(
    face_id: str,
    body_face_ids: Sequence[str],
    facts: dict[str, dict[str, Any]],
    linear_tolerance: float,
) -> bool:
    fact = facts[face_id]
    if fact["type"] != "PLANE" or fact["normal"] is None:
        return False
    normal = unit(fact["normal"])
    values = [
        float(np.dot(point, normal))
        for candidate_id in body_face_ids
        for point in face_vertices(facts[candidate_id]["shape"])
    ]
    if not values:
        return False
    tolerance = max(20.0 * linear_tolerance, 1.0e-7)
    return abs(plane_offset(fact, normal) - max(values)) <= tolerance


def face_is_side(
    fact: dict[str, Any],
    direction: Sequence[float],
    angular_tolerance_degrees: float,
) -> bool:
    if fact["type"] == "PLANE" and fact["normal"] is not None:
        return abs(float(np.dot(unit(fact["normal"]), unit(direction)))) <= math.sin(
            math.radians(angular_tolerance_degrees)
        )
    if fact["type"] == "CYLINDER":
        return parallel(
            fact["parameters"]["axis"]["direction"],
            direction,
            angular_tolerance_degrees,
        )
    if fact["type"] == "EXTRUSION":
        return parallel(
            fact["parameters"]["direction"],
            direction,
            angular_tolerance_degrees,
        )
    return False


def body_face_ids(model, body_id: str) -> list[str]:
    return sorted(model.adjacency_details(body_id)["faces"], key=entity_index)


def loop_wall_ids(model, loop: dict[str, Any], support_face_id: str) -> list[str]:
    result = set()
    for edge_id in loop["edge_ids"]:
        result.update(
            face_id
            for face_id in model.adjacency_details(edge_id)["faces"]
            if face_id != support_face_id
        )
    return entity_ids(result)


def terminal_face_candidates(
    *,
    model,
    start_face_id: str,
    wall_face_ids: Sequence[str],
    body_face_ids_value: Sequence[str],
    facts: dict[str, dict[str, Any]],
    direction: Sequence[float],
    linear_tolerance: float,
    angular_tolerance_degrees: float,
) -> list[tuple[str, float, int]]:
    direction_value = unit(direction)
    start_offset = plane_offset(facts[start_face_id], direction_value)
    counts: dict[str, int] = {}
    wall_set = set(wall_face_ids)
    for wall_face_id in wall_face_ids:
        for candidate_id in facts[wall_face_id]["neighbors"]:
            if candidate_id == start_face_id or candidate_id in wall_set:
                continue
            candidate = facts[candidate_id]
            if candidate["type"] != "PLANE" or candidate["normal"] is None:
                continue
            if not parallel(
                candidate["normal"], direction_value, angular_tolerance_degrees
            ):
                continue
            counts[candidate_id] = counts.get(candidate_id, 0) + 1
    minimum_count = max(2, int(math.ceil(0.75 * len(wall_face_ids))))
    result = []
    for candidate_id, count in counts.items():
        depth = plane_offset(facts[candidate_id], direction_value) - start_offset
        if depth > max(20.0 * linear_tolerance, 1.0e-7) and count >= minimum_count:
            result.append((candidate_id, depth, count))
    return sorted(result, key=lambda item: (item[1], entity_index(item[0])))


def is_external_side_face(
    face_id: str,
    body_face_ids_value: Sequence[str],
    facts: dict[str, dict[str, Any]],
    linear_tolerance: float,
) -> bool:
    fact = facts[face_id]
    return bool(
        fact["type"] == "PLANE"
        and fact["normal"] is not None
        and face_is_external_extreme(
            face_id, body_face_ids_value, facts, linear_tolerance
        )
    )

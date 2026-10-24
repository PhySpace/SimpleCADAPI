"""Legacy analytic-hole compatibility helpers.

New recognition is composed by :mod:`.feature_hints`; these private functions
remain for the public manufacturing interface's analytic-hole path.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_IN,
    TopAbs_ON,
    TopAbs_OUT,
    TopAbs_VERTEX,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.gp import gp_Pnt

from .model import BRepModel


def _entity_index(entity_id: str) -> int:
    return int(entity_id.split(":", 1)[1])


def _entity_ids(values: Sequence[str]) -> list[str]:
    return sorted(set(values), key=_entity_index)


def _unit(values: Sequence[float]) -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    magnitude = float(np.linalg.norm(vector))
    if magnitude <= 1.0e-15:
        raise ValueError("direction must be non-zero")
    return vector / magnitude


def _canonical_direction(values: Sequence[float]) -> np.ndarray:
    direction = _unit(values)
    first_nonzero = next(
        (float(value) for value in direction if abs(float(value)) > 1.0e-12),
        1.0,
    )
    return -direction if first_nonzero < 0.0 else direction


def _vector(values: Sequence[float]) -> list[float]:
    return [round(float(value), 9) for value in values]


def _axis(parameters: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    raw = parameters["axis"]
    direction = _canonical_direction(raw["direction"])
    point = np.asarray(raw["point"], dtype=float)
    point = point - np.dot(point, direction) * direction
    return point, direction


def _angle_degrees(first: Sequence[float], second: Sequence[float]) -> float:
    cosine = abs(float(np.dot(_unit(first), _unit(second))))
    return math.degrees(math.acos(min(1.0, max(-1.0, cosine))))


def _axes_coaxial(
    first: tuple[np.ndarray, np.ndarray],
    second: tuple[np.ndarray, np.ndarray],
    linear_tolerance: float,
    angular_tolerance_degrees: float,
) -> bool:
    first_point, first_direction = first
    second_point, second_direction = second
    if _angle_degrees(first_direction, second_direction) > angular_tolerance_degrees:
        return False
    offset = second_point - first_point
    return float(np.linalg.norm(np.cross(offset, first_direction))) <= linear_tolerance


def _confidence(level: str, support: float = 1.0) -> dict[str, Any]:
    return {
        "level": level,
        "support_fraction": float(support),
        "evaluated_fraction": 1.0,
        "calibrated_probability": False,
    }


def _evidence(
    code: str,
    *,
    entity_ids: Sequence[str] = (),
    observed: dict[str, Any] | None = None,
    criterion: dict[str, Any] | None = None,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "outcome": "pass",
        "required": required,
        "entity_ids": list(entity_ids),
        "observed": observed or {},
        "criterion": criterion or {},
    }


def _body_closed_manifold(body: TopoDS_Shape) -> bool:
    if not BRepCheck_Analyzer(body).IsValid():
        return False
    edges = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(body, TopAbs_EDGE, edges)
    edge_uses = [0] * edges.Extent()
    face_explorer = TopExp_Explorer(body, TopAbs_FACE)
    while face_explorer.More():
        edge_explorer = TopExp_Explorer(face_explorer.Current(), TopAbs_EDGE)
        while edge_explorer.More():
            edge = edge_explorer.Current()
            edge_index = edges.FindIndex(edge) - 1
            if edge_index >= 0:
                edge_uses[edge_index] += 1
            edge_explorer.Next()
        face_explorer.Next()
    return bool(edge_uses) and all(
        count == 2 or BRep_Tool.Degenerated_s(TopoDS.Edge_s(edges.FindKey(index + 1)))
        for index, count in enumerate(edge_uses)
    )


def _face_vertices(face: TopoDS_Shape) -> list[np.ndarray]:
    points: list[np.ndarray] = []
    explorer = TopExp_Explorer(face, TopAbs_VERTEX)
    while explorer.More():
        point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(explorer.Current()))
        points.append(np.asarray(point.Coord(), dtype=float))
        explorer.Next()
    return points


def _face_span(
    fact: dict[str, Any],
    axis_point: np.ndarray,
    axis_direction: np.ndarray,
) -> tuple[float, float]:
    projections = [
        float(np.dot(point - axis_point, axis_direction))
        for point in _face_vertices(fact["shape"])
    ]
    if not projections:
        surface = BRepAdaptor_Surface(TopoDS.Face_s(fact["shape"]), True)
        u = 0.5 * (float(surface.FirstUParameter()) + float(surface.LastUParameter()))
        for v in (float(surface.FirstVParameter()), float(surface.LastVParameter())):
            point = np.asarray(surface.Value(u, v).Coord(), dtype=float)
            projections.append(float(np.dot(point - axis_point, axis_direction)))
    return min(projections), max(projections)


def _radial_distance(
    point: np.ndarray,
    axis_point: np.ndarray,
    axis_direction: np.ndarray,
) -> float:
    offset = point - axis_point
    return float(
        np.linalg.norm(offset - np.dot(offset, axis_direction) * axis_direction)
    )


def _face_end_radii(
    fact: dict[str, Any],
    axis_point: np.ndarray,
    axis_direction: np.ndarray,
    span: tuple[float, float],
) -> tuple[float, float]:
    if fact["type"] == "CYLINDER":
        radius = float(fact["parameters"]["radius"])
        return radius, radius
    samples = []
    surface = BRepAdaptor_Surface(TopoDS.Face_s(fact["shape"]), True)
    u_values = (
        float(surface.FirstUParameter()),
        0.5 * (float(surface.FirstUParameter()) + float(surface.LastUParameter())),
        float(surface.LastUParameter()),
    )
    v_values = (float(surface.FirstVParameter()), float(surface.LastVParameter()))
    for u in u_values:
        for v in v_values:
            point = np.asarray(surface.Value(u, v).Coord(), dtype=float)
            projection = float(np.dot(point - axis_point, axis_direction))
            samples.append(
                (projection, _radial_distance(point, axis_point, axis_direction))
            )
    low = min(samples, key=lambda item: abs(item[0] - span[0]))[1]
    high = min(samples, key=lambda item: abs(item[0] - span[1]))[1]
    return float(low), float(high)


def _classifier(
    body: TopoDS_Shape,
    tolerance: float,
) -> tuple[BRepClass3d_SolidClassifier, bool] | None:
    classifier = BRepClass3d_SolidClassifier()
    classifier.Load(body)
    classifier.PerformInfinitePoint(tolerance)
    infinite_state = classifier.State()
    if infinite_state not in (TopAbs_IN, TopAbs_OUT):
        return None
    return classifier, infinite_state == TopAbs_IN


def _occupied(
    classifier_context: tuple[BRepClass3d_SolidClassifier, bool],
    point: np.ndarray,
    tolerance: float,
) -> bool | None:
    classifier, inverted = classifier_context
    classifier.Perform(gp_Pnt(*[float(value) for value in point]), tolerance)
    state = classifier.State()
    if state == TopAbs_ON or state not in (TopAbs_IN, TopAbs_OUT):
        return None
    occupied = state == TopAbs_IN
    return not occupied if inverted else occupied


def _cavity_material_side(
    fact: dict[str, Any],
    classifier_context: tuple[BRepClass3d_SolidClassifier, bool],
    linear_tolerance: float,
) -> bool | None:
    surface = BRepAdaptor_Surface(TopoDS.Face_s(fact["shape"]), True)
    u = 0.5 * (float(surface.FirstUParameter()) + float(surface.LastUParameter()))
    v = 0.5 * (float(surface.FirstVParameter()) + float(surface.LastVParameter()))
    point = np.asarray(surface.Value(u, v).Coord(), dtype=float)
    axis_point, axis_direction = _axis(fact["parameters"])
    offset = point - axis_point
    radial = offset - np.dot(offset, axis_direction) * axis_direction
    if float(np.linalg.norm(radial)) <= linear_tolerance:
        return None
    radial = _unit(radial)
    characteristic = max(_radial_distance(point, axis_point, axis_direction), 1.0)
    for multiplier in (20.0, 100.0, 500.0):
        delta = max(multiplier * linear_tolerance, characteristic * 1.0e-5)
        outside_axis = _occupied(
            classifier_context, point + radial * delta, linear_tolerance
        )
        inside_axis = _occupied(
            classifier_context, point - radial * delta, linear_tolerance
        )
        if outside_axis is None or inside_axis is None:
            continue
        if outside_axis != inside_axis:
            return outside_axis and not inside_axis
    return None


def _connected_components(
    face_ids: Sequence[str],
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> list[list[str]]:
    remaining = set(face_ids)
    components: list[list[str]] = []
    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    while remaining:
        seed = min(remaining, key=_entity_index)
        remaining.remove(seed)
        component = [seed]
        queue = [seed]
        while queue:
            current_id = queue.pop()
            current = facts[current_id]
            current_axis = _axis(current["parameters"])
            current_span = _face_span(current, *current_axis)
            for candidate_id in sorted(remaining, key=_entity_index):
                candidate = facts[candidate_id]
                candidate_axis = _axis(candidate["parameters"])
                if not _axes_coaxial(
                    current_axis,
                    candidate_axis,
                    max(linear, float(tolerances["radius"])),
                    angular,
                ):
                    continue
                candidate_span = _face_span(candidate, *current_axis)
                gap = max(
                    current_span[0] - candidate_span[1],
                    candidate_span[0] - current_span[1],
                    0.0,
                )
                if gap > max(20.0 * linear, 1.0e-7):
                    continue
                remaining.remove(candidate_id)
                component.append(candidate_id)
                queue.append(candidate_id)
        components.append(sorted(component, key=_entity_index))
    return components


def _merge_segments(
    face_ids: Sequence[str],
    facts: dict[str, dict[str, Any]],
    axis_point: np.ndarray,
    axis_direction: np.ndarray,
    tolerances: dict[str, float | str],
) -> list[dict[str, Any]]:
    radius_tolerance = float(tolerances["radius"])
    linear_tolerance = float(tolerances["linear"])
    raw = []
    for face_id in face_ids:
        fact = facts[face_id]
        span = _face_span(fact, axis_point, axis_direction)
        low_radius, high_radius = _face_end_radii(
            fact, axis_point, axis_direction, span
        )
        raw.append(
            {
                "carrier": fact["type"].lower(),
                "face_ids": [face_id],
                "low": span[0],
                "high": span[1],
                "low_radius": low_radius,
                "high_radius": high_radius,
            }
        )
    merged: list[dict[str, Any]] = []
    for item in sorted(raw, key=lambda value: (value["low"], value["high"])):
        match = next(
            (
                value
                for value in merged
                if value["carrier"] == item["carrier"]
                and abs(float(value["low"]) - float(item["low"]))
                <= max(20.0 * linear_tolerance, 1.0e-7)
                and abs(float(value["high"]) - float(item["high"]))
                <= max(20.0 * linear_tolerance, 1.0e-7)
                and abs(float(value["low_radius"]) - float(item["low_radius"]))
                <= radius_tolerance
                and abs(float(value["high_radius"]) - float(item["high_radius"]))
                <= radius_tolerance
            ),
            None,
        )
        if match is None:
            merged.append(item)
        else:
            match["face_ids"].extend(item["face_ids"])
    return merged


def _terminal_planes(
    face_ids: Sequence[str],
    body_face_ids: set[str],
    facts: dict[str, dict[str, Any]],
    axis_direction: np.ndarray,
    offset: float,
    tolerances: dict[str, float | str],
) -> list[str]:
    linear = float(tolerances["linear"])
    angular = float(tolerances["angular_degrees"])
    result = []
    for face_id in sorted(body_face_ids, key=_entity_index):
        fact = facts[face_id]
        if fact["type"] != "PLANE" or fact["normal"] is None:
            continue
        if _angle_degrees(fact["normal"], axis_direction) > angular:
            continue
        if abs(float(np.dot(fact["centroid"], axis_direction)) - offset) > max(
            20.0 * linear, 1.0e-7
        ):
            continue
        if set(fact["neighbors"]).intersection(face_ids):
            result.append(face_id)
    return result


def _is_opening_face(model: BRepModel, face_id: str) -> bool:
    descriptor = model.describe_entity(face_id)
    return int(descriptor["geometry"]["inner_boundary_count"]) > 0


def _classify_hole(segments: Sequence[dict[str, Any]], terminal_kind: str) -> str:
    if segments and segments[0]["carrier"] == "cone":
        if len(segments) == 1:
            return "tapered_hole"
        return "countersink"
    if len(segments) == 1 and segments[0]["carrier"] == "cylinder":
        return "through_hole" if terminal_kind == "opening" else "blind_hole"
    diameters = [float(segment["diameter"]) for segment in segments]
    if (
        len(segments) == 2
        and all(segment["carrier"] == "cylinder" for segment in segments)
        and diameters[0] > diameters[1]
    ):
        return "counterbore"
    return "stepped_hole"


def _hole_hints(
    model: BRepModel,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    linear = float(tolerances["linear"])
    for body_index, body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        if not _body_closed_manifold(body):
            continue
        body_face_ids = set(model.adjacency_details(body_id)["faces"])
        classifier_context = _classifier(body, linear)
        if classifier_context is None:
            continue
        cavity_face_ids = []
        for face_id in sorted(body_face_ids, key=_entity_index):
            fact = facts[face_id]
            if fact["type"] not in {"CYLINDER", "CONE"}:
                continue
            if _cavity_material_side(fact, classifier_context, linear) is True:
                cavity_face_ids.append(face_id)
        for component in _connected_components(cavity_face_ids, facts, tolerances):
            reference_axis = _axis(facts[component[0]]["parameters"])
            axis_point, axis_direction = reference_axis
            if any(
                not _axes_coaxial(
                    reference_axis,
                    _axis(facts[face_id]["parameters"]),
                    max(linear, float(tolerances["radius"])),
                    float(tolerances["angular_degrees"]),
                )
                for face_id in component
            ):
                continue
            segments = _merge_segments(
                component, facts, axis_point, axis_direction, tolerances
            )
            minimum = min(float(segment["low"]) for segment in segments)
            maximum = max(float(segment["high"]) for segment in segments)
            ordered_by_axis = sorted(segments, key=lambda item: item["low"])
            if any(
                float(second["low"]) - float(first["high"]) > max(20.0 * linear, 1.0e-7)
                for first, second in zip(ordered_by_axis, ordered_by_axis[1:])
            ):
                continue
            low_planes = _terminal_planes(
                component,
                body_face_ids,
                facts,
                axis_direction,
                minimum + float(np.dot(axis_point, axis_direction)),
                tolerances,
            )
            high_planes = _terminal_planes(
                component,
                body_face_ids,
                facts,
                axis_direction,
                maximum + float(np.dot(axis_point, axis_direction)),
                tolerances,
            )
            terminals = [
                ("low", face_id, _is_opening_face(model, face_id))
                for face_id in low_planes
            ] + [
                ("high", face_id, _is_opening_face(model, face_id))
                for face_id in high_planes
            ]
            openings = [record for record in terminals if record[2]]
            bottoms = [record for record in terminals if not record[2]]
            if not openings or len(terminals) < 2:
                continue
            entry_side, entry_face_id, _ = min(
                openings, key=lambda record: _entity_index(record[1])
            )
            remaining_terminals = [
                record for record in terminals if record[1] != entry_face_id
            ]
            if not remaining_terminals:
                continue
            end_side, end_face_id, end_is_opening = min(
                remaining_terminals, key=lambda record: _entity_index(record[1])
            )
            if entry_side == end_side:
                continue
            direction = axis_direction if entry_side == "low" else -axis_direction
            entry_offset = minimum if entry_side == "low" else maximum
            serialized_segments = []
            for segment in sorted(
                segments,
                key=lambda item: (
                    float(item["low"] - entry_offset)
                    if entry_side == "low"
                    else float(entry_offset - item["high"])
                ),
            ):
                if entry_side == "low":
                    start = float(segment["low"] - entry_offset)
                    end = float(segment["high"] - entry_offset)
                    start_radius = float(segment["low_radius"])
                    end_radius = float(segment["high_radius"])
                else:
                    start = float(entry_offset - segment["high"])
                    end = float(entry_offset - segment["low"])
                    start_radius = float(segment["high_radius"])
                    end_radius = float(segment["low_radius"])
                diameter = 2.0 * (
                    start_radius
                    if segment["carrier"] == "cone"
                    else 0.5 * (start_radius + end_radius)
                )
                serialized_segments.append(
                    {
                        "carrier": segment["carrier"],
                        "face_ids": _entity_ids(segment["face_ids"]),
                        "diameter": float(diameter),
                        "start_diameter": 2.0 * start_radius,
                        "end_diameter": 2.0 * end_radius,
                        "start_offset": start,
                        "end_offset": end,
                    }
                )
            internal_plane_ids = [
                face_id
                for face_id in sorted(body_face_ids, key=_entity_index)
                if facts[face_id]["type"] == "PLANE"
                and face_id not in {entry_face_id, end_face_id}
                and len(set(facts[face_id]["neighbors"]).intersection(component)) >= 2
            ]
            bottom_face_id = None if end_is_opening else end_face_id
            exit_face_id = end_face_id if end_is_opening else None
            explained = _entity_ids(
                component
                + internal_plane_ids
                + ([bottom_face_id] if bottom_face_id else [])
            )
            support = _entity_ids(
                [entry_face_id] + ([exit_face_id] if exit_face_id else [])
            )
            total_depth = maximum - minimum
            form = _classify_hole(
                serialized_segments, "opening" if end_is_opening else "bottom"
            )
            hints.append(
                {
                    "kind": "hole_region_candidate",
                    "claim": "geometric_candidate",
                    "body_id": body_id,
                    "entity_ids": explained,
                    "highlight_entity_ids": explained,
                    "support_entity_ids": support,
                    "geometry": {
                        "form": form,
                        "axis": {
                            "point": _vector(axis_point),
                            "direction": _vector(direction),
                        },
                        "entry_face_id": entry_face_id,
                        "exit_face_id": exit_face_id,
                        "bottom_face_id": bottom_face_id,
                        "diameters": [
                            float(segment["diameter"])
                            for segment in serialized_segments
                        ],
                        "depths": [
                            float(segment["end_offset"] - segment["start_offset"])
                            for segment in serialized_segments
                        ],
                        "total_depth": float(total_depth),
                        "segments": serialized_segments,
                    },
                    "confidence": _confidence("strong"),
                    "evidence": [
                        _evidence(
                            "hole.closed_manifold_body",
                            entity_ids=[body_id],
                        ),
                        _evidence(
                            "hole.material_outside_wall",
                            entity_ids=component,
                        ),
                        _evidence(
                            "hole.coaxial_contiguous_segments",
                            entity_ids=component,
                            observed={"segment_count": len(serialized_segments)},
                            criterion={
                                "linear_tolerance": linear,
                                "angular_tolerance_degrees": float(
                                    tolerances["angular_degrees"]
                                ),
                            },
                        ),
                        _evidence(
                            "hole.planar_entry",
                            entity_ids=[entry_face_id],
                        ),
                        _evidence(
                            "hole.terminal_opening_or_bottom",
                            entity_ids=[end_face_id],
                            observed={
                                "terminal": "opening" if end_is_opening else "bottom"
                            },
                        ),
                        _evidence(
                            "hole.stable_dimensions",
                            entity_ids=explained,
                            observed={"total_depth": float(total_depth)},
                            criterion={
                                "linear_tolerance": linear,
                                "radius_tolerance": float(tolerances["radius"]),
                            },
                        ),
                    ],
                }
            )
    return sorted(
        hints,
        key=lambda hint: (
            _entity_index(hint["body_id"]),
            tuple(_entity_index(value) for value in hint["entity_ids"]),
        ),
    )


__all__: list[str] = []

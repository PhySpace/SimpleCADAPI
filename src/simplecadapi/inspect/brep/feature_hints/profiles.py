"""Closed-loop extraction, planar measurement, and profile classification."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.TopAbs import TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

from .common import (
    axial_radial_coordinates,
    entity_index,
    face_vertices,
    rotate_points_about_axis,
    unit,
    vector,
)


def _canonical_cycle(values: Sequence[str]) -> list[str]:
    items = list(values)
    if len(items) < 2:
        return items
    candidates = []
    for ordered in (items, list(reversed(items))):
        candidates.extend(
            ordered[offset:] + ordered[:offset] for offset in range(len(ordered))
        )
    return min(candidates, key=lambda item: tuple(map(entity_index, item)))


def face_loops(model, face_id: str) -> list[dict[str, Any]]:
    _, _, shape = model.resolve_entity(face_id)
    face = TopoDS.Face_s(shape)
    outer = BRepTools.OuterWire_s(face)
    wires = []
    explorer = TopExp_Explorer(face, TopAbs_WIRE)
    while explorer.More():
        wires.append(TopoDS.Wire_s(explorer.Current()))
        explorer.Next()
    ordered = [] if outer.IsNull() else [outer]
    ordered.extend(wire for wire in wires if outer.IsNull() or not wire.IsSame(outer))
    result = []
    for position, wire in enumerate(ordered):
        wire_explorer = BRepTools_WireExplorer(wire, face)
        edges = []
        while wire_explorer.More():
            edges.append(TopoDS.Edge_s(wire_explorer.Current()))
            wire_explorer.Next()
        edge_ids = [model.id_for_shape("edge", edge) for edge in edges]
        result.append(
            {
                "face_id": face_id,
                "role": "outer" if position == 0 else "inner",
                "loop_index": 0 if position == 0 else position - 1,
                "edge_ids": _canonical_cycle(edge_ids),
                "edges": edges,
            }
        )
    return result


def _curve_type(edge) -> str:
    if BRep_Tool.Degenerated_s(edge):
        return "DEGENERATE"
    raw = str(BRepAdaptor_Curve(edge).GetType()).rsplit(".", 1)[-1]
    return raw.removeprefix("GeomAbs_").upper()


def _edge_length(edge) -> float:
    properties = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, properties)
    return float(properties.Mass())


def _sample_edge(edge, count: int = 9) -> list[np.ndarray]:
    if BRep_Tool.Degenerated_s(edge):
        return []
    adaptor = BRepAdaptor_Curve(edge)
    first = float(adaptor.FirstParameter())
    last = float(adaptor.LastParameter())
    if not math.isfinite(first) or not math.isfinite(last):
        return []
    parameters = np.linspace(first, last, count)
    if edge.Orientation().name.endswith("REVERSED"):
        parameters = parameters[::-1]
    return [
        np.asarray(adaptor.Value(float(parameter)).Coord(), dtype=float)
        for parameter in parameters
    ]


def loop_points(loop: dict[str, Any], *, dense: bool = False) -> list[np.ndarray]:
    points: list[np.ndarray] = []
    for edge in loop["edges"]:
        samples = _sample_edge(edge, 17 if dense else 2)
        points.extend(samples if not points else samples[1:])
    if len(points) > 1 and float(np.linalg.norm(points[0] - points[-1])) <= 1.0e-9:
        points.pop()
    return points


def loop_polylines(
    loop: dict[str, Any], *, samples_per_edge: int = 65
) -> list[np.ndarray]:
    if samples_per_edge < 2:
        raise ValueError("samples_per_edge must be at least two")
    return [
        np.asarray(samples, dtype=float)
        for edge in loop["edges"]
        for samples in [_sample_edge(edge, samples_per_edge)]
        if len(samples) >= 2
    ]


def resample_loop(loop: dict[str, Any], *, count: int = 128) -> np.ndarray:
    """Sample a closed boundary at equal arc-length intervals.

    Equal-distance sampling removes dependence on edge splitting while retaining
    the actual BREP curve geometry.
    """

    if count < 8:
        raise ValueError("count must be at least eight")
    points = np.asarray(loop_points(loop, dense=True), dtype=float)
    if len(points) < 3:
        raise ValueError("closed profile loop has fewer than three sampled points")
    closed = np.vstack([points, points[0]])
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    total = float(np.sum(lengths))
    if not math.isfinite(total) or total <= 1.0e-15:
        raise ValueError("closed profile loop has zero or non-finite perimeter")
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    distances = np.linspace(0.0, total, count, endpoint=False)
    result = []
    segment = 0
    for distance in distances:
        while segment + 1 < len(cumulative) and cumulative[segment + 1] <= distance:
            segment += 1
        segment_length = lengths[min(segment, len(lengths) - 1)]
        fraction = (
            0.0
            if segment_length <= 1.0e-15
            else (distance - cumulative[segment]) / segment_length
        )
        result.append(
            closed[segment] + fraction * (closed[segment + 1] - closed[segment])
        )
    return np.asarray(result, dtype=float)


def sample_edge_points(edge, *, count: int = 129) -> np.ndarray:
    """Return ordered points on one real BRep edge."""

    if count < 2:
        raise ValueError("count must be at least two")
    return np.asarray(_sample_edge(edge, count), dtype=float)


def align_closed_profiles(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    count: int = 128,
) -> dict[str, Any]:
    """Find the best cyclic 3-D similarity alignment of two closed loops.

    Both wire direction and start edge are unknown in an imported BRep.  The
    exhaustive cyclic search is deterministic and the Kabsch fit separates a
    rigidly transported profile (sweep) from a genuinely changing one (loft).
    """

    source = resample_loop(first, count=count)
    target = resample_loop(second, count=count)
    source_center = np.mean(source, axis=0)
    source_zero = source - source_center
    source_energy = float(np.sum(source_zero * source_zero))
    if source_energy <= 1.0e-24:
        raise ValueError("profile has zero spatial extent")
    best: tuple[tuple[float, float, float, int, int], dict[str, Any]] | None = None
    for reversed_order in (False, True):
        ordered = target[::-1] if reversed_order else target
        for offset in range(count):
            candidate = np.roll(ordered, -offset, axis=0)
            target_center = np.mean(candidate, axis=0)
            target_zero = candidate - target_center
            covariance = source_zero.T @ target_zero
            left, singular, right = np.linalg.svd(covariance)
            rotation = right.T @ left.T
            if float(np.linalg.det(rotation)) < 0.0:
                right[-1, :] *= -1.0
                rotation = right.T @ left.T
            rigid = source_zero @ rotation.T + target_center
            rigid_distances = np.linalg.norm(rigid - candidate, axis=1)
            scale = float(np.sum(singular) / source_energy)
            similarity = scale * (source_zero @ rotation.T) + target_center
            similarity_distances = np.linalg.norm(similarity - candidate, axis=1)
            trace = min(3.0, max(-1.0, float(np.trace(rotation))))
            angle = math.degrees(math.acos(min(1.0, max(-1.0, (trace - 1.0) * 0.5))))
            payload = {
                "sample_count": count,
                "reversed": reversed_order,
                "cyclic_offset": offset,
                "source_centroid": vector(source_center),
                "target_centroid": vector(target_center),
                "translation": vector(target_center - source_center @ rotation.T),
                "rotation_matrix": [vector(row) for row in rotation],
                "rotation_angle_degrees": angle,
                "scale": scale,
                "rigid_rms_error": float(np.sqrt(np.mean(rigid_distances**2))),
                "rigid_maximum_error": float(np.max(rigid_distances)),
                "similarity_rms_error": float(
                    np.sqrt(np.mean(similarity_distances**2))
                ),
                "similarity_maximum_error": float(np.max(similarity_distances)),
            }
            key = (
                payload["rigid_maximum_error"],
                payload["rigid_rms_error"],
                angle,
                int(reversed_order),
                offset,
            )
            if best is None or key < best[0]:
                best = (key, payload)
    if best is None:
        raise ValueError("profile alignment produced no candidate")
    return best[1]


def loop_geometry_signature(loop: dict[str, Any]) -> dict[str, Any]:
    curve_types = [_curve_type(edge) for edge in loop["edges"]]
    return {
        "closed": True,
        "perimeter": float(sum(_edge_length(edge) for edge in loop["edges"])),
        "curve_type_counts": {
            value: curve_types.count(value) for value in sorted(set(curve_types))
        },
        "cyclic_curve_sequence": (
            min(
                tuple(curve_types[offset:] + curve_types[:offset])
                for offset in range(len(curve_types))
            )
            if curve_types
            else ()
        ),
    }


def _directed_distance(first: np.ndarray, second: np.ndarray) -> float:
    """Maximum distance from points to the closed polyline ``second``."""

    if len(first) == 0 or len(second) < 2:
        return math.inf
    starts = second
    ends = np.roll(second, -1, axis=0)
    segments = ends - starts
    squared_lengths = np.sum(segments * segments, axis=1)
    maximum = 0.0
    for point in first:
        projections = np.zeros(len(segments), dtype=float)
        nonzero = squared_lengths > 1.0e-30
        projections[nonzero] = (
            np.sum((point - starts[nonzero]) * segments[nonzero], axis=1)
            / squared_lengths[nonzero]
        )
        projections = np.clip(projections, 0.0, 1.0)
        closest = starts + projections[:, None] * segments
        maximum = max(maximum, float(np.min(np.linalg.norm(closest - point, axis=1))))
    return maximum


def _directed_to_polylines(first: np.ndarray, polylines: Sequence[np.ndarray]) -> float:
    if len(first) == 0 or not polylines:
        return math.inf
    maximum = 0.0
    for point in first:
        minimum = math.inf
        for polyline in polylines:
            if len(polyline) < 2:
                continue
            starts = polyline[:-1]
            segments = polyline[1:] - starts
            squared = np.sum(segments * segments, axis=1)
            projections = np.zeros(len(segments), dtype=float)
            nonzero = squared > 1.0e-30
            projections[nonzero] = (
                np.sum((point - starts[nonzero]) * segments[nonzero], axis=1)
                / squared[nonzero]
            )
            projections = np.clip(projections, 0.0, 1.0)
            closest = starts + projections[:, None] * segments
            minimum = min(
                minimum,
                float(np.min(np.linalg.norm(closest - point, axis=1))),
            )
        maximum = max(maximum, minimum)
    return maximum


def transformed_loop_deviation(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    transform: str,
    expected_direction: Sequence[float] | None = None,
    axis: dict[str, Sequence[float]] | None = None,
    angle_degrees: float | None = None,
) -> dict[str, Any]:
    first_polylines = loop_polylines(first)
    second_polylines = loop_polylines(second)
    first_points = np.vstack([value for value in first_polylines if len(value)])
    second_points = np.vstack([value for value in second_polylines if len(value)])
    translation = np.zeros(3, dtype=float)
    if transform == "translation":
        first_center = (first_points.min(axis=0) + first_points.max(axis=0)) * 0.5
        second_center = (second_points.min(axis=0) + second_points.max(axis=0)) * 0.5
        translation = second_center - first_center
        if expected_direction is not None:
            direction = unit(expected_direction)
            translation = float(np.dot(translation, direction)) * direction
        transformed_polylines = [value + translation for value in first_polylines]
    elif transform == "rotation":
        if axis is None or angle_degrees is None:
            raise ValueError("rotation matching requires axis and angle_degrees")
        transformed_polylines = [
            rotate_points_about_axis(
                value,
                axis=axis,
                angle_degrees_value=angle_degrees,
            )
            for value in first_polylines
        ]
    else:
        raise ValueError("transform must be 'translation' or 'rotation'")
    transformed = np.vstack(transformed_polylines)
    forward = _directed_to_polylines(transformed, second_polylines)
    reverse = _directed_to_polylines(second_points, transformed_polylines)
    return {
        "translation": vector(translation),
        "forward_deviation": forward,
        "reverse_deviation": reverse,
        "maximum_deviation": max(forward, reverse),
    }


def pair_loop_sets(
    first_loops: Sequence[dict[str, Any]],
    second_loops: Sequence[dict[str, Any]],
    *,
    transform: str,
    linear_tolerance: float,
    expected_direction: Sequence[float] | None = None,
    axis: dict[str, Sequence[float]] | None = None,
    angle_degrees: float | None = None,
) -> dict[str, Any]:
    """Pair loops by deterministic global minimum cost, never list position."""

    from functools import lru_cache

    first_values = list(first_loops)
    second_values = list(second_loops)
    boundary_tolerance = max(20.0 * linear_tolerance, 1.0e-7)
    costs: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}
    for first_index, first in enumerate(first_values):
        first_signature = loop_geometry_signature(first)
        for second_index, second in enumerate(second_values):
            second_signature = loop_geometry_signature(second)
            perimeter_scale = max(
                first_signature["perimeter"], second_signature["perimeter"], 1.0
            )
            perimeter_delta = abs(
                first_signature["perimeter"] - second_signature["perimeter"]
            )
            if perimeter_delta > max(20.0 * linear_tolerance, 1.0e-6 * perimeter_scale):
                continue
            deviation = transformed_loop_deviation(
                first,
                second,
                transform=transform,
                expected_direction=expected_direction,
                axis=axis,
                angle_degrees=angle_degrees,
            )
            pair_tolerance = max(
                boundary_tolerance,
                1.0e-5 * perimeter_scale,
            )
            if deviation["maximum_deviation"] > pair_tolerance:
                continue
            role_penalty = 0.0 if first["role"] == second["role"] else linear_tolerance
            costs[(first_index, second_index)] = (
                deviation["maximum_deviation"] + perimeter_delta + role_penalty,
                {
                    **deviation,
                    "first_loop_index": first_index,
                    "second_loop_index": second_index,
                    "first_role": first["role"],
                    "second_role": second["role"],
                    "first_face_id": first["face_id"],
                    "second_face_id": second["face_id"],
                    "first_edge_ids": list(first["edge_ids"]),
                    "second_edge_ids": list(second["edge_ids"]),
                    "perimeter_delta": perimeter_delta,
                },
            )

    skip_cost = max(boundary_tolerance, 1.0)

    @lru_cache(maxsize=None)
    def solve(first_index: int, used_mask: int):
        if first_index >= len(first_values):
            return 0.0, ()
        best_cost, best_pairs = solve(first_index + 1, used_mask)
        best_cost += skip_cost
        for second_index in range(len(second_values)):
            if used_mask & (1 << second_index):
                continue
            candidate = costs.get((first_index, second_index))
            if candidate is None:
                continue
            remainder_cost, remainder_pairs = solve(
                first_index + 1, used_mask | (1 << second_index)
            )
            total = candidate[0] + remainder_cost
            pairs = ((first_index, second_index),) + remainder_pairs
            if (total, pairs) < (best_cost, best_pairs):
                best_cost, best_pairs = total, pairs
        return best_cost, best_pairs

    _, selected = solve(0, 0)
    matches = [costs[pair][1] for pair in selected]
    matched_first = {pair[0] for pair in selected}
    matched_second = {pair[1] for pair in selected}
    return {
        "matches": matches,
        "unmatched_first": [
            index for index in range(len(first_values)) if index not in matched_first
        ],
        "unmatched_second": [
            index for index in range(len(second_values)) if index not in matched_second
        ],
    }


def measure_meridian_profile(
    face_ids: Sequence[str],
    facts: dict[str, dict[str, Any]],
    *,
    axis: dict[str, Sequence[float]],
) -> dict[str, Any]:
    coordinates = {
        tuple(round(value, 9) for value in axial_radial_coordinates(point, axis))
        for face_id in face_ids
        for point in face_vertices(facts[face_id]["shape"])
    }
    center = np.mean(np.asarray(list(coordinates), dtype=float), axis=0)
    ordered = sorted(
        coordinates,
        key=lambda value: (
            math.atan2(value[1] - center[1], value[0] - center[0]),
            value,
        ),
    )
    if not ordered:
        raise ValueError("revolution candidate has no measurable meridian vertices")
    axial = [value[0] for value in ordered]
    radial = [value[1] for value in ordered]
    return {
        "family": "revolution",
        "kind": "meridian",
        "segments": [
            {"index": index, "start": list(first), "end": list(second)}
            for index, (first, second) in enumerate(
                zip(ordered, [*ordered[1:], ordered[0]])
            )
        ],
        "samples_2d": [list(value) for value in ordered],
        "minimum_radius": min(radial),
        "maximum_radius": max(radial),
        "axial_span": max(axial) - min(axial),
    }


def local_axes(normal: Sequence[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    normal_value = unit(normal)
    reference = min(np.eye(3), key=lambda axis: abs(float(np.dot(axis, normal_value))))
    x_axis = unit(np.cross(reference, normal_value))
    y_axis = unit(np.cross(normal_value, x_axis))
    return x_axis, y_axis, normal_value


def _signed_area(points: np.ndarray) -> float:
    return 0.5 * float(
        np.sum(points[:, 0] * np.roll(points[:, 1], -1))
        - np.sum(points[:, 1] * np.roll(points[:, 0], -1))
    )


def _canonical_points(points: np.ndarray) -> np.ndarray:
    """Choose one cyclic order independent of wire orientation and start."""

    if len(points) < 2:
        return points
    rounded = [tuple(round(float(value), 9) for value in point) for point in points]
    candidates = []
    for reverse in (False, True):
        indices = list(range(len(points)))
        if reverse:
            indices.reverse()
        for offset in range(len(indices)):
            ordered = indices[offset:] + indices[:offset]
            key = tuple(rounded[index] for index in ordered)
            candidates.append((key, ordered))
    _, selected = min(candidates, key=lambda item: item[0])
    return points[selected]


def _is_convex(points: np.ndarray, tolerance: float) -> bool:
    if len(points) < 4:
        return True
    signs = []
    for index in range(len(points)):
        first = points[index]
        second = points[(index + 1) % len(points)]
        third = points[(index + 2) % len(points)]
        first_vector = second - first
        second_vector = third - second
        cross = float(
            first_vector[0] * second_vector[1] - first_vector[1] * second_vector[0]
        )
        if abs(cross) > tolerance:
            signs.append(math.copysign(1.0, cross))
    return not signs or all(value == signs[0] for value in signs)


def _classify(
    *,
    curve_types: Sequence[str],
    edge_count: int,
    aspect_ratio: float,
    fill_ratio: float,
    convex: bool,
) -> str:
    nondegenerate = [value for value in curve_types if value != "DEGENERATE"]
    if nondegenerate and all(value in {"CIRCLE", "ELLIPSE"} for value in nondegenerate):
        return "circular" if aspect_ratio <= 1.05 else "elliptic"
    if edge_count == 4 and convex:
        return "rectangular"
    if convex and edge_count <= 10:
        return "polygonal"
    if convex and edge_count >= 12 and aspect_ratio >= 2.2 and fill_ratio >= 0.84:
        return "obround"
    if convex and edge_count >= 12 and fill_ratio >= 0.95:
        return "rectangular"
    if not convex and edge_count >= 16:
        return "d_or_keyhole"
    return "freeform"


def measure_loop(
    loop: dict[str, Any],
    *,
    origin: Sequence[float],
    normal: Sequence[float],
    linear_tolerance: float,
) -> dict[str, Any]:
    x_axis, y_axis, normal_value = local_axes(normal)
    origin_value = np.asarray(origin, dtype=float)
    sparse = loop_points(loop, dense=False)
    dense = loop_points(loop, dense=True)
    if len(dense) < 3:
        raise ValueError("closed profile loop has fewer than three sampled points")
    if len(sparse) < 3:
        sparse = dense
    sparse_2d = np.asarray(
        [
            [
                float(np.dot(point - origin_value, x_axis)),
                float(np.dot(point - origin_value, y_axis)),
            ]
            for point in sparse
        ],
        dtype=float,
    )
    dense_2d = np.asarray(
        [
            [
                float(np.dot(point - origin_value, x_axis)),
                float(np.dot(point - origin_value, y_axis)),
            ]
            for point in dense
        ],
        dtype=float,
    )
    dense_2d = _canonical_points(dense_2d)
    minimum = dense_2d.min(axis=0)
    maximum = dense_2d.max(axis=0)
    spans = maximum - minimum
    width = float(max(spans))
    height = float(min(spans))
    area = abs(_signed_area(dense_2d))
    perimeter = sum(_edge_length(edge) for edge in loop["edges"])
    bbox_area = max(float(spans[0] * spans[1]), 1.0e-15)
    curve_types = [_curve_type(edge) for edge in loop["edges"]]
    convex = _is_convex(sparse_2d, max(linear_tolerance, 1.0e-10))
    aspect_ratio = width / max(height, 1.0e-15)
    fill_ratio = min(1.0, area / bbox_area)
    profile_kind = _classify(
        curve_types=curve_types,
        edge_count=len(loop["edges"]),
        aspect_ratio=aspect_ratio,
        fill_ratio=fill_ratio,
        convex=convex,
    )
    centroid_2d = np.mean(dense_2d, axis=0)
    centroid_3d = origin_value + centroid_2d[0] * x_axis + centroid_2d[1] * y_axis
    return {
        "family": "circular" if profile_kind == "circular" else "non_circular",
        "kind": profile_kind,
        "role": loop["role"],
        "face_id": loop["face_id"],
        "loop_index": loop["loop_index"],
        "edge_ids": list(loop["edge_ids"]),
        "curve_types": curve_types,
        "segment_count": len(loop["edges"]),
        "width": width,
        "height": height,
        "area": area,
        "perimeter": float(perimeter),
        "maximum_caliper": width,
        "minimum_caliper": height,
        "aspect_ratio": aspect_ratio,
        "fill_ratio": fill_ratio,
        "convex": convex,
        "centroid": vector(centroid_3d),
        "local_x_direction": vector(x_axis),
        "local_y_direction": vector(y_axis),
        "normal": vector(normal_value),
        "samples_2d": [[float(x), float(y)] for x, y in dense_2d],
    }


def matching_inner_loop(
    model,
    face_id: str,
    wall_face_ids: Sequence[str],
) -> dict[str, Any] | None:
    wall_set = set(wall_face_ids)
    candidates = []
    for loop in face_loops(model, face_id):
        if loop["role"] != "inner":
            continue
        adjacent = {
            adjacent_face
            for edge_id in loop["edge_ids"]
            for adjacent_face in model.adjacency_details(edge_id)["faces"]
            if adjacent_face != face_id
        }
        candidates.append((len(adjacent & wall_set), loop))
    if not candidates:
        return None
    count, loop = max(candidates, key=lambda item: item[0])
    return loop if count >= max(2, int(math.ceil(0.75 * len(wall_face_ids)))) else None

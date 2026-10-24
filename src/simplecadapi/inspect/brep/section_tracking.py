"""Ordered section-contour tracking with explicit topology-change events."""

from __future__ import annotations

from itertools import combinations
from math import hypot, sqrt
from typing import Any, Mapping, Sequence


def _centroid(contour: Mapping[str, Any]) -> tuple[float, float]:
    value = contour.get("centroid_2d") or contour.get("centroid")
    if isinstance(value, Sequence) and len(value) >= 2:
        return float(value[0]), float(value[1])
    points = contour.get("samples_2d") or ()
    if points:
        return (
            sum(float(point[0]) for point in points) / len(points),
            sum(float(point[1]) for point in points) / len(points),
        )
    return 0.0, 0.0


def _descriptor(contour: Mapping[str, Any]) -> dict[str, float]:
    center = _centroid(contour)
    area = abs(float(contour.get("area") or 0.0))
    perimeter = float(
        contour.get("perimeter")
        or contour.get("length_exact")
        or contour.get("length_sampled")
        or contour.get("length")
        or 0.0
    )
    nesting = float(contour.get("nesting_depth") or contour.get("depth") or 0.0)
    return {
        "area": area,
        "perimeter": perimeter,
        "x": center[0],
        "y": center[1],
        "nesting": nesting,
    }


def _cost(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    area_scale = max(left["area"], right["area"], 1.0e-12)
    length_scale = max(sqrt(area_scale), 1.0e-6)
    perimeter_scale = max(left["perimeter"], right["perimeter"], length_scale)
    return (
        abs(left["area"] - right["area"]) / area_scale
        + hypot(left["x"] - right["x"], left["y"] - right["y"]) / length_scale
        + 0.35 * abs(left["perimeter"] - right["perimeter"]) / perimeter_scale
        + 0.75 * abs(left["nesting"] - right["nesting"])
    )


def _hungarian(costs: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    """Return minimum-cost square assignment as row/column pairs."""
    size = len(costs)
    if size == 0:
        return []
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)
    for row in range(1, size + 1):
        p[0] = row
        minv = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        col0 = 0
        while True:
            used[col0] = True
            row0 = p[col0]
            delta = float("inf")
            col1 = 0
            for col in range(1, size + 1):
                if used[col]:
                    continue
                current = costs[row0 - 1][col - 1] - u[row0] - v[col]
                if current < minv[col]:
                    minv[col] = current
                    way[col] = col0
                if minv[col] < delta:
                    delta = minv[col]
                    col1 = col
            for col in range(size + 1):
                if used[col]:
                    u[p[col]] += delta
                    v[col] -= delta
                else:
                    minv[col] -= delta
            col0 = col1
            if p[col0] == 0:
                break
        while True:
            col1 = way[col0]
            p[col0] = p[col1]
            col0 = col1
            if col0 == 0:
                break
    return [(p[col] - 1, col - 1) for col in range(1, size + 1) if p[col]]


def _station_contours(station: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    section = station.get("section")
    source = section if isinstance(section, Mapping) else station
    contours = source.get("contours") or []
    return [contour for contour in contours if contour.get("closed", True)]


def track_section_contours_rdescriptor(
    *,
    sections: Sequence[Mapping[str, Any]],
    maximum_match_cost: float = 1.5,
    topology_area_tolerance: float = 0.2,
) -> dict[str, Any]:
    """Track contours across ordered stations without forcing one global loft.

    The output distinguishes continuation, birth, death, split and merge
    events. Its summary reports whether topology changes make one global loft
    unsafe. It is hypothesis evidence and must not be copied into the raw BREP
    summary.
    """
    if len(sections) < 2:
        raise ValueError("sections must contain at least two ordered stations")
    if maximum_match_cost <= 0.0:
        raise ValueError("maximum_match_cost must be positive")
    if not 0.0 <= topology_area_tolerance < 1.0:
        raise ValueError("topology_area_tolerance must be in [0, 1)")

    tracks: dict[str, list[dict[str, Any]]] = {}
    events: list[dict[str, Any]] = []
    previous = _station_contours(sections[0])
    previous_tracks: dict[int, str] = {}
    next_track = 0
    for index, _contour in enumerate(previous):
        track_id = f"contour_track:{next_track}"
        next_track += 1
        previous_tracks[index] = track_id
        tracks[track_id] = [{"station": 0, "contour": index}]
        events.append({"station": 0, "type": "birth", "tracks": [track_id]})

    for station_index in range(1, len(sections)):
        current = _station_contours(sections[station_index])
        left = [_descriptor(contour) for contour in previous]
        right = [_descriptor(contour) for contour in current]
        size = max(len(left), len(right))
        padded = [
            [
                (
                    _cost(left[row], right[col])
                    if row < len(left) and col < len(right)
                    else maximum_match_cost
                )
                for col in range(size)
            ]
            for row in range(size)
        ]
        matched_left: set[int] = set()
        matched_right: set[int] = set()
        current_tracks: dict[int, str] = {}
        for left_index, right_index in _hungarian(padded):
            if left_index >= len(left) or right_index >= len(right):
                continue
            score = _cost(left[left_index], right[right_index])
            if score > maximum_match_cost:
                continue
            track_id = previous_tracks[left_index]
            tracks[track_id].append(
                {
                    "station": station_index,
                    "contour": right_index,
                    "match_cost": score,
                    "confidence": max(0.0, 1.0 - score / maximum_match_cost),
                }
            )
            current_tracks[right_index] = track_id
            matched_left.add(left_index)
            matched_right.add(right_index)
            events.append(
                {
                    "station": station_index,
                    "type": "continue",
                    "tracks": [track_id],
                    "match_cost": score,
                }
            )

        unmatched_left = sorted(set(range(len(left))) - matched_left)
        unmatched_right = sorted(set(range(len(right))) - matched_right)

        # Area-conserving local groups expose likely split/merge hypotheses.
        consumed_left: set[int] = set()
        consumed_right: set[int] = set()
        for source_index in unmatched_left:
            source = left[source_index]
            for pair in combinations(unmatched_right, 2):
                total = right[pair[0]]["area"] + right[pair[1]]["area"]
                if (
                    source["area"]
                    and abs(total - source["area"]) / source["area"]
                    <= topology_area_tolerance
                ):
                    parent = previous_tracks[source_index]
                    children = []
                    for right_index in pair:
                        track_id = f"contour_track:{next_track}"
                        next_track += 1
                        current_tracks[right_index] = track_id
                        tracks[track_id] = [
                            {"station": station_index, "contour": right_index}
                        ]
                        children.append(track_id)
                    events.append(
                        {
                            "station": station_index,
                            "type": "split",
                            "tracks": [parent, *children],
                        }
                    )
                    consumed_left.add(source_index)
                    consumed_right.update(pair)
                    break

        for target_index in unmatched_right:
            if target_index in consumed_right:
                continue
            target = right[target_index]
            available_left = [
                index for index in unmatched_left if index not in consumed_left
            ]
            for pair in combinations(available_left, 2):
                total = left[pair[0]]["area"] + left[pair[1]]["area"]
                if (
                    target["area"]
                    and abs(total - target["area"]) / target["area"]
                    <= topology_area_tolerance
                ):
                    track_id = f"contour_track:{next_track}"
                    next_track += 1
                    current_tracks[target_index] = track_id
                    tracks[track_id] = [
                        {"station": station_index, "contour": target_index}
                    ]
                    parents = [previous_tracks[index] for index in pair]
                    events.append(
                        {
                            "station": station_index,
                            "type": "merge",
                            "tracks": [*parents, track_id],
                        }
                    )
                    consumed_left.update(pair)
                    consumed_right.add(target_index)
                    break

        for left_index in unmatched_left:
            if left_index not in consumed_left:
                events.append(
                    {
                        "station": station_index,
                        "type": "death",
                        "tracks": [previous_tracks[left_index]],
                    }
                )
        for right_index in unmatched_right:
            if right_index in consumed_right:
                continue
            track_id = f"contour_track:{next_track}"
            next_track += 1
            current_tracks[right_index] = track_id
            tracks[track_id] = [{"station": station_index, "contour": right_index}]
            events.append(
                {"station": station_index, "type": "birth", "tracks": [track_id]}
            )

        previous = current
        previous_tracks = current_tracks

    return {
        "schema": "simplecadapi.section_contour_tracks.v1",
        "station_count": len(sections),
        "tracks": [
            {"id": track_id, "samples": samples} for track_id, samples in tracks.items()
        ],
        "events": events,
        "summary": {
            "track_count": len(tracks),
            "birth_count": sum(event["type"] == "birth" for event in events),
            "death_count": sum(event["type"] == "death" for event in events),
            "split_count": sum(event["type"] == "split" for event in events),
            "merge_count": sum(event["type"] == "merge" for event in events),
            "single_loft_safe": not any(
                event["type"] in {"split", "merge", "birth", "death"}
                and event["station"] > 0
                for event in events
            ),
        },
    }


__all__ = ["track_section_contours_rdescriptor"]

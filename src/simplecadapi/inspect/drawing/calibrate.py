"""Scale calibration and measurement: the trust foundation for derived numbers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from math import hypot
from pathlib import Path
from typing import Any, Mapping, Sequence

_BEZIER_SAMPLES = 24


@dataclass(frozen=True)
class DrawingCalibration:
    """Consensus mm-per-pt scale fitted from independent known dimensions.

    ``accepted`` requires at least ``min_pairs`` pairs and all per-pair
    scales agreeing within ``relative_tolerance``. A calibration that failed
    must never be used to produce derived numbers: fix the anchor selection
    or the measurement instead.
    """

    pair_count: int
    scale_mm_per_pt: float
    scales_per_pair: list[float]
    max_relative_deviation: float
    relative_tolerance: float
    min_pairs: int
    accepted: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path, *, indent: int = 2) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=indent), encoding="utf-8")
        return output


@dataclass(frozen=True)
class DrawingMeasurements:
    """Point-pair and stroke-length measurements with optional mm conversion.

    Every entry keeps its native ``length_pt``; ``length_mm`` is populated
    only when a calibration is supplied. Millimetre values derived here are
    "inferred"-grade claims: they must be cross-checked against annotated
    dimensions before they harden into facts.
    """

    measurement_count: int
    scale_mm_per_pt: float | None
    measurements: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path, *, indent: int = 2) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=indent), encoding="utf-8")
        return output


def _pair_scale(pair: Mapping[str, Any]) -> float:
    if "length_pt" in pair:
        length_pt = float(pair["length_pt"])
    elif "a" in pair and "b" in pair:
        point_a, point_b = pair["a"], pair["b"]
        if len(point_a) != 2 or len(point_b) != 2:
            raise ValueError(f"pair endpoints must be [x, y], got {pair!r}")
        length_pt = hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])
    else:
        raise ValueError(
            f"each pair needs 'length_pt' or both 'a' and 'b', got {pair!r}"
        )
    if "dim_mm" not in pair:
        raise ValueError(f"each pair needs 'dim_mm', got {pair!r}")
    if length_pt <= 0 or float(pair["dim_mm"]) <= 0:
        raise ValueError(f"pair lengths must be positive, got {pair!r}")
    return float(pair["dim_mm"]) / length_pt


def calibrate_drawing_scale_rcalibration(
    pairs: Sequence[Mapping[str, Any]],
    *,
    relative_tolerance: float = 0.01,
    min_pairs: int = 3,
) -> DrawingCalibration:
    """Fit one mm-per-pt scale from independent known dimensions and verify it.

    Each pair is either ``{"a": [x, y], "b": [x, y], "dim_mm": v}`` (two
    display-space points of a feature whose real dimension is known) or
    ``{"length_pt": v, "dim_mm": v}``. The consensus scale is the mean of the
    per-pair scales; ``accepted`` is true only with at least ``min_pairs``
    pairs whose scales agree within ``relative_tolerance``. Calibrate per
    view: detail views are drawn at their own scales (1:1, 2:1, 4:1) and one
    global factor is wrong for them by construction. Use dimensions that are
    geometrically independent; two deviations of the same chain are not two
    anchors.
    """
    if relative_tolerance <= 0:
        raise ValueError("relative_tolerance must be positive")
    if min_pairs < 1:
        raise ValueError("min_pairs must be at least 1")
    if not pairs:
        raise ValueError("at least one calibration pair is required")

    scales = [_pair_scale(pair) for pair in pairs]
    mean_scale = sum(scales) / len(scales)
    max_deviation = max(abs(scale - mean_scale) / mean_scale for scale in scales)
    return DrawingCalibration(
        pair_count=len(pairs),
        scale_mm_per_pt=mean_scale,
        scales_per_pair=scales,
        max_relative_deviation=max_deviation,
        relative_tolerance=relative_tolerance,
        min_pairs=min_pairs,
        accepted=len(pairs) >= min_pairs and max_deviation <= relative_tolerance,
    )


def _polyline_length(points: Sequence[Sequence[float]]) -> float:
    return sum(
        hypot(points[index + 1][0] - points[index][0],
              points[index + 1][1] - points[index][1])
        for index in range(len(points) - 1)
    )


def _bezier_length(points: Sequence[Sequence[float]]) -> float:
    """Approximate one cubic Bezier length by uniform de Casteljau sampling."""
    if len(points) != 4:
        return _polyline_length(points)
    p0, p1, p2, p3 = ((point[0], point[1]) for point in points)
    sampled: list[tuple[float, float]] = []
    for step in range(_BEZIER_SAMPLES + 1):
        t = step / _BEZIER_SAMPLES
        u = 1.0 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        sampled.append((x, y))
    return _polyline_length(sampled)


def measure_drawing_rmeasurements(
    selections: Sequence[Mapping[str, Any]],
    *,
    calibration: Mapping[str, Any] | None = None,
) -> DrawingMeasurements:
    """Measure display-space geometry and optionally convert to millimetres.

    Selections are self-contained: ``{"kind": "distance", "a": [x, y],
    "b": [x, y], "label": "..."}`` measures the Euclidean distance between
    two points; ``{"kind": "stroke_length", "points": [[x, y], ...],
    "label": "...", "stroke_kind": "line"|"bezier"|"polyline"}`` measures the
    polyline through ``points`` (pass the ``points`` of one stroke from
    ``extract_drawing_primitives_rstrokes``; ``bezier`` control polygons are
    sampled, not chorded). ``calibration`` is the dict returned by
    :func:`calibrate_drawing_scale_rcalibration`; without it ``length_mm``
    stays ``null``. Only pass a calibration whose ``accepted`` is true.
    """
    scale: float | None = None
    if calibration is not None:
        scale = float(calibration["scale_mm_per_pt"])

    measurements: list[dict[str, Any]] = []
    for selection in selections:
        label = str(selection.get("label", ""))
        kind = selection.get("kind")
        if kind == "distance":
            point_a, point_b = selection["a"], selection["b"]
            if len(point_a) != 2 or len(point_b) != 2:
                raise ValueError(
                    f"distance endpoints must be [x, y], got {selection!r}"
                )
            length_pt = hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])
        elif kind == "stroke_length":
            points = selection["points"]
            if len(points) < 2:
                raise ValueError(f"stroke_length needs at least 2 points, got {selection!r}")
            stroke_kind = selection.get("stroke_kind", "polyline")
            if stroke_kind == "bezier":
                length_pt = _bezier_length(points)
            else:
                length_pt = _polyline_length(points)
        else:
            raise ValueError(
                f"selection kind must be 'distance' or 'stroke_length', got {selection!r}"
            )
        measurements.append(
            {
                "label": label,
                "kind": kind,
                "length_pt": length_pt,
                "length_mm": length_pt * scale if scale is not None else None,
            }
        )

    return DrawingMeasurements(
        measurement_count=len(measurements),
        scale_mm_per_pt=scale,
        measurements=measurements,
    )

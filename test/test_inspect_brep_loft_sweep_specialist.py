from __future__ import annotations

import math

import numpy as np

from simplecadapi.inspect.brep.feature_hints.loft_sweep_specialist import (
    align_section_sequence,
)
from simplecadapi.inspect.brep.feature_hints.path_recovery import recover_path


def _section_family(origins):
    return {
        "stations": [
            {
                "station": index / max(len(origins) - 1, 1),
                "plane": {"origin": list(origin), "normal": [0.0, 0.0, 1.0]},
                "contours": [],
            }
            for index, origin in enumerate(origins)
        ]
    }


def test_path_recovery_prefers_line_when_all_station_origins_are_collinear():
    report = recover_path(
        _section_family([(0.0, 0.0, 0.0), (0.0, 0.0, 4.0), (0.0, 0.0, 9.0)]),
        linear_tolerance=1.0e-6,
    )

    assert report["status"] == "recovered"
    assert report["recommended"]["curve_type"] == "line"
    assert report["recommended"]["maximum_error"] < 1.0e-9


def test_path_recovery_prefers_arc_over_chord_for_curved_station_origins():
    origins = [
        (10.0 * math.cos(angle), 10.0 * math.sin(angle), 0.0)
        for angle in np.linspace(0.0, math.pi / 2.0, 7)
    ]
    report = recover_path(
        _section_family(origins),
        linear_tolerance=1.0e-6,
    )

    assert report["recommended"]["curve_type"] == "circular_arc"
    assert report["recommended"]["maximum_error"] < 1.0e-8


def test_global_section_alignment_removes_direction_and_seam_changes():
    angles = np.linspace(0.0, 2.0 * math.pi, 48, endpoint=False)
    radius = 1.0 + 0.18 * np.cos(3.0 * angles) + 0.07 * np.sin(angles)
    base = np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])
    samples = [
        base,
        np.roll(base, 9, axis=0),
        np.roll(base[::-1], 17, axis=0),
        np.roll(base, 25, axis=0),
    ]
    family = {
        "stations": [
            {
                "station": index / 3.0,
                "plane": {
                    "origin": [0.0, 0.0, float(index)],
                    "normal": [0, 0, 1],
                },
                "contours": [
                    {
                        "closed": True,
                        "samples_2d": points.tolist(),
                        "area": 1.0,
                        "length_exact": 1.0,
                    }
                ],
            }
            for index, points in enumerate(samples)
        ]
    }

    report = align_section_sequence(family, sample_count=48)

    assert report["status"] == "aligned"
    assert report["station_count"] == 4
    assert report["global_cost"] < 0.1
    assert max(
        item["normalized_rms_error_to_start"] for item in report["profiles"]
    ) < 0.04
    assert any(item["reversed"] for item in report["profiles"])

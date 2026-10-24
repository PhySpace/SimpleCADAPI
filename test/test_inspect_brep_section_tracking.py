from __future__ import annotations

from simplecadapi.inspect.brep.section_tracking import (
    track_section_contours_rdescriptor,
)


def _section(area: float, length: float, x: float = 0.0):
    return {
        "contours": [
            {
                "closed": True,
                "area": area,
                "length_exact": length,
                "samples_2d": [[x - 1.0, -1.0], [x + 1.0, 1.0]],
            }
        ]
    }


def test_section_tracking_uses_inspector_length_exact_and_keeps_one_track():
    report = track_section_contours_rdescriptor(
        sections=[_section(4.0, 8.0), _section(4.2, 8.2, 0.05)]
    )

    assert report["summary"]["track_count"] == 1
    assert report["summary"]["single_loft_safe"] is True
    continuation = next(item for item in report["events"] if item["type"] == "continue")
    assert continuation["match_cost"] < 0.2


def test_section_tracking_reports_split_instead_of_forcing_one_loft():
    report = track_section_contours_rdescriptor(
        sections=[
            _section(8.0, 12.0),
            {
                "contours": [
                    {"closed": True, "area": 4.0, "length_exact": 8.0},
                    {"closed": True, "area": 4.0, "length_exact": 8.0},
                ]
            },
        ],
        maximum_match_cost=0.1,
    )

    assert report["summary"]["split_count"] == 1
    assert report["summary"]["single_loft_safe"] is False

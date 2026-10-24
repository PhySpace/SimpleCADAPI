"""Non-circular holes remain holes in the computational-geometry catalog."""

from __future__ import annotations

import math

import pytest

import simplecadapi as scad
from simplecadapi.inspect import brep


def _base():
    return scad.make_box_rsolid(
        width=50.0,
        height=36.0,
        depth=16.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )


def _profile_tool(points, *, z: float, depth: float):
    wire = scad.make_polyline_rwire(
        points=[(x, y, z) for x, y in points],
        closed=True,
    )
    face = scad.make_face_from_wire_rface(wire=wire, normal=(0.0, 0.0, 1.0))
    return scad.extrude_rsolid(
        profile=face,
        direction=(0.0, 0.0, 1.0),
        distance=depth,
    )


def _cut_profile(points, *, z: float = -1.0, depth: float = 18.0):
    return scad.cut_rsolid(
        _base(),
        _profile_tool(points, z=z, depth=depth),
        skip_non_intersecting=False,
    )


def _obround(length: float = 22.0, width: float = 8.0):
    radius = width / 2.0
    half_straight = (length - width) / 2.0
    result = []
    for degrees in range(-90, 91, 12):
        radians = math.radians(degrees)
        result.append(
            (
                half_straight + radius * math.cos(radians),
                radius * math.sin(radians),
            )
        )
    for degrees in range(90, 271, 12):
        radians = math.radians(degrees)
        result.append(
            (
                -half_straight + radius * math.cos(radians),
                radius * math.sin(radians),
            )
        )
    return result


def _keyhole():
    result = [(-5.196, 1.0), (-8.0, -12.0), (8.0, -12.0), (5.196, 1.0)]
    for degrees in range(-30, 211, 12):
        radians = math.radians(degrees)
        result.append((6.0 * math.cos(radians), 4.0 + 6.0 * math.sin(radians)))
    return result


def _freeform():
    return [
        (-10.0, -1.0),
        (-8.0, -6.0),
        (-3.0, -7.0),
        (1.0, -5.5),
        (5.0, -7.0),
        (10.0, -3.0),
        (8.5, 2.0),
        (5.0, 5.5),
        (0.5, 7.0),
        (-4.0, 5.0),
        (-8.5, 4.0),
    ]


def _forms(shape):
    report = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=shape.wrapped,
        feature_kinds=("hole",),
        max_hints=50,
    )
    return [
        hint["geometry"]["form"]
        for hint in report["hints"]
        if hint["kind"] == "hole_region_candidate"
    ]


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        ([(-9.0, -5.0), (9.0, -5.0), (9.0, 5.0), (-9.0, 5.0)], "rectangular"),
        (
            [
                (
                    7.0 * math.cos(math.radians(30.0 + index * 60.0)),
                    7.0 * math.sin(math.radians(30.0 + index * 60.0)),
                )
                for index in range(6)
            ],
            "polygonal",
        ),
        (_obround(), "obround_through"),
        (_keyhole(), "d_or_keyhole"),
        (_freeform(), "freeform_profile"),
    ],
)
def test_closed_non_circular_through_profiles_are_holes(points, expected):
    assert expected in _forms(_cut_profile(points))


def test_obround_blind_hole_has_bottom_and_depth():
    shape = _cut_profile(_obround(), z=6.0, depth=11.0)
    report = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=shape.wrapped,
        feature_kinds=("hole",),
        max_hints=20,
    )
    hint = next(
        item
        for item in report["hints"]
        if item["geometry"].get("form") == "obround_blind"
    )
    assert hint["geometry"]["bottom_face_id"].startswith("face:")
    assert hint["geometry"]["exit_face_id"] is None
    assert hint["geometry"]["total_depth"] == pytest.approx(10.0)


def test_non_circular_step_profiles_form_one_profile_stepped_hole():
    lower = _profile_tool(_obround(16.0, 7.0), z=4.0, depth=7.2)
    body = scad.cut_rsolid(_base(), lower, skip_non_intersecting=False)
    upper = _profile_tool(_obround(24.0, 12.0), z=10.9, depth=6.1)
    shape = scad.cut_rsolid(body, upper, skip_non_intersecting=False)
    report = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=shape.wrapped,
        feature_kinds=("hole",),
        max_hints=20,
    )
    hints = [
        item
        for item in report["hints"]
        if item["geometry"].get("form") == "profile_stepped"
    ]
    assert len(hints) == 1
    assert len(hints[0]["geometry"]["segments"]) == 2
    assert hints[0]["geometry"]["profile_family"] == "non_circular"


def test_open_slot_is_not_promoted_to_hole():
    cutter = scad.make_box_rsolid(
        width=28.0,
        height=10.0,
        depth=9.0,
        bottom_face_center=(18.0, 0.0, 8.0),
    )
    shape = scad.cut_rsolid(_base(), cutter, skip_non_intersecting=False)
    assert _forms(shape) == []

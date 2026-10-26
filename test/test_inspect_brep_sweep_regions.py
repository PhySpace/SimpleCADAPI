from __future__ import annotations

import math

import simplecadapi as scad
from simplecadapi.inspect import brep


def _sweep_hints(shape):
    report = brep.inspect_manufacturing_hints_rdescriptor(
        shape.wrapped, feature_kinds=("sweep",), max_hints=50
    )
    return [
        item for item in report["hints"] if item["kind"] == "sweep_region_candidate"
    ]


def test_twisted_sweep_is_identified_from_rigid_rotating_sections():
    profile = scad.make_rectangle_rface(4.0, 2.0)
    shape = scad.twisted_sweep_rsolid(profile, distance=9.0, twist_angle=70.0)

    hint = next(
        item
        for item in _sweep_hints(shape)
        if item["geometry"]["form"] == "twisted_sweep"
    )
    assert hint["geometry"]["coverage"] == "whole_body"
    assert abs(hint["geometry"]["twist_angle_degrees"]) > 60.0
    assert hint["geometry"]["section_family"]["station_count"] >= 3
    specialist = hint["geometry"]["specialist_analysis"]
    assert specialist["loft_control_mode"] == "path"
    assert specialist["path_profile_mode"] == "rigid"
    assert specialist["spine"]["status"] == "recovered"


def test_curved_path_sweep_is_identified_but_straight_sweep_stays_extrusion():
    profile = scad.make_rectangle_rface(2.0, 1.0)
    arc = scad.make_three_point_arc_rwire((0, 0, 0), (3, 0, 3), (6, 0, 0))
    curved = scad.sweep_rsolid(profile, arc, is_frenet=True)
    assert any(
        item["geometry"]["form"] == "whole_body_path_sweep"
        for item in _sweep_hints(curved)
    )

    line = scad.make_segment_rwire((0, 0, 0), (0, 0, 6))
    straight = scad.sweep_rsolid(profile, line)
    assert _sweep_hints(straight) == []
    extrusion = brep.inspect_manufacturing_hints_rdescriptor(
        straight.wrapped, feature_kinds=("extrusion",)
    )
    assert any(
        item["kind"] == "extrusion_region_candidate" for item in extrusion["hints"]
    )


def test_helical_sweep_requires_measured_constant_radius_and_pitch():
    profile = scad.make_circle_rwire((3.0, 0.0, 0.0), 0.35, normal=(0, 1, 0))
    shape = scad.helical_sweep_rsolid(profile, pitch=2.0, height=5.0, radius=3.0)

    hint = next(
        item
        for item in _sweep_hints(shape)
        if item["geometry"]["form"] == "helical_sweep"
    )
    fit = hint["geometry"]["helix_fit"]
    assert fit["turn_count"] > 2.0
    assert 1.5 < fit["pitch"] < 2.5


def test_scaled_profiles_are_not_mislabeled_as_sweep():
    first = scad.make_rectangle_rwire(8.0, 4.0, center=(0.0, 0.0, 0.0))
    second = scad.make_rectangle_rwire(3.0, 7.0, center=(1.0, 0.5, 10.0))
    shape = scad.loft_rsolid([first, second])
    assert _sweep_hints(shape) == []


def test_matching_end_caps_do_not_hide_variable_middle_sections():
    def circle(x, z, slope):
        length = math.hypot(1.0, slope)

        def point(angle):
            return (
                x - 10.0 * slope / length * math.sin(angle),
                10.0 * math.cos(angle),
                z + 10.0 / length * math.sin(angle),
            )

        edges = []
        for index in range(4):
            angle = -3.0 * math.pi / 4.0 + index * math.pi / 2.0
            edges.append(
                scad.make_three_point_arc_redge(
                    start=point(angle),
                    middle=point(angle + math.pi / 4.0),
                    end=point(angle + math.pi / 2.0),
                )
            )
        return scad.make_wire_from_edges_rwire(edges=edges)

    def rectangle(x):
        return scad.make_polyline_rwire(
            points=[
                (x - 15.0, -20.0, 0.0),
                (x + 15.0, -20.0, 0.0),
                (x + 15.0, 20.0, 0.0),
                (x - 15.0, 20.0, 0.0),
            ],
            closed=True,
        )

    profiles = [
        rectangle(-135),
        circle(-55, 180, 0.8),
        circle(55, 180, -0.8),
        rectangle(135),
    ]
    path = scad.make_interpolated_spline_rwire(
        points=[
            (-135, 0, 0),
            (-100, 0, 100),
            (-55, 0, 180),
            (0, 0, 190),
            (55, 0, 180),
            (100, 0, 100),
            (135, 0, 0),
        ]
    )
    shape = scad.loft_multisection_rsolid(profiles=profiles, path=path)
    report = brep.inspect_manufacturing_hints_rdescriptor(
        shape.wrapped, feature_kinds=("loft", "sweep")
    )

    assert any(item["kind"] == "loft_region_candidate" for item in report["hints"])
    assert not any(item["kind"] == "sweep_region_candidate" for item in report["hints"])
    assert any(
        item["code"] == "sweep.variable_section_spacing"
        for item in report["diagnostics"]
    )
    catalog = brep.inspect_geometric_features_rdescriptor(
        shape.wrapped, feature_kinds=("loft", "sweep")
    )
    feature = catalog["features"][0]
    assert feature["category"] == "loft"
    assert feature["reconstruction"]["recommended_operation"]["api"] == (
        "loft_multisection_rsolid"
    )
    assert feature["reconstruction"]["spine"]["source"] == (
        "averaged_longitudinal_guides"
    )

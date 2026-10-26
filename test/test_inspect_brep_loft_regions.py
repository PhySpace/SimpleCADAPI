from __future__ import annotations

import simplecadapi as scad
from simplecadapi.inspect import brep
from simplecadapi.inspect.brep.feature_hints import section_families


def _loft_hints(shape):
    report = brep.inspect_manufacturing_hints_rdescriptor(
        shape.wrapped, feature_kinds=("loft",), max_hints=50
    )
    return [item for item in report["hints"] if item["kind"] == "loft_region_candidate"]


def test_scaled_rectangles_are_whole_body_profile_loft_with_actual_sections():
    first = scad.make_rectangle_rwire(8.0, 4.0, center=(0.0, 0.0, 0.0))
    second = scad.make_rectangle_rwire(3.0, 7.0, center=(1.0, 0.5, 10.0))
    shape = scad.loft_rsolid([first, second])

    hint = next(
        item
        for item in _loft_hints(shape)
        if item["geometry"]["form"] == "whole_body_profile_loft"
    )
    geometry = hint["geometry"]
    assert geometry["coverage"] == "whole_body"
    assert geometry["region_role"] == "neutral"
    assert geometry["section_family"]["station_count"] >= 3
    assert geometry["section_family"]["tracking"]["summary"]["single_loft_safe"]
    assert geometry["variation_law"] in {"area_and_shape", "area", "shape"}
    assert geometry["specialist_analysis"]["loft_control_mode"] in {
        "sections_only",
        "path",
    }
    assert geometry["specialist_analysis"]["section_alignment"]["status"] == "aligned"


def test_point_terminal_is_reported_as_point_loft():
    base = scad.make_rectangle_rwire(6.0, 4.0, center=(0.0, 0.0, 0.0))
    apex = scad.make_point_rvertex(0.5, 0.25, 8.0)
    shape = scad.loft_rsolid([base, apex])

    hint = next(
        item
        for item in _loft_hints(shape)
        if item["geometry"]["form"] == "whole_body_point_loft"
    )
    assert hint["geometry"]["terminal_kind"] == "point"
    assert hint["geometry"]["terminal_mode"] == "end_point"
    assert hint["geometry"]["apex_vertex_id"].startswith("vertex:")


def test_double_point_terminal_loft_uses_internal_sections_and_guide_evidence():
    start = scad.make_point_rvertex(x=0.0, y=0.0, z=0.0)
    first = scad.make_rectangle_rwire(
        width=6.0,
        height=4.0,
        center=(0.0, 0.0, 3.0),
    )
    second = scad.make_rectangle_rwire(
        width=7.0,
        height=5.0,
        center=(0.5, 0.0, 6.0),
    )
    end = scad.make_point_rvertex(x=0.0, y=0.0, z=9.0)
    shape = scad.loft_rsolid(profiles=[start, first, second, end])

    hint = next(
        item
        for item in _loft_hints(shape)
        if item["geometry"]["form"] == "whole_body_point_loft"
    )

    assert hint["geometry"]["terminal_mode"] == "both_points"
    assert len(hint["geometry"]["apex_vertex_ids"]) == 2
    specialist = hint["geometry"]["specialist_analysis"]
    assert specialist["section_alignment"]["status"] == "aligned"
    assert specialist["guide_recovery_status"] == "recovered"
    assert specialist["guide_attachment_map"]
    assert specialist["boundary_conditions"]["start"]["type"] == "singular"
    assert specialist["boundary_conditions"]["end"]["type"] == "singular"


def test_prism_is_not_mislabeled_as_loft():
    shape = scad.make_box_rsolid(8.0, 5.0, 7.0)
    assert _loft_hints(shape) == []


def test_local_lofted_boss_and_cut_keep_support_out_of_highlight():
    base = scad.make_box_rsolid(30.0, 24.0, 10.0, bottom_face_center=(0.0, 0.0, 0.0))
    boss_start = scad.make_rectangle_rwire(10.0, 8.0, center=(0.0, 0.0, 10.0))
    boss_end = scad.make_rectangle_rwire(5.0, 3.0, center=(1.0, 0.0, 16.0))
    boss = scad.union_rsolid(
        base, scad.loft_rsolid([boss_start, boss_end]), clean=False
    )
    boss_hint = next(
        item
        for item in _loft_hints(boss)
        if item["geometry"]["form"] == "local_lofted_boss"
    )
    assert boss_hint["support_entity_ids"]
    assert not set(boss_hint["support_entity_ids"]) & set(
        boss_hint["highlight_entity_ids"]
    )

    cut_start = scad.make_rectangle_rwire(9.0, 7.0, center=(0.0, 0.0, 10.0))
    cut_end = scad.make_rectangle_rwire(4.0, 3.0, center=(0.5, 0.0, 4.0))
    cut = scad.cut_rsolid(base, scad.loft_rsolid([cut_start, cut_end]))
    cut_hint = next(
        item
        for item in _loft_hints(cut)
        if item["geometry"]["form"] == "local_lofted_cut"
    )
    assert cut_hint["geometry"]["region_role"] == "subtractive"


def test_whole_body_loft_rejects_incomplete_cap_wall_coverage_before_pairing(
    monkeypatch,
):
    class FakeModel:
        bodies = [object()]

    face_ids = [f"face:{index}" for index in range(5)]
    facts = {
        face_id: {"type": "PLANE", "normal": [0.0, 0.0, 1.0]}
        for face_id in face_ids
    }
    monkeypatch.setattr(section_families, "body_face_ids", lambda *_: face_ids)
    monkeypatch.setattr(
        section_families,
        "face_loops",
        lambda *_: [{"role": "outer"}],
    )
    monkeypatch.setattr(section_families, "_wall_ids", lambda *_: ["face:4"])
    monkeypatch.setattr(
        section_families,
        "entity_ids",
        lambda *_: (_ for _ in ()).throw(AssertionError("pairing must be skipped")),
    )

    assert (
        section_families.whole_body_section_families(
            FakeModel(),
            facts,
            {"linear": 1.0e-6, "angular_degrees": 0.5},
        )
        == []
    )


def _rectangle_points(scale: float, z: float):
    return [
        (-8.0 * scale, -5.0 * scale, z),
        (8.0 * scale, -5.0 * scale, z),
        (8.0 * scale, 5.0 * scale, z),
        (-8.0 * scale, 5.0 * scale, z),
    ]


def _loft_contract(shape):
    report = brep.inspect_geometric_features_rdescriptor(
        shape.wrapped, feature_kinds=("loft",)
    )
    feature = next(
        item for item in report["features"] if item["category"] == "loft"
    )
    return feature["reconstruction"]


def test_two_section_frustum_with_bilinear_sides_is_a_native_ruled_loft():
    shape = scad.loft_rsolid(
        [
            scad.make_polyline_rwire(points=_rectangle_points(1.0, 0.0), closed=True),
            scad.make_polyline_rwire(points=_rectangle_points(0.65, 16.0), closed=True),
        ]
    )

    contract = _loft_contract(shape)

    assert contract["interpolation"] == "ruled"
    assert contract["reconstruction_support"] == "native"
    assert contract["exactness"] == "tolerance_fit"
    for endpoint in ("start", "end"):
        condition = contract["boundary_conditions"][endpoint]
        assert condition["type"] == "implied_by_ruled"
        assert condition["measured_type"] == "fitted_direction"
    assert contract["operation_candidates"][0]["capability"] == "native"


def test_three_section_smooth_polygon_loft_is_not_called_ruled():
    shape = scad.loft_rsolid(
        [
            scad.make_polyline_rwire(points=_rectangle_points(1.0, 0.0), closed=True),
            scad.make_polyline_rwire(points=_rectangle_points(0.5, 8.0), closed=True),
            scad.make_polyline_rwire(points=_rectangle_points(0.9, 16.0), closed=True),
        ]
    )

    contract = _loft_contract(shape)

    assert contract["interpolation"] == "smooth"
    assert contract["reconstruction_support"] == "emulated"
    assert {
        condition["type"] for condition in contract["boundary_conditions"].values()
    } != {"implied_by_ruled"}


def test_path_constrained_variable_sections_recommend_path_loft():
    from simplecadapi.inspect.brep.reconstruction_contract import build_reconstruction_contract

    contract = build_reconstruction_contract(
        category="loft",
        geometry={
            "section_family": {"stations": [{}, {}]},
            "specialist_analysis": {
                "construction_strategy": "path_constrained",
                "result_kind": "solid",
                "spine": {"recommended": {"curve_type": "BSPLINE"}},
                "boundary_conditions": {},
            },
        },
    )
    assert contract["recommended_operation"]["api"] == "loft_multisection_rsolid"
    assert contract["reconstruction_support"] == "native"
    assert contract["exactness"] == "tolerance_fit"

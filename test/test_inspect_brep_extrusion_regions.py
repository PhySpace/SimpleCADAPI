"""Local constant-section regions are extrusion geometry, not whole-body only."""

from __future__ import annotations

import pytest
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Compound

import simplecadapi as scad
from simplecadapi.inspect import brep
from simplecadapi.inspect.brep.feature_hints.profiles import (
    face_loops,
    pair_loop_sets,
)


def _base(*, depth: float = 10.0):
    return scad.make_box_rsolid(
        width=50.0,
        height=36.0,
        depth=depth,
        bottom_face_center=(0.0, 0.0, 0.0),
    )


def _forms(shape, *, include_holes: bool = False):
    kinds = ("hole", "extrusion") if include_holes else ("extrusion",)
    report = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=shape.wrapped,
        feature_kinds=kinds,
        max_hints=50,
    )
    return [
        hint for hint in report["hints"] if hint["kind"] == "extrusion_region_candidate"
    ]


def test_whole_body_extrusion_is_explicitly_one_subtype():
    hints = _forms(_base(depth=16.0))
    assert hints
    assert all(item["geometry"]["form"] == "whole_body_prism" for item in hints)


def test_local_boss_highlights_only_the_local_region():
    boss = scad.make_box_rsolid(
        width=18.0,
        height=12.0,
        depth=9.2,
        bottom_face_center=(0.0, 0.0, 9.8),
    )
    shape = scad.union_rsolid(_base(), boss, clean=False)
    hint = next(
        item for item in _forms(shape) if item["geometry"]["form"] == "local_boss"
    )
    assert len(hint["highlight_entity_ids"]) == 5
    assert len(hint["highlight_entity_ids"]) < len(
        brep.index_shape_rbrepmodel(shape=shape.wrapped).faces
    )


def test_local_boss_does_not_require_complete_support_and_top_face_areas_to_match():
    boss = scad.make_box_rsolid(
        width=18.0,
        height=12.0,
        depth=9.2,
        bottom_face_center=(0.0, 0.0, 9.8),
    )
    shape = scad.union_rsolid(_base(), boss, clean=False)
    hint = next(
        item for item in _forms(shape) if item["geometry"]["form"] == "local_boss"
    )
    area_evidence = next(
        item
        for item in hint["evidence"]
        if item["code"] == "extrusion.face_area_similarity"
    )

    assert area_evidence["required"] is False
    assert area_evidence["observed"]["support_face_area"] != pytest.approx(
        area_evidence["observed"]["terminal_face_area"]
    )


def test_loop_pairing_ignores_cycle_start_orientation_and_split_collinear_edges():
    first_wire = scad.make_polyline_rwire(
        points=[
            (-5.0, -3.0, 0.0),
            (0.0, -3.0, 0.0),
            (5.0, -3.0, 0.0),
            (5.0, 3.0, 0.0),
            (-5.0, 3.0, 0.0),
        ],
        closed=True,
    )
    second_wire = scad.make_polyline_rwire(
        points=[
            (5.0, 3.0, 8.0),
            (5.0, -3.0, 8.0),
            (-5.0, -3.0, 8.0),
            (-5.0, 3.0, 8.0),
        ],
        closed=True,
    )
    first_face = scad.make_face_from_wire_rface(wire=first_wire, normal=(0.0, 0.0, 1.0))
    second_face = scad.make_face_from_wire_rface(
        wire=second_wire, normal=(0.0, 0.0, 1.0)
    )
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, first_face.wrapped)
    builder.Add(compound, second_face.wrapped)
    model = brep.index_shape_rbrepmodel(shape=compound)
    first_face_id, second_face_id = [
        f"face:{index}" for index in range(len(model.faces))
    ]

    result = pair_loop_sets(
        face_loops(model, first_face_id),
        face_loops(model, second_face_id),
        transform="translation",
        linear_tolerance=1.0e-6,
        expected_direction=(0.0, 0.0, 1.0),
    )

    assert len(result["matches"]) == 1
    assert result["unmatched_first"] == []
    assert result["unmatched_second"] == []
    assert result["matches"][0]["maximum_deviation"] <= 1.0e-6


def test_thin_local_boss_is_classified_as_rib_or_web():
    rib = scad.make_box_rsolid(
        width=30.0,
        height=4.0,
        depth=12.2,
        bottom_face_center=(0.0, 0.0, 7.8),
    )
    shape = scad.union_rsolid(_base(depth=8.0), rib, clean=False)
    assert any(item["geometry"]["form"] == "rib_or_web" for item in _forms(shape))


def test_closed_local_recess_is_blind_pocket():
    cutter = scad.make_box_rsolid(
        width=24.0,
        height=16.0,
        depth=10.0,
        bottom_face_center=(0.0, 0.0, 7.0),
    )
    shape = scad.cut_rsolid(_base(depth=16.0), cutter, skip_non_intersecting=False)
    assert any(item["geometry"]["form"] == "blind_pocket" for item in _forms(shape))

    full_report = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=shape.wrapped,
        feature_kinds=("hole", "extrusion"),
        max_hints=50,
    )
    assert any(
        item["kind"] == "extrusion_region_candidate"
        and item["geometry"]["form"] == "blind_pocket"
        for item in full_report["hints"]
    )
    assert not any(
        item["kind"] == "hole_region_candidate" for item in full_report["hints"]
    )


def test_extrusion_section_evidence_contains_measured_brep_stations():
    hint = next(
        item
        for item in _forms(_base(depth=16.0))
        if item["geometry"]["form"] == "whole_body_prism"
    )
    consistency = hint["geometry"]["section_consistency"]

    assert consistency["stations"] == [0.25, 0.5, 0.75]
    assert [item["station"] for item in consistency["measurements"]] == [
        0.25,
        0.5,
        0.75,
    ]
    assert all(
        item["source"] == "actual_brep_section"
        and item["maximum_correspondence_error"] >= 0.0
        for item in consistency["measurements"]
    )


def test_boundary_connected_recess_is_open_slot_or_notch():
    cutter = scad.make_box_rsolid(
        width=28.0,
        height=10.0,
        depth=9.0,
        bottom_face_center=(18.0, 0.0, 8.0),
    )
    shape = scad.cut_rsolid(_base(depth=16.0), cutter, skip_non_intersecting=False)
    assert any(
        item["geometry"]["form"] == "open_slot_or_notch" for item in _forms(shape)
    )


def test_boundary_connected_through_cut_is_local_region():
    cutter = scad.make_box_rsolid(
        width=18.0,
        height=14.0,
        depth=18.0,
        bottom_face_center=(20.0, 0.0, -1.0),
    )
    shape = scad.cut_rsolid(_base(depth=16.0), cutter, skip_non_intersecting=False)
    assert any(
        item["geometry"]["form"] == "through_cut_region" for item in _forms(shape)
    )


def test_closed_negative_space_is_owned_by_hole_not_local_extrusion():
    cutter = scad.make_box_rsolid(
        width=18.0,
        height=10.0,
        depth=18.0,
        bottom_face_center=(0.0, 0.0, -1.0),
    )
    shape = scad.cut_rsolid(_base(depth=16.0), cutter, skip_non_intersecting=False)
    report = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=shape.wrapped,
        feature_kinds=("hole", "extrusion"),
        max_hints=50,
    )
    assert any(
        item["kind"] == "hole_region_candidate"
        and item["geometry"]["form"] == "rectangular"
        for item in report["hints"]
    )
    assert not any(
        item["kind"] == "extrusion_region_candidate"
        and item["geometry"]["form"] != "whole_body_prism"
        and set(item["entity_ids"])
        <= set(
            next(
                hole["entity_ids"]
                for hole in report["hints"]
                if hole["kind"] == "hole_region_candidate"
            )
        )
        for item in report["hints"]
    )

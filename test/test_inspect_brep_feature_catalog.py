"""Unified per-instance computational-geometry feature catalog contract."""

from __future__ import annotations

import math

from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Compound
import pytest

import simplecadapi as scad
from simplecadapi.inspect import brep


REQUIRED_FIELDS = {
    "feature_id",
    "category",
    "subtype",
    "display_name",
    "claim",
    "body_id",
    "entity_ids",
    "highlight_entity_ids",
    "support_entity_ids",
    "location",
    "dimensions",
    "profile",
    "relationships",
    "evidence",
    "confidence",
    "visuals",
    "limitations",
    "reconstruction",
    "target_sha256",
}


def _rectangular_through_hole():
    base = scad.make_box_rsolid(
        width=50.0,
        height=36.0,
        depth=16.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )
    wire = scad.make_polyline_rwire(
        points=[
            (-9.0, -5.0, -1.0),
            (9.0, -5.0, -1.0),
            (9.0, 5.0, -1.0),
            (-9.0, 5.0, -1.0),
        ],
        closed=True,
    )
    face = scad.make_face_from_wire_rface(wire=wire, normal=(0.0, 0.0, 1.0))
    tool = scad.extrude_rsolid(
        profile=face,
        direction=(0.0, 0.0, 1.0),
        distance=18.0,
    )
    return scad.cut_rsolid(base, tool, skip_non_intersecting=False)


def test_catalog_exposes_complete_per_instance_schema_and_shaped_hole_ownership():
    report = brep.inspect_geometric_features_rdescriptor(
        model_or_path=_rectangular_through_hole().wrapped,
        feature_kinds=("hole", "extrusion"),
        max_features=50,
    )
    feature = next(
        item for item in report["features"] if item["subtype"] == "rectangular"
    )
    assert report["raw_feature_hints"]
    assert set(feature) == REQUIRED_FIELDS
    assert feature["category"] == "hole"
    assert feature["claim"] == "geometric_candidate"
    assert feature["feature_id"].startswith("hole-")
    assert feature["location"]["direction"]
    assert feature["dimensions"]["depth"]["unit"] == "mm"
    assert feature["profile"]["family"] == "non_circular"
    assert feature["visuals"]["isometric"].endswith("/isometric.png")
    assert len(feature["evidence"]) >= 3


def test_catalog_ids_and_order_are_repeatable_for_the_same_brep():
    shape = _rectangular_through_hole()
    first = brep.inspect_geometric_features_rdescriptor(
        model_or_path=shape.wrapped,
        feature_kinds=("hole", "extrusion"),
        max_features=50,
    )
    second = brep.inspect_geometric_features_rdescriptor(
        model_or_path=shape.wrapped,
        feature_kinds=("hole", "extrusion"),
        max_features=50,
    )
    assert [item["feature_id"] for item in first["features"]] == [
        item["feature_id"] for item in second["features"]
    ]
    assert first["target_sha256"] == second["target_sha256"]


def test_every_null_dimension_explains_why_it_is_unavailable():
    body = scad.make_box_rsolid(
        width=40.0,
        height=28.0,
        depth=14.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )
    report = brep.inspect_geometric_features_rdescriptor(
        model_or_path=body.wrapped,
        feature_kinds=("extrusion",),
        max_features=20,
    )
    for feature in report["features"]:
        for dimension in feature["dimensions"].values():
            assert math.isfinite(dimension["value"]) or dimension["value"] is None
            if dimension["value"] is None:
                assert dimension["unavailable_reason"]


def test_catalog_rejects_truncation_as_a_complete_result():
    first = scad.make_box_rsolid(
        width=10.0,
        height=10.0,
        depth=10.0,
        bottom_face_center=(-8.0, 0.0, 0.0),
    )
    second = scad.make_box_rsolid(
        width=10.0,
        height=10.0,
        depth=10.0,
        bottom_face_center=(8.0, 0.0, 0.0),
    )
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, first.wrapped)
    builder.Add(compound, second.wrapped)
    report = brep.inspect_geometric_features_rdescriptor(
        model_or_path=compound,
        feature_kinds=("extrusion",),
        max_features=1,
    )
    assert report["truncated"] is True
    assert report["complete"] is False
    assert report["omitted_feature_count"] >= 1


def test_revolution_catalog_uses_existing_top_level_contract_and_axis_dimensions():
    profile = scad.make_rectangle_rface(
        width=2.0,
        height=4.0,
        center=(3.0, 0.0, 0.0),
    )
    body = scad.revolve_rsolid(
        profile,
        axis=(0.0, 1.0, 0.0),
        angle=120.0,
        origin=(0.0, 0.0, 0.0),
    )
    report = brep.inspect_geometric_features_rdescriptor(
        model_or_path=body.wrapped,
        feature_kinds=("revolution",),
        max_features=20,
    )
    feature = next(
        item
        for item in report["features"]
        if item["subtype"] == "whole_body_partial_revolution"
    )

    assert report["schema_version"] == "4.1"
    assert set(feature) == REQUIRED_FIELDS
    assert feature["category"] == "revolution"
    assert feature["location"]["axis"]["direction"] == pytest.approx([0.0, 1.0, 0.0])
    assert feature["dimensions"]["sweep_angle"]["value"] == pytest.approx(120.0)
    assert feature["dimensions"]["minimum_radius"]["value"] == pytest.approx(2.0)
    assert feature["dimensions"]["maximum_radius"]["value"] == pytest.approx(4.0)
    assert feature["dimensions"]["axial_span"]["value"] == pytest.approx(4.0)
    assert feature["profile"]["kind"] == "meridian"
    assert feature["visuals"]["profile"].endswith(".png")
    assert feature["visuals"]["angular_sections"]


def test_cylinder_prefers_revolution_and_records_extrusion_as_alternative():
    body = scad.make_cylinder_rsolid(radius=4.0, height=10.0)
    report = brep.inspect_geometric_features_rdescriptor(
        model_or_path=body.wrapped,
        feature_kinds=("extrusion", "revolution"),
        max_features=20,
    )
    primary = [
        item
        for item in report["features"]
        if item["subtype"] == "whole_body_full_revolution"
    ]

    assert len(primary) == 1
    assert not any(item["subtype"] == "whole_body_prism" for item in report["features"])
    relationships = primary[0]["relationships"]
    assert relationships["conflict_group_id"]
    assert any(
        item["category"] == "extrusion"
        for item in relationships["alternative_interpretations"]
    )


def test_v4_catalog_exposes_loft_and_sweep_instances_with_section_visuals():
    first = scad.make_rectangle_rwire(8.0, 4.0, center=(0.0, 0.0, 0.0))
    second = scad.make_rectangle_rwire(3.0, 7.0, center=(1.0, 0.5, 10.0))
    loft = scad.loft_rsolid([first, second])
    loft_report = brep.inspect_geometric_features_rdescriptor(
        loft.wrapped, feature_kinds=("loft",), max_features=20
    )
    loft_feature = next(
        item
        for item in loft_report["features"]
        if item["subtype"] == "whole_body_profile_loft"
    )
    assert set(loft_feature) == REQUIRED_FIELDS
    assert loft_feature["category"] == "loft"
    assert loft_feature["dimensions"]["rigid_fit_error"]["value"] > 0.0
    assert loft_feature["visuals"]["transverse_section"]
    assert loft_feature["reconstruction"]["schema_version"] == "1.0"
    assert loft_feature["reconstruction"]["section_alignment"]["status"] == "aligned"
    assert loft_feature["reconstruction"]["feature_id"] == loft_feature["feature_id"]
    assert loft_feature["reconstruction"]["roi_face_ids"]
    assert loft_feature["reconstruction"]["profile_tracks"][0]["track_id"] == (
        "profile_track:0"
    )
    assert loft_feature["reconstruction"]["specialist_trigger"]["decision"] == (
        "accepted"
    )
    assert loft_feature["reconstruction"]["adaptive_station_plan"]["status"] in {
        "adequate",
        "refinement_requested",
    }
    assert loft_feature["reconstruction"]["recommended_operation"]["api"] == (
        "loft_rsolid"
    )
    assert loft_feature["reconstruction"]["recommended_operation"]["parameters"] == {
        "ruled": False
    }

    profile = scad.make_rectangle_rface(4.0, 2.0)
    twisted = scad.twisted_sweep_rsolid(profile, 9.0, 70.0)
    sweep_report = brep.inspect_geometric_features_rdescriptor(
        twisted.wrapped, feature_kinds=("sweep",), max_features=20
    )
    sweep_feature = next(
        item for item in sweep_report["features"] if item["subtype"] == "twisted_sweep"
    )
    assert set(sweep_feature) == REQUIRED_FIELDS
    assert sweep_feature["category"] == "sweep"
    assert sweep_feature["dimensions"]["twist_angle"]["value"] > 60.0
    assert sweep_feature["visuals"]["profile"]
    assert sweep_feature["reconstruction"]["recommended_operation"]["capability"] == (
        "native"
    )

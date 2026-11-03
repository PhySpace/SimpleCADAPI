"""Phase A characterization of the current Model 2.0 and OCP boundaries."""

from __future__ import annotations

import json

import pytest
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_FORWARD, TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location

import simplecadapi as scad
from simplecadapi.core import Compound, Edge, Face
from simplecadapi.kernel.ocp_export import make_compound_always
from simplecadapi.operators import _make_geo_selector
from simplecadapi.scene import (
    canonical_json_bytes,
    load_contract_artifact,
    profile_cross,
    profile_f32_bits,
    profile_normalize,
)
from simplecadapi.recording.serializer import (
    _candidate_shapes_for_geo_selection,
    _geo_selector_score,
    _resolve_shape_from_geo_selector,
)


CHARACTERIZED_RENDER_PROFILE_CASES = {
    "bounded_canonicalization_failure",
    "closed_edge",
    "degenerate_edge",
    "duplicate_geometry_with_different_metadata",
    "duplicate_geometry_with_different_provenance",
    "negative_zero",
    "normal_fallback",
    "reversed_kernel_traversal",
    "shared_face_rejection",
    "symmetric_entity",
}


def _evaluated_profile() -> dict[str, object]:
    return json.loads(
        load_contract_artifact(
            "profiles/ocp-evaluated-properties-1.profile.json"
        )
    )


def _render_profile() -> dict[str, object]:
    return json.loads(
        load_contract_artifact("profiles/scene-1.0-ocp-glb-2.profile.json")
    )


def _fallback_normal(face: Face) -> tuple[float, float, float]:
    BRepTools.Clean_s(face.wrapped, False)
    mesher = BRepMesh_IncrementalMesh(face.wrapped, 0.35, False, 0.22, False)
    mesher.Perform()
    location = TopLoc_Location()
    triangulation = BRep_Tool.Triangulation_s(face.wrapped, location, 0)
    assert triangulation is not None
    assert triangulation.HasNormals() is False
    indices = list(triangulation.Triangle(1).Get())
    if face.wrapped.Orientation() == TopAbs_REVERSED:
        indices = [indices[0], indices[2], indices[1]]
    points = []
    transform = location.Transformation()
    for index in indices:
        point = triangulation.Node(index).Transformed(transform)
        points.append((point.X() / 1000, point.Z() / 1000, -point.Y() / 1000))
    first = tuple(points[1][index] - points[0][index] for index in range(3))
    second = tuple(points[2][index] - points[0][index] for index in range(3))
    return profile_normalize(profile_cross(first, second))


def test_all_render_profile_characterization_cases_have_targeted_evidence():
    profile = _render_profile()
    assert set(profile["rules"]["required_characterization_cases"]) == (
        CHARACTERIZED_RENDER_PROFILE_CASES
    )


def test_model_schema_2_topology_witnesses_and_roles_survive_clean_replay():
    with scad.GraphSession(graph_id="scene-characterization") as session:
        profile = scad.make_rectangle_rface(width=5, height=3)
        scad.extrude_rsolid(
            profile=profile,
            direction=(0, 0, 1),
            distance=2,
            start_face_tag="role.start",
            end_face_tag="role.end",
        )

    model_json = scad.export_model_json(session=session)
    payload = json.loads(model_json)
    assert payload["schema_version"] == "2.0"
    assert payload["graph"]["schema_version"] == "2.0"
    assert {
        key: payload["graph"]["capabilities"][key]
        for key in (
            "topology_delta_entries",
            "durable_topology_parent_refs",
            "operation_output_roles",
        )
    } == {
        "topology_delta_entries": True,
        "durable_topology_parent_refs": True,
        "operation_output_roles": True,
    }

    assert len(payload["topology_delta_log"]) == 1
    witness = payload["topology_delta_log"][0]
    delta = witness["delta"]
    assert sorted({entry["role"] for entry in delta["roles"]}) == [
        "extrusion.end",
        "extrusion.side",
        "extrusion.start",
    ]
    assert all(
        entry["ref"]["graph_id"] == "scene-characterization"
        and entry["ref"]["node_id"] == witness["node_id"]
        for entry in delta["entries"]
    )

    replayed = scad.replay_model_json(json_str=model_json)
    assert len(replayed) == 1
    solid = replayed[0]
    assert {
        role: sum(scad.ql.output_role(role)(face) for face in solid._iter_faces())
        for role in ("extrusion.start", "extrusion.end", "extrusion.side")
    } == {
        "extrusion.start": 1,
        "extrusion.end": 1,
        "extrusion.side": 4,
    }


def test_profile_forces_reversed_edges_forward_before_selector_evaluation():
    profile = _evaluated_profile()
    preparation = profile["rules"]["shape_preparation"]
    assert preparation["edge_orientation_call"] == "edge.Oriented(TopAbs_FORWARD)"
    assert preparation["edge_orientation_order"] == "force_forward_before_location_bake"

    edge = scad.make_line_redge(start=(0, 0, 0), end=(3, 4, 0))
    reversed_edge = Edge(edge.wrapped.Oriented(TopAbs_REVERSED))
    forward_edge = Edge(reversed_edge.wrapped.Oriented(TopAbs_FORWARD))

    assert edge.wrapped.Orientation() == TopAbs_FORWARD
    assert reversed_edge.wrapped.Orientation() == TopAbs_REVERSED
    assert forward_edge.wrapped.Orientation() == TopAbs_FORWARD
    assert _make_geo_selector(forward_edge) == _make_geo_selector(edge)
    assert _geo_selector_score(
        forward_edge, _make_geo_selector(edge)
    ) == pytest.approx(0.0)


def test_reversed_kernel_traversal_preserves_normalized_evaluated_properties():
    first = scad.make_box_rsolid(
        width=1,
        height=2,
        depth=3,
        bottom_face_center=(-5, 0, 0),
    )
    second = scad.make_box_rsolid(
        width=2,
        height=3,
        depth=4,
        bottom_face_center=(5, 0, 0),
    )
    forward_root = Compound(
        make_compound_always([first.wrapped, second.wrapped])
    )
    reversed_root = Compound(
        make_compound_always([second.wrapped, first.wrapped])
    )
    forward_solids = forward_root._iter_solids()
    reversed_solids = reversed_root._iter_solids()

    assert len(forward_solids) == len(reversed_solids) == 2
    assert forward_solids[0].wrapped.IsSame(first.wrapped)
    assert forward_solids[1].wrapped.IsSame(second.wrapped)
    assert reversed_solids[0].wrapped.IsSame(second.wrapped)
    assert reversed_solids[1].wrapped.IsSame(first.wrapped)

    def evaluated_property_records(root: Compound) -> list[bytes]:
        records = []
        for solid in root._iter_solids():
            selector = _make_geo_selector(solid)
            records.append(
                canonical_json_bytes(
                    {
                        "bounds": selector["bbox"],
                        "kind": selector["kind"],
                        "volume": selector["volume"],
                    }
                )
            )
        return records

    forward_records = evaluated_property_records(forward_root)
    reversed_records = evaluated_property_records(reversed_root)
    assert forward_records != reversed_records
    assert tuple(sorted(forward_records)) == tuple(sorted(reversed_records))


def test_symmetric_entities_are_selector_ambiguous_even_if_legacy_resolver_picks_one():
    profile = _evaluated_profile()
    selector_rules = profile["rules"]["geo_exact_selector"]
    threshold = selector_rules["threshold"]
    assert selector_rules["multiple_match_status"] == "selector_ambiguous"

    first = scad.make_box_rsolid(width=2, height=2, depth=2)
    second = scad.make_box_rsolid(width=2, height=2, depth=2)
    compound = Compound(make_compound_always([first.wrapped, second.wrapped]))
    selector = _make_geo_selector(compound.get_edges(0))
    candidates = _candidate_shapes_for_geo_selection(compound, "edge")
    passing = [
        candidate
        for candidate in candidates
        if _geo_selector_score(candidate, selector) <= threshold
    ]

    assert len(passing) == 2
    legacy_result = _resolve_shape_from_geo_selector(compound, selector)
    assert any(legacy_result.same_topology(candidate) for candidate in passing)


def test_serialized_closed_edge_connector_replays_but_has_no_current_frame():
    profile = _evaluated_profile()
    assert (
        profile["rules"]["connector_frame"]["edge_undefined"]
        == "missing_endpoint_or_coincident_endpoints"
    )

    with scad.GraphSession(graph_id="closed-edge-characterization") as session:
        edge = scad.make_circle_redge(center=(0, 0, 0), radius=2)
        scad.make_edge_connector_rconnector(
            connector_id="closed_edge",
            edge=edge,
        )

    replayed = scad.replay_model_json(
        json_str=scad.export_model_json(session=session)
    )
    assert len(replayed) == 1
    connector = replayed[0]
    selector = connector.geometry_ref.geo_selector
    assert selector["start"] == selector["end"]
    with pytest.raises(ValueError, match="direction must be a non-zero vector"):
        _ = connector.placement


def test_profile_canonicalizes_negative_zero_before_render_keys():
    profile = _render_profile()
    assert profile["rules"]["numeric"]["negative_zero"] == (
        "canonicalize_to_positive_zero"
    )
    assert profile_f32_bits(-0.0) == profile_f32_bits(0.0) == 0


def test_short_valid_ocp_edge_collapses_after_gltf_float32_conversion():
    profile = _render_profile()
    assert profile["rules"]["canonical_blocks"]["edge_empty_policy"] == (
        "retain_degenerate_entity_without_render_block"
    )
    edge = scad.make_line_redge(
        start=(1000, 0, 0),
        end=(1000.00001, 0, 0),
    )
    start = edge.get_start_vertex().get_coordinates()
    end = edge.get_end_vertex().get_coordinates()

    assert edge.get_length() > 0
    assert tuple(profile_f32_bits(component / 1000) for component in start) == tuple(
        profile_f32_bits(component / 1000) for component in end
    )


def test_missing_kernel_normals_use_oriented_triangle_fallback():
    profile = _render_profile()
    assert profile["rules"]["normal"]["fallback"] == (
        "oriented_triangle_cross_product_after_coordinate_conversion"
    )
    face = scad.make_rectangle_rface(width=2, height=3)
    reversed_face = Face(face.wrapped.Oriented(TopAbs_REVERSED))

    assert _fallback_normal(face) == pytest.approx((0, 1, 0))
    assert _fallback_normal(reversed_face) == pytest.approx((0, -1, 0))


def test_duplicate_geometry_metadata_changes_selector_bytes_but_not_score():
    first = scad.make_line_redge(start=(0, 0, 0), end=(1, 0, 0))
    second = scad.make_line_redge(start=(0, 0, 0), end=(1, 0, 0))
    first.set_metadata("geo", {"label": "first"})
    second.set_metadata("geo", {"label": "second"})
    first_selector = _make_geo_selector(first)
    second_selector = _make_geo_selector(second)

    assert first_selector["metadata_geo"] != second_selector["metadata_geo"]
    assert _geo_selector_score(first, second_selector) == pytest.approx(0.0)
    assert _geo_selector_score(second, first_selector) == pytest.approx(0.0)


def test_duplicate_geometry_provenance_is_distinct_but_not_selector_scored():
    with scad.GraphSession(graph_id="duplicate-provenance"):
        first = scad.make_line_redge(start=(0, 0, 0), end=(1, 0, 0))
        second = scad.make_line_redge(start=(0, 0, 0), end=(1, 0, 0))

    first_node = first._get_runtime("graph.node")
    second_node = second._get_runtime("graph.node")
    assert first_node.node_id != second_node.node_id
    assert _make_geo_selector(first) == _make_geo_selector(second)
    assert _geo_selector_score(first, _make_geo_selector(second)) == pytest.approx(0.0)


def test_shared_shape_compound_violates_disjoint_solid_ownership_target():
    profile = _evaluated_profile()
    topology = profile["rules"]["topology"]
    assert topology["accepted_root"] == (
        "single_manifold_solid_or_compound_of_disjoint_manifold_solids"
    )
    assert "shared_face_between_solids" in topology["rejected_roots"]

    solid = scad.make_box_rsolid(width=2, height=2, depth=2)
    compound = Compound(make_compound_always([solid.wrapped, solid.wrapped]))
    solids = compound._iter_solids()
    assert len(solids) == 2
    assert solids[0].wrapped.IsSame(solids[1].wrapped)
    assert len(compound._iter_faces()) == 12
    assert len({face.topo_id for face in compound._iter_faces()}) == 6


def test_symmetric_graph_canonicalization_has_a_hard_failure_budget():
    profile = _evaluated_profile()
    labeling = profile["rules"]["canonical_labeling"]
    assert labeling["maximum_states"] == 1_000_000
    assert labeling["budget_error"] == "entity_canonicalization_budget_exceeded"
    assert labeling["exact_candidate_ties"] == (
        "arbitrary_order_but_evaluate_every_branch"
    )

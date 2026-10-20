"""Target-limited extrusions must terminate on actual target surfaces."""
from __future__ import annotations

import json
import pytest
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

import simplecadapi as s
from simplecadapi.kernel.ocp_booleans import solids_of
from simplecadapi.kernel.ocp_properties import center_of_mass, volume
from simplecadapi import extrude_until_rsolid
from simplecadapi.recording.graph import GraphSession


@pytest.mark.parametrize("until,height", [("NEXT", 5), ("LAST", 7)])
def test_forward_stops_at_near_or_far_planar_surface(until, height):
    face = s.make_rectangle_rface(2, 2)
    target = s.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 5))
    output = extrude_until_rsolid(face, target, until=until)
    assert output.get_volume() == pytest.approx(4 * height)


@pytest.mark.parametrize("until,height", [("PREVIOUS", 8), ("FIRST", 10)])
def test_reverse_modes_invert_the_direction(until, height):
    face = s.make_rectangle_rface(2, 2, center=(0, 0, 10))
    target = s.make_box_rsolid(10, 10, 2)
    output = extrude_until_rsolid(face, target, until=until)
    assert output.get_volume() == pytest.approx(4 * height)


def test_curved_termination_matches_an_independent_boolean_reference():
    face = s.make_rectangle_rface(2, 2)
    sphere = s.make_sphere_rsolid(5, center=(0, 0, 10))
    output = extrude_until_rsolid(face, sphere)
    long_prism = s.extrude_rsolid(face, direction=(0, 0, 1), distance=20)
    cut = BRepAlgoAPI_Cut(long_prism.wrapped, sphere.wrapped)
    cut.Build()
    candidates = solids_of(cut.Shape())
    lower = min(candidates, key=lambda part: center_of_mass(part).z)
    assert output.get_volume() == pytest.approx(volume(lower), rel=1e-8)
    # A sphere's contact surface bows away from its bounding box near the axis.
    assert output.get_volume() > 4 * 5 + .1


def test_ordered_multi_body_targets_choose_first_and_last_surface():
    face = s.make_rectangle_rface(2, 2)
    lower = s.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 5))
    upper = s.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 10))
    assert extrude_until_rsolid(face, [upper, lower], until="NEXT").get_volume() == pytest.approx(20)
    assert extrude_until_rsolid(face, [upper, lower], until="LAST").get_volume() == pytest.approx(48)


def test_rejects_invalid_parameters_and_non_intersecting_targets():
    face = s.make_rectangle_rface(2, 2)
    far = s.make_box_rsolid(2, 2, 2, bottom_face_center=(20, 0, 5))
    with pytest.raises(ValueError, match="intersect|contact"):
        extrude_until_rsolid(face, far)
    with pytest.raises(ValueError, match="nonzero"):
        extrude_until_rsolid(face, far, direction=(0, 0, 0))
    with pytest.raises(ValueError, match="NEXT"):
        extrude_until_rsolid(face, far, until="UNKNOWN")
    with pytest.raises(ValueError, match="at least one"):
        extrude_until_rsolid(face, [])


def test_operation_retains_profile_and_target_as_replay_inputs():
    with GraphSession() as session:
        face = s.make_rectangle_rface(2, 2)
        target = s.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 5))
        output = extrude_until_rsolid(face, target)
        session.capture_result(value=output)
    node = next(n for n in session.graph.nodes if n.op == "make_extrude_until_rsolid")
    assert len(node.inputs) == 2
    assert {key: value for key, value in node.params.items() if key != "input_refs"} == {
        "direction": (0, 0, 1), "until": "NEXT", "target_count": 1}
    assert [ref["node_id"] for ref in node.params["input_refs"]] == [n.node_id for n in node.inputs]
    assert [ref["output_slot"] for ref in node.params["input_refs"]] == [0, 0]
    replayed = s.replay_model_json(s.export_model_json(session))[0]
    assert replayed.get_volume() == pytest.approx(output.get_volume(), rel=1e-9)
    assert replayed.get_volume() == pytest.approx(20)


@pytest.mark.parametrize("until,height", [("NEXT", 5), ("LAST", 7)])
def test_matching_target_footprint_keeps_distinct_termination_faces(until, height):
    profile = s.make_rectangle_rface(2, 2)
    target = s.make_box_rsolid(2, 2, 2, bottom_face_center=(0, 0, 5))
    result = extrude_until_rsolid(profile, target, until=until)
    assert result.get_volume() == pytest.approx(4 * height)


def test_partial_target_cannot_silently_leave_the_temporary_prism():
    profile = s.make_rectangle_rface(4, 4)
    target = s.make_box_rsolid(2, 2, 2, bottom_face_center=(0, 0, 5))
    with pytest.raises(ValueError, match="cover|termination"):
        extrude_until_rsolid(profile, target)

"""Recorded draft preserves its selected faces and neutral-plane semantics."""
import math

import pytest
from OCP.BRepCheck import BRepCheck_Analyzer

import simplecadapi as s
from simplecadapi import ql
from simplecadapi.operators.draft import draft_rsolid
from simplecadapi.recording.graph import GraphSession


def _right_face(body):
    return next(face for face in body._iter_faces() if face.get_normal_at().x > .9)


@pytest.mark.parametrize("angle", [10, -10, 0])
def test_single_planar_face_uses_neutral_plane_and_signed_degrees(angle):
    body = s.make_box_rsolid(10, 10, 10)
    result = draft_rsolid(body, [_right_face(body)], angle=angle)
    assert result.get_volume() == pytest.approx(1000 - 500 * math.tan(math.radians(angle)), rel=1e-9)
    assert body.get_volume() == pytest.approx(1000)
    assert BRepCheck_Analyzer(result.wrapped).IsValid()


def test_query_selection_has_same_geometry_as_explicit_faces():
    body = s.make_box_rsolid(10, 10, 10)
    selector = ql.faces().where(ql.prop("geom.normal.x", ">", .9)).exactly(1)
    selected = draft_rsolid(body, selector, 5, plane_origin=(0, 0, 5))
    explicit = draft_rsolid(body, [_right_face(body)], 5, plane_origin=(0, 0, 5))
    assert selected.get_volume() == pytest.approx(explicit.get_volume(), rel=1e-9)
    assert selected.get_volume() == pytest.approx(1000)


def test_draft_face_selection_and_plane_are_replayable():
    with GraphSession() as session:
        body = s.make_box_rsolid(10, 10, 10)
        result = draft_rsolid(body, [_right_face(body)], 10)
        session.capture_result(value=result)
    node = next(node for node in session.graph.nodes if node.op == "make_draft_rsolid")
    assert node.params["angle"] == 10
    assert node.params["selected_face_count"] == 1
    assert len(node.params["selected_face_node_ids"]) == 1
    assert len(node.inputs) == 2
    replayed = s.replay_model_json(s.export_model_json(session))[0]
    assert replayed.get_volume() == pytest.approx(result.get_volume(), rel=1e-9)


def test_invalid_selection_plane_and_angle_are_rejected():
    body = s.make_box_rsolid(10, 10, 10)
    faces = [_right_face(body)]
    other = s.make_box_rsolid(1, 1, 1, bottom_face_center=(20, 0, 0))
    with pytest.raises(ValueError, match="belong"):
        draft_rsolid(body, [_right_face(other)], 5)
    with pytest.raises(ValueError, match="at least one"):
        draft_rsolid(body, [], 5)
    with pytest.raises(ValueError, match="nonzero"):
        draft_rsolid(body, faces, 5, plane_normal=(0, 0, 0))
    with pytest.raises(ValueError, match="angle"):
        draft_rsolid(body, faces, 90)

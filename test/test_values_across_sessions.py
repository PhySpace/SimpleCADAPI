"""A value that outlived the session that made it (a notebook cell's result restored from the cache) is a legitimate
input of the next cell: its faces anchor connectors, its edges feed features."""

import pickle

import simplecadapi as scad
from simplecadapi.recording.graph import GraphSession


def _restored_box():
    with GraphSession("nb", namespace="ca", shared_lineage=True):
        box = scad.make_box_rsolid(20.0, 10.0, 5.0)
    return pickle.loads(pickle.dumps(box))


def test_a_face_of_a_restored_value_anchors_a_connector():
    restored = _restored_box()
    face = restored.get_faces(0)  # picked outside any session

    with GraphSession("nb", namespace="cb", shared_lineage=True) as session:
        connector = scad.make_face_connector_rconnector("mount", face)

    assert connector.connector_id == "mount"
    assert "make_face_connector_rconnector" in [node.op for node in session.graph.nodes]


def test_a_face_picked_in_a_session_of_the_next_cell_does_too():
    restored = _restored_box()

    with GraphSession("nb", namespace="cb", shared_lineage=True) as session:
        face = restored.get_faces(1)
        connector = scad.make_face_connector_rconnector("mount", face)
        part = scad.make_part_rpart("p", scad.make_box_rsolid(1.0, 1.0, 1.0))

    assert connector.connector_id == "mount" and part.part_id == "p"
    assert session.graph.node_count >= 3

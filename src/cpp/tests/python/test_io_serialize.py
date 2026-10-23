"""Shape serialization, pickle and copy."""

import copy
import pickle

import pytest

import simplecadapi._cpp as scad
from simplecadapi._cpp import _testing


def tagged_box():
    box = _testing.box(10, 20, 30)
    box._add_tag("role.body")
    box.set_metadata("name", "bracket")
    box.set_metadata("info", {"mass": 1.25, "ids": [1, 2, 3], "ok": True, "none": None})
    face = box.get_faces(2)
    face._add_tag("role.mount")
    face.set_metadata("provenance", {"source": "unit-test"})
    face._set_runtime("semantic.lineage.coverage", "complete")
    box.get_edges(5).set_metadata("geo", {"edge_index": 5})
    return box


def test_serialize_round_trip_keeps_geometry_and_semantic_state():
    box = tagged_box()
    data = scad.serialize_shape(box)
    assert data.startswith(b"SCADSHAP")
    restored = scad.deserialize_shape(data)
    assert isinstance(restored, scad.Solid)
    assert restored.get_volume() == pytest.approx(6000.0)
    assert restored._has_tag("role.body", scope="local")
    assert restored.get_metadata("name") == "bracket"
    assert restored.get_metadata("info") == {"mass": 1.25, "ids": [1, 2, 3], "ok": True, "none": None}
    face = restored.get_faces(2)
    assert face.topo_id == box.get_faces(2).topo_id
    assert face._has_tag("role.mount", scope="local")
    assert face.get_metadata("provenance") == {"source": "unit-test"}
    assert face._get_runtime("semantic.lineage.coverage") == "complete"
    assert restored.get_edges(5).get_metadata("geo") == {"edge_index": 5}
    assert not restored.get_faces(0)._has_tag("role.mount")
    assert scad.serialize_shape(restored) == data


def test_pickle_and_deepcopy_use_the_container():
    box = tagged_box()
    for clone in (pickle.loads(pickle.dumps(box)), pickle.loads(pickle.dumps(box, protocol=2)), copy.deepcopy(box)):
        assert isinstance(clone, scad.Solid)
        assert clone.get_volume() == pytest.approx(6000.0)
        assert clone.get_faces(2)._has_tag("role.mount", scope="local")
        assert clone.get_metadata("name") == "bracket"
    face = pickle.loads(pickle.dumps(box.get_faces(2)))
    assert isinstance(face, scad.Face)
    assert face._has_tag("role.mount", scope="local")


def test_a_clone_is_independent_of_its_source():
    box = tagged_box()
    clone = copy.deepcopy(box)
    clone._add_tag("role.only_on_clone")
    assert not box._has_tag("role.only_on_clone")


def test_damaged_bytes_raise_simplecad_errors():
    data = scad.serialize_shape(tagged_box())
    for bad in (b"", b"junk" * 20, data[:-5], data[:40] + bytes(len(data) - 40)):
        with pytest.raises(scad.SimpleCADError) as info:
            scad.deserialize_shape(bad)
        assert info.value.operation == "deserialize_shape"
    flipped = bytearray(data)
    flipped[len(flipped) // 2] ^= 0x55
    with pytest.raises(scad.SimpleCADError, match="checksum|corrupt|length"):
        scad.deserialize_shape(bytes(flipped))

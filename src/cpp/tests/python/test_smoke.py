import math

import pytest

import simplecadapi._cpp as scad
from simplecadapi._cpp import _testing


def test_module_imports_and_error_type():
    assert issubclass(scad.SimpleCADError, ValueError)


def test_box_topology_and_measures():
    box = _testing.box(10, 20, 30)
    assert box.get_volume() == pytest.approx(6000.0)
    assert len(box.faces()) == 6
    assert len(box.edges()) == 12
    assert len(box.get_edge_occurrences(23).get_vertices(0).get_coordinates()) == 3


def test_bare_enumeration_is_forbidden_like_python_sdk():
    box = _testing.box(1, 1, 1)
    with pytest.raises(scad.SimpleCADError) as info:
        box.get_faces()
    assert info.value.operation == "get_faces (no index)"
    assert "How to fix:" in str(info.value)
    assert "ql.edges().resolve(shape)" in str(info.value)


def test_indexing_follows_python_semantics():
    box = _testing.box(1, 1, 1)
    assert box.get_faces(-1).topo_id == box.get_faces(5).topo_id
    with pytest.raises(IndexError):
        box.get_faces(6)


def test_tags_are_shared_between_handles_of_one_solid():
    box = _testing.box(1, 1, 1)
    box.get_faces(0)._add_tag("role.mount")
    assert box.get_faces(0)._has_tag("role.mount")
    assert not box.get_faces(1)._has_tag("role.mount")
    assert box.get_faces(0)._list_tags(scope="local") == ["role.mount"]


def test_normals_and_vec3_object():
    box = _testing.box(2, 2, 2)
    normals = [box.get_faces(i).get_normal_at() for i in range(6)]
    assert any(n.z > 0.9 for n in normals) and any(n.z < -0.9 for n in normals)
    n = normals[0]
    assert math.isclose(n.norm(), 1.0)
    assert repr(n).startswith("Vec3(")
    assert len(tuple(n)) == 3


def test_workplane_stack_and_cs():
    assert tuple(scad.get_current_cs().origin) == (0, 0, 0)
    with scad.SimpleWorkplane(origin=(0, 0, 5)):
        assert tuple(scad.get_current_cs().origin) == (0, 0, 5)
        with scad.SimpleWorkplane(origin=(1, 0, 0)):
            assert tuple(scad.get_current_cs().origin) == (1, 0, 5)
    assert tuple(scad.get_current_cs().origin) == (0, 0, 0)


def test_coordinate_system_rejects_zero_axis_with_guidance():
    with pytest.raises(scad.SimpleCADError) as info:
        scad.CoordinateSystem((0, 0, 0), (0, 0, 0), (0, 1, 0))
    assert "What happened:" in str(info.value)
    assert info.value.to_dict()["operation"] == "CoordinateSystem._normalize"


def test_repr_matches_python_sdk_format():
    box = _testing.box(1, 2, 3)
    assert repr(box).startswith("Solid(volume=6.000, faces=6, tags=")
    assert "Solid:" in str(box) and "face_count: 6" in str(box)

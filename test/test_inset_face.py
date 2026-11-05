"""inset_face_rsolid: a planar face's loops moved inside it are imprinted; the face splits into its inner face and ring."""

import pytest
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer

import simplecadapi as s
from simplecadapi import ql
from simplecadapi.recording.graph import GraphSession

TOP = ql.faces().where(ql.prop("geom.center.z", ">=", 19.9)).where(ql.prop("geom.type", "==", "PLANE")).exactly(1)


def _top_pieces(body):
    return sorted((face for face in body._iter_faces() if abs(face.get_center().z - 20) < 1e-6 and face._geom_type() == "PLANE"), key=lambda f: f.get_area())


def test_the_face_splits_into_its_inner_face_and_ring_and_the_shape_stays():
    box = s.make_box_rsolid(40, 30, 20)
    inset = s.inset_face_rsolid(box, TOP, 3)
    assert len(inset._iter_faces()) == 7
    assert inset.get_volume() == pytest.approx(box.get_volume())
    assert [round(face.get_area(), 6) for face in _top_pieces(inset)] == [384, 816]  # the ring, then 34 x 24 inside
    assert BRepCheck_Analyzer(inset.wrapped).IsValid()


def test_a_hole_of_the_face_gets_its_own_ring():
    holed = s.cut_rsolid(s.make_box_rsolid(40, 30, 20), s.make_cylinder_rsolid(4, 50, (0, 0, -5)))
    inset = s.inset_face_rsolid(holed, TOP, 2)
    areas = [face.get_area() for face in _top_pieces(inset)]
    assert areas[0] == pytest.approx(3.14159265 * (6**2 - 4**2), rel=1e-6)  # around the hole
    assert sum(areas) == pytest.approx(40 * 30 - 3.14159265 * 16, rel=1e-6)


def test_the_pieces_carry_kernel_roles_that_name_them_after_a_parameter_change():
    with GraphSession():
        inset = s.inset_face_rsolid(s.make_box_rsolid(40, 30, 20), TOP, 3)
        inner = s.ref.face("", "make_inset_face_rsolid", role="inset.inner")
        ring = s.ref.face("", "make_inset_face_rsolid", role="inset.ring")
        assert inner.one(inset).get_area() == pytest.approx(816)
        assert ring.one(inset).get_area() == pytest.approx(384)
        assert s.ref.of(inner.one(inset), inset) == inner.__class__.from_dict({**inner.to_dict(), "guard": s.ref.of(inner.one(inset), inset).guard})
        # pull the inner face out: a boss, built on the piece the role names
        boss = s.union_rsolid(inset, s.extrude_rsolid(profile=inner.one(inset), direction=(0, 0, 1), distance=5))
        assert boss.get_volume() == pytest.approx(24000 + 816 * 5)


def test_the_operation_is_recorded_and_replays():
    with GraphSession() as session:
        result = s.inset_face_rsolid(s.make_box_rsolid(40, 30, 20), TOP, 3)
        session.capture_result(value=result)
    node = next(node for node in session.graph.nodes if node.op == "make_inset_face_rsolid")
    assert node.params["distance"] == 3
    assert node.params["selected_face_count"] == 1
    assert len(node.inputs) == 2
    replayed = s.replay_model_json(s.export_model_json(session))[0]
    assert len(replayed._iter_faces()) == 7


def test_what_it_refuses():
    box = s.make_box_rsolid(40, 30, 20)
    with pytest.raises(ValueError, match="positive"):
        s.inset_face_rsolid(box, TOP, 0)
    with pytest.raises(ValueError, match="does not fit"):
        s.inset_face_rsolid(box, TOP, 20)
    with pytest.raises(ValueError, match="exactly one"):
        s.inset_face_rsolid(box, ql.faces(), 1)
    with pytest.raises(ValueError, match="planar"):
        s.inset_face_rsolid(s.make_cylinder_rsolid(5, 10), ql.faces().where(ql.prop("geom.type", "==", "CYLINDER")).exactly(1), 1)

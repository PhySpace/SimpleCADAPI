"""Geometric and graph-replay contracts needed by source translators."""
import math

import pytest
import simplecadapi as scad


def test_nonuniform_scale_volume_and_replay():
    with scad.GraphSession(graph_id="scale-test") as session:
        original = scad.make_box_rsolid(width=10, height=12, depth=14)
        scaled = scad.scale_rsolid(solid=original, factors=(2, 3, 0.5), center=(5, 6, 7))
        session.capture_result(value=scaled)
    assert scaled.get_volume() == pytest.approx(original.get_volume() * 3)
    assert original.get_volume() == pytest.approx(1680)
    rebuilt = scad.replay_model_json(scad.export_model_json(session=session), strict=True)[0]
    assert rebuilt.get_volume() == pytest.approx(scaled.get_volume())


@pytest.mark.parametrize("factors", [(0, 1, 1), (math.nan, 1, 1), (1, 2), (math.inf, 1, 1)])
def test_invalid_scale_factors_are_rejected(factors):
    original = scad.make_box_rsolid(width=10, height=12, depth=14)
    with pytest.raises(ValueError):
        scad.scale_rsolid(solid=original, factors=factors)


@pytest.mark.parametrize("amount", [-1.0, 1.0])
def test_signed_open_shell_replays(amount):
    with scad.GraphSession(graph_id="offset-test") as session:
        original = scad.make_box_rsolid(width=10, height=12, depth=14)
        openings = scad.ql.faces().where(scad.ql.prop("geom.normal.z", ">", 0.9)).exactly(1)
        hollow = scad.offset_rsolid(solid=original, amount=amount, openings=openings)
        session.capture_result(value=hollow)
    assert 0 < hollow.get_volume() < original.get_volume()
    rebuilt = scad.replay_model_json(scad.export_model_json(session=session), strict=True)[0]
    assert rebuilt.get_volume() == pytest.approx(hollow.get_volume(), rel=1e-9)


def test_closed_outer_offset_increases_volume():
    original = scad.make_box_rsolid(width=10, height=12, depth=14)
    expanded = scad.offset_rsolid(solid=original, amount=1.0)
    assert expanded.get_volume() > original.get_volume()


def test_zero_offset_rejected():
    original = scad.make_box_rsolid(width=10, height=12, depth=14)
    with pytest.raises(ValueError):
        scad.offset_rsolid(solid=original, amount=0)


def test_affine_shear_is_recorded_and_replayed():
    with scad.GraphSession(graph_id="shear") as session:
        original = scad.make_box_rsolid(width=10, height=12, depth=14)
        transformed = scad.transform_rsolid(solid=original,
            matrix=[[1, 0.3, 0, 5], [0, 1, 0, 2], [0, 0, 1, 0], [0, 0, 0, 1]])
        session.capture_result(value=transformed)
    assert transformed.get_volume() == pytest.approx(original.get_volume())
    rebuilt = scad.replay_model_json(scad.export_model_json(session=session), strict=True)[0]
    assert rebuilt.get_volume() == pytest.approx(transformed.get_volume())


def test_affine_singular_matrix_rejected():
    original = scad.make_box_rsolid(width=10, height=12, depth=14)
    with pytest.raises(ValueError):
        scad.transform_rsolid(solid=original, matrix=[[0]*4 for _ in range(4)])


def test_set_boolean_keeps_all_output_slots_and_part_replay():
    with scad.GraphSession(graph_id="cut-pieces") as session:
        base = scad.make_box_rsolid(10, 2, 2)
        tool = scad.make_box_rsolid(2, 4, 4, bottom_face_center=(0, 0, -1))
        pieces = scad.boolean_rsolidlist(left=[base], right=[tool], operation="cut")
        assert len(pieces) == 2
        final = scad.make_part_rpart(part_id="second", body=pieces[1])
        session.capture_result(value=final)
    replayed = scad.replay_model_json(scad.export_model_json(session=session), strict=True)[0]
    from simplecadapi.kernel.ocp_properties import center_of_mass
    assert tuple(center_of_mass(replayed.body.wrapped)) == pytest.approx(tuple(center_of_mass(pieces[1].wrapped)))
    assert replayed.body.get_volume() == pytest.approx(16)


@pytest.mark.parametrize("operation", ["cut", "intersect", "union"])
def test_set_boolean_compound_members_and_graph_replay(operation):
    with scad.GraphSession(graph_id="set-boolean") as session:
        left = [scad.make_box_rsolid(2, 2, 2, bottom_face_center=(x, 0, 0)) for x in (-4, 4)]
        right = [scad.make_box_rsolid(1, 4, 4, bottom_face_center=(x, 0, -1)) for x in (-4, 4)]
        result = scad.boolean_rsolidlist(left=left, right=right, operation=operation)
        session.capture_result(value=result)
    expected = {"cut": 8, "intersect": 8, "union": 40}[operation]
    assert sum(body.get_volume() for body in result) == pytest.approx(expected)
    replayed = scad.replay_model_json(scad.export_model_json(session=session), strict=True)
    assert len(replayed) == len(result)
    assert sum(body.get_volume() for body in replayed) == pytest.approx(expected)


def test_set_boolean_complete_removal_returns_no_solid():
    base = scad.make_box_rsolid(2, 2, 2)
    assert scad.boolean_rsolidlist(left=[base], right=[base], operation="cut") == []

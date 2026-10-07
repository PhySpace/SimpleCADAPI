"""Native section features: strict geometry and graph replay."""
import math
import pytest
import simplecadapi as s


def _rectangle(z, width=10, height=6):
    sketch = s.make_sketch_rsketch(name=f"section{z}", plane={"origin": (0, 0, z), "x_axis": (1, 0, 0), "y_axis": (0, 1, 0)})
    for name, point in zip("abcd", [(0, 0), (width, 0), (width, height), (0, height)]):
        sketch = s.add_point_rsketch(sketch=sketch, point_id=name, x=point[0], y=point[1])
    for name, first, second in [("ab", "a", "b"), ("bc", "b", "c"), ("cd", "c", "d"), ("da", "d", "a")]:
        sketch = s.add_line_rsketch(sketch=sketch, entity_id=name, start=first, end=second)
    return s.make_face_from_sketch_rface(sketch=sketch)


def test_tapered_rectangle_and_graph_replay():
    with s.GraphSession(graph_id="taper") as session:
        profile = _rectangle(0)
        body = s.extrude_taper_rsolid(profile=profile, vector=(0, 0, 4), taper=10)
        session.capture_result(value=body)
    slope = math.tan(math.radians(10))
    expected = 60 * 4 - (10 + 6) * slope * 4**2 + 4 * slope**2 * 4**3 / 3
    assert body.get_volume() == pytest.approx(expected, rel=1e-8)
    replayed = s.replay_model_json(s.export_model_json(session=session), strict=True)[0]
    assert replayed.get_volume() == pytest.approx(expected, rel=1e-8)


def test_multisection_straight_sweep_and_replay():
    with s.GraphSession(graph_id="multi") as session:
        sections = [_rectangle(0), _rectangle(3), _rectangle(6)]
        path = s.make_segment_rwire(start=(5, 3, 0), end=(5, 3, 6))
        body = s.sweep_multisection_rsolid(profiles=sections, path=path)
        session.capture_result(value=body)
    assert body.get_volume() == pytest.approx(360, rel=1e-6)
    replayed = s.replay_model_json(s.export_model_json(session=session), strict=True)[0]
    assert replayed.get_volume() == pytest.approx(360, rel=1e-6)


def test_multisection_needs_two_sections():
    with pytest.raises(ValueError):
        s.sweep_multisection_rsolid(profiles=[_rectangle(0)], path=s.make_segment_rwire(start=(0, 0, 0), end=(0, 0, 3)))


def test_invalid_taper_is_rejected():
    with pytest.raises(ValueError):
        s.extrude_taper_rsolid(profile=_rectangle(0), vector=(0, 0, 4), taper=math.nan)


@pytest.mark.parametrize("taper,vector", [(-10, (0, 0, 4)), (10, (0, 0, -4))])
def test_taper_fallback_keeps_exact_section_area(taper, vector):
    body = s.extrude_taper_rsolid(profile=_rectangle(0), vector=vector, taper=taper)
    slope = math.tan(math.radians(taper))
    expected = 60 * 4 - 16 * slope * 16 + 4 * slope**2 * 64 / 3
    assert body.get_volume() == pytest.approx(expected, rel=1e-7)


def test_taper_with_hole_tapers_inner_loop_oppositely():
    sketch = s.make_sketch_rsketch(name="annulus", plane="XY")
    sketch = s.add_point_rsketch(sketch=sketch, point_id="center", x=0, y=0)
    sketch = s.add_circle_rsketch(sketch=sketch, entity_id="outer", center="center", radius=10)
    sketch = s.add_circle_rsketch(sketch=sketch, entity_id="inner", center="center", radius=2)
    face = s.make_face_from_sketch_rface(sketch=sketch, profile="outer", inner_profiles=["inner"])
    body = s.extrude_taper_rsolid(profile=face, vector=(0, 0, 3), taper=5)
    slope = math.tan(math.radians(5))
    expected = math.pi * ((100 - 4) * 3 - (10 + 2) * slope * 9)
    assert body.get_volume() == pytest.approx(expected, rel=1e-6)

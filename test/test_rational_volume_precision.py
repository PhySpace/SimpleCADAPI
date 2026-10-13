"""Rational NURBS mass properties must match analytic geometry."""
import math

import pytest
import simplecadapi as s


def test_nurbs_circle_extrusion_uses_span_aware_volume_integration():
    sketch = s.make_sketch_rsketch(name="rational-circle", plane="XY")
    sketch = s.add_point_rsketch(sketch=sketch, point_id="seam", x=1, y=0)
    poles = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0)]
    sketch = s.add_bspline_rsketch(sketch=sketch, entity_id="circle", start="seam", end="seam",
        control_points=poles, degree=2, knots=[0, .25, .5, .75, 1],
        multiplicities=[3, 2, 2, 2, 3], weights=[1, math.sqrt(.5), 1, math.sqrt(.5), 1, math.sqrt(.5), 1, math.sqrt(.5), 1])
    profile = s.make_face_from_sketch_rface(sketch=sketch)
    body = s.extrude_rsolid(profile=profile, direction=(0, 0, 1), distance=2)
    assert body.get_volume() == pytest.approx(2 * math.pi, rel=1e-9)

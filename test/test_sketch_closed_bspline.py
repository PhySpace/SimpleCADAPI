"""Closed spline seams are topology endpoints, including periodic NURBS."""
import math
import pytest
import simplecadapi as scad
from simplecadapi._cpp.occt.BRepGProp import BRepGProp
from simplecadapi._cpp.occt.GProp import GProp_GProps


def accurate_mass(shape, *, volume=False):
    props = GProp_GProps()
    if volume:
        BRepGProp.VolumePropertiesGK_s(shape.wrapped, props, 1e-10, True, True)
    else:
        BRepGProp.SurfaceProperties_s(shape.wrapped, props, 1e-10)
    return props.Mass()


def rational_circle():
    poles = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0)]
    weights = [1, math.sqrt(.5), 1, math.sqrt(.5), 1, math.sqrt(.5), 1, math.sqrt(.5), 1]
    return poles, weights


def test_closed_rational_bspline_same_endpoint_promotes_exact_face():
    poles, weights = rational_circle()
    sketch = scad.make_sketch_rsketch(name='closed-rational')
    sketch = scad.add_point_rsketch(sketch, 'seam', 1, 0)
    sketch = scad.add_bspline_rsketch(sketch, 'boundary', 'seam', 'seam', poles,
        degree=2, knots=[0, .25, .5, .75, 1], multiplicities=[3, 2, 2, 2, 3], weights=weights)
    face = scad.make_face_from_sketch_rface(sketch=sketch)
    assert accurate_mass(face) == pytest.approx(math.pi, rel=1e-9)
    with scad.GraphSession() as session:
        sketch2 = scad.make_sketch_rsketch(name='replayed-closed-rational')
        sketch2 = scad.add_point_rsketch(sketch2, 'seam', 1, 0)
        sketch2 = scad.add_bspline_rsketch(sketch2, 'boundary', 'seam', 'seam', poles,
            degree=2, knots=[0, .25, .5, .75, 1], multiplicities=[3, 2, 2, 2, 3], weights=weights)
        face2 = scad.make_face_from_sketch_rface(sketch=sketch2)
        solid = scad.extrude_rsolid(face2, (0, 0, 1), 2)
        session.capture_result(value=solid)
    from simplecadapi.recording.serializer import replay_graph
    rebuilt = replay_graph(session.graph)
    assert accurate_mass(rebuilt[0], volume=True) == pytest.approx(math.pi * 2, rel=1e-9)


def test_periodic_bspline_seam_does_not_replace_control_poles():
    poles = [(2, 0), (0, 2), (-2, 0), (0, -2)]
    # The seam lies midway between poles for this periodic quadratic basis.
    native = scad.make_spline_redge(control_points=[(x, y, 0) for x, y in poles], degree=2, periodic=True)
    from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve
    adaptor = BRepAdaptor_Curve(native.wrapped)
    seam = adaptor.Value(adaptor.FirstParameter())
    wire = scad.make_wire_from_edges_rwire([native])
    reference = scad.make_face_from_wire_rface(wire)
    sketch = scad.make_sketch_rsketch(name='periodic')
    sketch = scad.add_point_rsketch(sketch, 'seam', seam.X(), seam.Y())
    sketch = scad.add_bspline_rsketch(sketch, 'boundary', 'seam', 'seam', poles, degree=2, periodic=True)
    face = scad.make_face_from_sketch_rface(sketch=sketch)
    assert face.get_area() == pytest.approx(reference.get_area(), rel=1e-9)

"""make_spline_*, make_interpolated_spline_*, make_periodic_spline_rwire against the reference."""

import pytest

import simplecadapi._cpp as scad
from ops_geometry_support import parity

POLES = "[(0.0, 0.0, 0.0), (0.6, 1.0, 0.0), (1.4, 1.0, 0.0), (2.0, 0.0, 0.0)]"


def test_exact_splines():
    parity("splines_exact", f"""
        poles = {POLES}
        quintic = [(0, 0), (1, 2), (2, -1), (3, 2), (4, 0), (5, 1)]
        result = {{
            "default": describe(scad.make_spline_redge(control_points=poles)),
            "wire": describe(scad.make_spline_rwire(control_points=poles)),
            "alias": describe(scad.create_spline(control_points=poles)),
            "alias_wire": describe(scad.create_spline_wire(control_points=poles)),
            "planar_poles": describe(scad.make_spline_redge(control_points=quintic, degree=5)),
            "quadratic": describe(scad.make_spline_redge(control_points=poles, degree=2)),
            "full_knots": describe(scad.make_spline_redge(control_points=poles, knots=[0, 0, 0, 0, 1, 1, 1, 1])),
            "unique_knots": describe(scad.make_spline_redge(control_points=poles, knots=[0, 1], multiplicities=[4, 4])),
            "rational": describe(scad.make_spline_redge(control_points=poles, weights=[1, 2, 2, 1])),
            "periodic": describe(scad.make_spline_redge(control_points=poles + [(1, -1, 0)], degree=3, periodic=True)),
            "float_degree": describe(scad.make_spline_redge(control_points=poles, degree=3.0)),
        }}
    """)


def test_exact_spline_failures():
    parity("splines_exact_failures", f"""
        poles = {POLES}
        result = {{
            "fractional_degree": failure(lambda: scad.make_spline_redge(control_points=poles, degree=2.5)),
            "bool_degree": failure(lambda: scad.make_spline_redge(control_points=poles, degree=True)),
            "zero_degree": failure(lambda: scad.make_spline_redge(control_points=poles, degree=0)),
            "huge_degree": failure(lambda: scad.make_spline_redge(control_points=poles, degree=30)),
            "no_poles": failure(lambda: scad.make_spline_redge(control_points=[])),
            "too_few_poles": failure(lambda: scad.make_spline_redge(control_points=poles[:3])),
            "bad_dimension": failure(lambda: scad.make_spline_redge(control_points=[(0,), (1,), (2,), (3,)])),
            "multiplicities_only": failure(lambda: scad.make_spline_redge(control_points=poles, multiplicities=[4, 4])),
            "decreasing_knots": failure(lambda: scad.make_spline_redge(control_points=poles, knots=[0, 0, 0, 1, 0, 1, 1, 1])),
            "knot_sum": failure(lambda: scad.make_spline_redge(control_points=poles, knots=[0, 1], multiplicities=[3, 4])),
            "multiplicity_cap": failure(lambda: scad.make_spline_redge(control_points=poles, knots=[0, 1], multiplicities=[5, 3])),
            "length_mismatch": failure(lambda: scad.make_spline_redge(control_points=poles, knots=[0, 1, 2], multiplicities=[4, 4])),
            "weights_count": failure(lambda: scad.make_spline_redge(control_points=poles, weights=[1, 2])),
            "weights_positive": failure(lambda: scad.make_spline_redge(control_points=poles, weights=[1, 0, 1, 1])),
            "wire": failure(lambda: scad.make_spline_rwire(control_points=poles[:2])),
        }}
    """)


def test_spline_arguments_are_keyword_only():
    with pytest.raises(TypeError):
        scad.make_spline_redge([(0, 0, 0), (1, 1, 0), (2, 1, 0), (3, 0, 0)])
    with pytest.raises(TypeError):
        scad.make_interpolated_spline_redge([(0, 0, 0), (1, 1, 0)])


def test_interpolated_splines():
    parity("splines_interpolated", """
        pts = [(0, 0, 0), (1, 2, 0), (2, 0, 1), (3, 2, 0)]
        loop = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)]
        result = {
            "open": describe(scad.make_interpolated_spline_redge(points=pts)),
            "wire": describe(scad.make_interpolated_spline_rwire(points=pts)),
            "periodic": describe(scad.make_interpolated_spline_redge(points=loop, periodic=True)),
            "closed_input": describe(scad.make_interpolated_spline_rwire(points=loop + [loop[0]], periodic=True)),
            "periodic_wire": describe(scad.make_periodic_spline_rwire(points=loop)),
            "planar_2d": describe(scad.make_interpolated_spline_redge(points=[(0, 0), (1, 1), (2, 0)])),
            "tolerance": describe(scad.make_interpolated_spline_redge(points=pts, tolerance=1e-3)),
            "aliases": [describe(scad.create_interpolated_spline(points=pts)), describe(scad.create_interpolated_spline_wire(points=pts)),
                        describe(scad.create_periodic_spline_wire(points=loop))],
        }
    """)


def test_interpolated_spline_failures():
    parity("splines_interpolated_failures", """
        result = {
            "one_point": failure(lambda: scad.make_interpolated_spline_redge(points=[(0, 0, 0)])),
            "two_periodic": failure(lambda: scad.make_interpolated_spline_redge(points=[(0, 0, 0), (1, 0, 0)], periodic=True)),
            "duplicate": failure(lambda: scad.make_interpolated_spline_redge(points=[(0, 0, 0), (0, 0, 0), (1, 0, 0)])),
            "tolerance": failure(lambda: scad.make_interpolated_spline_redge(points=[(0, 0, 0), (1, 0, 0)], tolerance=0)),
            "wire": failure(lambda: scad.make_interpolated_spline_rwire(points=[(0, 0, 0)])),
            "periodic_wire": failure(lambda: scad.make_periodic_spline_rwire(points=[(0, 0, 0), (1, 0, 0)])),
        }
    """)

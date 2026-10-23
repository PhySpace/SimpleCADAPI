"""trim_surface_rface against the reference SDK, and its error contract."""

import math

import pytest

import simplecadapi._cpp as scad
from ref import golden
from surface_support import REF_PRELUDE, arc, close_to, line, measure, rectangle, wire

CARRIER = [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]


def cylinder_patch(radius, a, b):
    def p(angle, z):
        return (radius * math.cos(angle), radius * math.sin(angle), z)

    mid = (a + b) / 2
    return wire([arc(p(a, 0), p(mid, 0), p(b, 0)), line(p(b, 0), p(b, 2)), arc(p(b, 2), p(mid, 2), p(a, 2)), line(p(a, 2), p(a, 0))])


def test_planar_trims_match_the_reference():
    ref_body = f"""
carrier = scad.make_bezier_surface_rface({CARRIER!r})
plain = scad.trim_surface_rface(carrier, rectangle(4, 4), tag_prefix="trimmed")
holed = scad.trim_surface_rface(carrier, rectangle(4, 4), holes=[rectangle(1, 1)])
bounded = scad.trim_surface_rface(carrier, rectangle(4, 4), holes=[rectangle(2, 2)])
again = scad.trim_surface_rface(bounded, rectangle(3, 3))
partial = scad.trim_surface_rface(plain, rectangle(2, 4, center=(1.5, 0, 0)))
result = {{"plain": measure(plain), "holed": measure(holed), "again": measure(again), "partial": measure(partial)}}
"""
    carrier = scad.make_bezier_surface_rface(CARRIER)
    plain = scad.trim_surface_rface(carrier, rectangle(4, 4), tag_prefix="trimmed")
    holed = scad.trim_surface_rface(carrier, rectangle(4, 4), holes=[rectangle(1, 1)])
    bounded = scad.trim_surface_rface(carrier, rectangle(4, 4), holes=[rectangle(2, 2)])
    again = scad.trim_surface_rface(bounded, rectangle(3, 3))
    partial = scad.trim_surface_rface(plain, rectangle(2, 4, center=(1.5, 0, 0)))
    expected = golden("surface_trim_planar", REF_PRELUDE + ref_body)
    got = {"plain": measure(plain), "holed": measure(holed), "again": measure(again), "partial": measure(partial)}
    assert close_to(got, expected, rel=1e-6), f"native {got}\nreference {expected}"
    assert "trimmed.face" in plain._list_tags()


def test_periodic_trim_matches_the_reference():
    ref_body = """
import math
def patch(radius, a, b):
    def p(angle, z):
        return (radius * math.cos(angle), radius * math.sin(angle), z)
    mid = (a + b) / 2
    return wire([arc(p(a, 0), p(mid, 0), p(b, 0)), line(p(b, 0), p(b, 2)), arc(p(b, 2), p(mid, 2), p(a, 2)), line(p(a, 2), p(a, 0))])
carrier = scad.make_cylindrical_surface_rface(2.0, (0.0, 2.0 * math.pi), (0.0, 2.0), tag_prefix="carrier")
result = measure(scad.trim_surface_rface(carrier, patch(2.0, 0.5, 2.5), tag_prefix="trimmed"))
"""
    carrier = scad.make_cylindrical_surface_rface(2.0, (0.0, 2.0 * math.pi), (0.0, 2.0), tag_prefix="carrier")
    got = measure(scad.trim_surface_rface(carrier, cylinder_patch(2.0, 0.5, 2.5), tag_prefix="trimmed"))
    expected = golden("surface_trim_periodic", REF_PRELUDE + ref_body)
    assert close_to(got, expected, rel=1e-6), f"native {got}\nreference {expected}"


def failure(call):
    with pytest.raises(scad.SimpleCADError) as info:
        call()
    return info.value


def test_trim_rejections_name_the_failing_check():
    carrier = scad.make_bezier_surface_rface(CARRIER)
    big = scad.make_bezier_surface_rface([[(-4, -4, 0), (-4, 4, 0)], [(4, -4, 0), (4, 4, 0)]])
    bounded = scad.trim_surface_rface(big, rectangle(6, 6), holes=[rectangle(2, 4)])
    assert "must be closed" in str(failure(lambda: scad.trim_surface_rface(carrier, wire([line((-1, 0, 0), (1, 0, 0))]))))
    assert "must be simple" in str(
        failure(lambda: scad.trim_surface_rface(carrier, scad._native._surface_testing.polygon([(-2, -2, 0), (2, 2, 0), (-2, 2, 0), (2, -2, 0)])))
    )
    assert "intersection is empty" in str(failure(lambda: scad.trim_surface_rface(bounded, rectangle(1, 1))))
    assert "produced 2 disconnected Faces" in str(failure(lambda: scad.trim_surface_rface(bounded, rectangle(4, 2))))
    cylinder = scad.make_cylindrical_surface_rface(2.0, (0.0, 2 * math.pi), (0.0, 2.0))
    assert "holes is not supported" in str(
        failure(lambda: scad.trim_surface_rface(cylinder, rectangle(1, 1, (2, 0, 1)), holes=[rectangle(0.25, 0.25, (2, 0, 1))]))
    )
    partial = scad.make_cylindrical_surface_rface(2.0, (0.0, 1.0), (0.0, 2.0))
    assert "bounded carrier" in str(failure(lambda: scad.trim_surface_rface(partial, cylinder_patch(2.0, 2.0, 2.5))))
    err = failure(lambda: scad.trim_surface_rface(carrier, rectangle(4, 4), tolerance=0.0))
    assert err.operation == "trim_surface_rface"
    assert "What happened:" in str(err)

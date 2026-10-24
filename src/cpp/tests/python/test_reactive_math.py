"""simplecadapi.math: ports of the fitting tests of test_math_helpers.py (the
make_spline_redge tests belong to the geometry operators)."""

import math

import pytest

import simplecadapi._cpp as scad
import simplecadapi._cpp.math as scmath
from ref import close, golden


def _distance(a, b):
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def _semicircle(count=21):
    return [(math.cos(i * math.pi / (count - 1)), math.sin(i * math.pi / (count - 1)), 0.0) for i in range(count)]


def test_fit_line_returns_minimal_cubic_controls():
    samples = [(float(i), 0.0, 0.0) for i in range(8)]
    result = scmath.fit_cubic_bspline_control_points(samples, tolerance=1e-10)
    assert result.converged
    assert result.control_count == 4
    assert result.dimension == 3
    assert result.max_error <= 1e-10
    assert result.unique_knots == (0.0, 1.0)
    assert result.multiplicities == (4, 4)
    assert result.evaluate(0.0) == pytest.approx(samples[0])
    assert result.evaluate(1.0) == pytest.approx(samples[-1])
    assert result.evaluate(0.5) == pytest.approx((3.5, 0.0, 0.0))


def test_fit_semicircle_adaptively_inserts_simple_knots():
    samples = _semicircle()
    result = scad.fit_cubic_bspline_control_points(samples, tolerance=0.002)
    assert result.converged
    assert 4 < result.control_count < len(samples)
    assert result.max_error <= result.tolerance
    assert result.multiplicities[0] == 4 and result.multiplicities[-1] == 4
    assert all(m == 1 for m in result.multiplicities[1:-1])
    errors = [_distance(result.evaluate(p), s) for p, s in zip(result.sample_parameters, samples)]
    assert max(errors) <= result.tolerance


def test_fit_accepts_2d_samples_and_serializes_result():
    samples = [(0.0, 0.0), (0.25, 0.2), (0.5, -0.1), (0.75, 0.2), (1.0, 0.0)]
    result = scmath.fit_cubic_bspline_control_points(samples, tolerance=0.05, fairing=1e-3)
    payload = result.to_dict()
    assert result.converged and result.dimension == 2
    assert payload["degree"] == 3
    assert payload["control_points"] == [list(p) for p in result.control_points]
    assert payload["unique_knots"] == list(result.unique_knots)
    assert payload["multiplicities"] == list(result.multiplicities)
    assert payload["converged"] is True


def test_fit_removes_consecutive_duplicate_samples():
    samples = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    result = scmath.fit_cubic_bspline_control_points(samples, tolerance=1e-10)
    assert result.converged and len(result.sample_parameters) == 3 and result.max_error <= 1e-10


def test_fit_returns_best_result_when_failure_is_allowed():
    result = scmath.fit_cubic_bspline_control_points(
        _semicircle(), tolerance=1e-6, max_control_points=4, raise_on_failure=False
    )
    assert not result.converged and result.control_count == 4 and result.max_error > result.tolerance


def test_fit_raises_when_tolerance_cannot_be_met():
    with pytest.raises(ValueError, match="failed to fit a cubic B-spline"):
        scmath.fit_cubic_bspline_control_points(_semicircle(), tolerance=1e-6, max_control_points=4)


@pytest.mark.parametrize(
    ("samples", "match"),
    [
        ([], "at least two distinct points"),
        ([(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)], "at least two distinct points"),
        ([(0.0, 0.0), (1.0, 0.0, 0.0)], "same dimension"),
        ([(0.0,), (1.0,)], "2D or 3D"),
        ([(0.0, 0.0), (math.nan, 1.0)], "finite"),
        ([(0.0, 0.0), ("a", 1.0)], "not a numeric sequence"),
    ],
)
def test_fit_validates_sample_points(samples, match):
    with pytest.raises(ValueError, match=match):
        scmath.fit_cubic_bspline_control_points(samples)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"tolerance": 0.0}, "tolerance"),
        ({"fairing": -1.0}, "fairing"),
        ({"duplicate_tolerance": -1.0}, "duplicate_tolerance"),
        ({"knot_tolerance": 0.0}, "knot_tolerance"),
        ({"max_control_points": 3}, "max_control_points"),
    ],
)
def test_fit_validates_options(kwargs, match):
    samples = [(0.0, 0.0, 0.0), (0.5, 0.1, 0.0), (1.0, 0.0, 0.0)]
    with pytest.raises(ValueError, match=match):
        scmath.fit_cubic_bspline_control_points(samples, **kwargs)


def test_math_helper_is_public_through_top_level_and_submodule():
    assert scad.fit_cubic_bspline_control_points is scmath.fit_cubic_bspline_control_points
    assert scad.BSplineFitResult is scmath.BSplineFitResult
    assert scad.math is scmath


def test_fits_match_the_reference():
    cases = {
        "line": ("[(float(i), 0.0, 0.0) for i in range(8)]", {"tolerance": 1e-10}),
        "semicircle": ("[(math.cos(i * math.pi / 20), math.sin(i * math.pi / 20), 0.0) for i in range(21)]", {"tolerance": 0.002}),
        "wave": ("[(i / 10.0, math.sin(i / 3.0) * 0.4) for i in range(30)]", {"tolerance": 0.01, "fairing": 1e-4}),
        "helix": ("[(math.cos(t), math.sin(t), t / 4.0) for t in [i * 0.2 for i in range(40)]]", {"tolerance": 0.005}),
        "pair": ("[(0.0, 0.0, 0.0), (3.0, 4.0, 0.0)]", {}),
    }
    expected = golden(
        "reactive_bspline_fits",
        f"""
        import math
        from simplecadapi.math import fit_cubic_bspline_control_points
        result = {{}}
        for name, (source, kwargs) in {cases!r}.items():
            result[name] = fit_cubic_bspline_control_points(eval(source), **kwargs).to_dict()
        """,
    )
    for name, (source, kwargs) in cases.items():
        got = scmath.fit_cubic_bspline_control_points(eval(source), **kwargs).to_dict()
        want = expected[name]
        assert got["multiplicities"] == want["multiplicities"], name
        assert got["knots"] == pytest.approx(want["knots"], abs=1e-9), name
        assert len(got["control_points"]) == len(want["control_points"]), name
        assert close(got["control_points"], want["control_points"], rel=1e-5, abs_=1e-7), name
        assert got["converged"] == want["converged"] and got["iterations"] == want["iterations"], name
        assert got["max_error"] == pytest.approx(want["max_error"], abs=1e-8), name

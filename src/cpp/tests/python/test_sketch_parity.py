"""Solved sketches against the reference SDK (py-slvs): same points, DOF and status.

Each case is a snippet that builds a sketch with `scad` (the reference module when
recording the golden file, simplecadapi._cpp here) and leaves a JSON summary in
`result`.  The golden file is the contract; see tests/python/ref.py.
"""

import textwrap

import pytest
from ref import close, golden

import simplecadapi._cpp as scad_cpp

_SUMMARY = """
        def summarize(r):
            return {
                "status": r.status,
                "dof": r.dof,
                "points": {k: [round(v[0], 7), round(v[1], 7)] for k, v in sorted(r.solved_points.items())},
                "scalars": {k: round(v, 7) for k, v in sorted(r.solved_scalars.items())},
            }
"""

_CASES = {
    "rect_redundant": """
        s = scad.make_sketch_rsketch("rect")
        for pid, (x, y) in {"p0": (0, 0), "p1": (2, 0), "p2": (2, 1), "p3": (0, 1)}.items():
            s = scad.add_point_rsketch(s, pid, float(x), float(y))
        for e, (a, b) in {"bottom": ("p0", "p1"), "right": ("p1", "p2"), "top": ("p2", "p3"), "left": ("p3", "p0")}.items():
            s = scad.add_line_rsketch(s, e, a, b)
        s = scad.constrain_horizontal_rsketch(s, "bottom")
        s = scad.constrain_vertical_rsketch(s, "right")
        s = scad.constrain_parallel_rsketch(s, "bottom", "top")
        s = scad.constrain_parallel_rsketch(s, "left", "right")
        s = scad.constrain_perpendicular_rsketch(s, "bottom", "right")
        s = scad.constrain_equal_length_rsketch(s, "bottom", "top")
        s = scad.constrain_equal_length_rsketch(s, "left", "right")
        s = scad.constrain_distance_rsketch(s, "p0", "p1", 2.0)
        s = scad.constrain_distance_rsketch(s, "p0", "p3", 1.0)
        s = scad.constrain_fix_rsketch(s, "p0")
        result = summarize(scad.inspect_sketch_rsketchresult(s, require_fully_constrained=True))
    """,
    "arc_radius": """
        s = scad.make_sketch_rsketch("arc_radius")
        s = scad.add_point_rsketch(s, "start", 2.0, 0.0)
        s = scad.add_point_rsketch(s, "end", 0.0, 2.0)
        s = scad.add_point_rsketch(s, "center", 0.0, 0.0)
        s = scad.add_arc_rsketch(s, "arc", "start", "end", "center")
        s = scad.constrain_fix_rsketch(s, "center")
        s = scad.constrain_radius_rsketch(s, "arc", 2.0)
        s = scad.constrain_point_on_rsketch(s, "end", "arc")
        result = summarize(scad.inspect_sketch_rsketchresult(s, strict=False))
    """,
    "angle_200": """
        import math
        s = scad.make_sketch_rsketch("angle")
        r = math.radians(200.0)
        for pid, (x, y) in {"p0": (0, 0), "p1": (4, 0), "p2": (1, 1), "p3": (1 + 3 * math.cos(r), 1 + 3 * math.sin(r))}.items():
            s = scad.add_point_rsketch(s, pid, float(x), float(y))
        s = scad.add_line_rsketch(s, "a", "p0", "p1")
        s = scad.add_line_rsketch(s, "b", "p2", "p3")
        for p in ("p0", "p1", "p2"):
            s = scad.constrain_fix_rsketch(s, p)
        s = scad.constrain_length_rsketch(s, "b", 3.0)
        s = scad.constrain_angle_rsketch(s, "a", "b", 200.0)
        result = summarize(scad.inspect_sketch_rsketchresult(s, require_fully_constrained=True))
    """,
    "line_distance_below": """
        s = scad.make_sketch_rsketch("offset")
        for pid, (x, y) in {"b0": (0, 0), "b1": (5, 0), "a0": (1, -1.8), "a1": (5, -1.8)}.items():
            s = scad.add_point_rsketch(s, pid, float(x), float(y))
        s = scad.add_line_rsketch(s, "base", "b0", "b1")
        s = scad.add_line_rsketch(s, "offset", "a0", "a1")
        s = scad.constrain_fix_rsketch(s, "b0")
        s = scad.constrain_fix_rsketch(s, "b1")
        s = scad.constrain_length_rsketch(s, "offset", 4.0)
        s = scad.constrain_parallel_rsketch(s, "offset", "base")
        s = scad.constrain_distance_x_rsketch(s, "b0", "a0", 1.0)
        s = scad.constrain_line_distance_rsketch(s, "offset", "base", 2.5)
        result = summarize(scad.inspect_sketch_rsketchresult(s, strict=False))
    """,
    "mirror_flipped": """
        s = scad.make_sketch_rsketch("mirror")
        for pid, (x, y) in {"a0": (0, 0), "a1": (0, 4), "m0": (1, 1), "m1": (1, 3), "n0": (-1.1, 2.9), "n1": (-1.2, 1.15)}.items():
            s = scad.add_point_rsketch(s, pid, float(x), float(y))
        s = scad.add_line_rsketch(s, "axis", "a0", "a1")
        s = scad.add_line_rsketch(s, "source", "m0", "m1")
        s = scad.add_line_rsketch(s, "image", "n0", "n1")
        for p in ("a0", "a1", "m0", "m1"):
            s = scad.constrain_fix_rsketch(s, p)
        s = scad.constrain_mirror_rsketch(s, "image", "axis", "source")
        result = summarize(scad.inspect_sketch_rsketchresult(s, strict=False))
    """,
    "symmetric_diagonal": """
        s = scad.make_sketch_rsketch("sym")
        for pid, (x, y) in {"a0": (0, 0), "a1": (3, 3), "p": (1, 3), "q": (2.6, 1.2)}.items():
            s = scad.add_point_rsketch(s, pid, float(x), float(y))
        s = scad.add_line_rsketch(s, "axis", "a0", "a1")
        for p in ("a0", "a1", "p"):
            s = scad.constrain_fix_rsketch(s, p)
        s = scad.constrain_symmetric_rsketch(s, "q", "p", "axis")
        result = summarize(scad.inspect_sketch_rsketchresult(s, strict=False))
    """,
    "tangent_internal": """
        s = scad.make_sketch_rsketch("t")
        s = scad.add_point_rsketch(s, "a", 0.0, 0.0)
        s = scad.add_point_rsketch(s, "b", 1.0, 0.0)
        s = scad.add_circle_rsketch(s, "left", "a", 2.0)
        s = scad.add_circle_rsketch(s, "right", "b", 1.0)
        s = scad.constrain_fix_rsketch(s, "left")
        s = scad.constrain_fix_rsketch(s, "right")
        s = scad.constrain_tangent_rsketch(s, "left", "right", mode="internal")
        result = summarize(scad.inspect_sketch_rsketchresult(s, require_fully_constrained=True))
    """,
    "u_path": """
        L, H, R = 80.0, 20.0, 17.0
        xl, xr = -L / 2, L / 2
        seeds = {"lt": (xl, H), "l1": (xl, R), "cl": (xl + R, R), "b1": (xl + R, 0.0), "b2": (xr - R, 0.0),
                 "cr": (xr - R, R), "r1": (xr, R), "rt": (xr, H)}
        s = scad.make_sketch_rsketch("u_path")
        for pid, (x, y) in seeds.items():
            s = scad.add_point_rsketch(s, pid, x, y)
        s = scad.add_line_rsketch(s, "arm_l", "lt", "l1")
        s = scad.add_arc_rsketch(s, "corner_l", "l1", "b1", "cl")
        s = scad.add_line_rsketch(s, "bottom", "b1", "b2")
        s = scad.add_arc_rsketch(s, "corner_r", "b2", "r1", "cr")
        s = scad.add_line_rsketch(s, "arm_r", "r1", "rt")
        s = scad.constrain_fix_rsketch(s, "b1")
        s = scad.constrain_vertical_rsketch(s, "arm_l")
        s = scad.constrain_vertical_rsketch(s, "arm_r")
        s = scad.constrain_horizontal_rsketch(s, "bottom")
        s = scad.constrain_tangent_rsketch(s, "arm_l", "corner_l", at_b="start")
        s = scad.constrain_tangent_rsketch(s, "corner_l", "bottom", at_a="end")
        s = scad.constrain_tangent_rsketch(s, "bottom", "corner_r", at_b="start")
        s = scad.constrain_tangent_rsketch(s, "corner_r", "arm_r", at_a="end")
        s = scad.constrain_equal_radius_rsketch(s, "corner_l", "corner_r")
        s = scad.constrain_radius_rsketch(s, "corner_l", R)
        s = scad.constrain_distance_x_rsketch(s, "lt", "rt", L)
        s = scad.constrain_distance_y_rsketch(s, "b1", "lt", H)
        s = scad.constrain_distance_y_rsketch(s, "b1", "rt", H)
        result = summarize(scad.inspect_sketch_rsketchresult(s, require_fully_constrained=True))
    """,
    "ellipse_radii": """
        import math
        t = math.radians(30.0)
        s = scad.make_sketch_rsketch("oval")
        s = scad.add_point_rsketch(s, "c", 0.0, 0.0)
        s = scad.add_point_rsketch(s, "M", 4 * math.cos(t), 4 * math.sin(t))
        s = scad.add_point_rsketch(s, "m", -2 * math.sin(t), 2 * math.cos(t))
        s = scad.add_ellipse_rsketch(s, "oval", "c", "M", "m")
        s = scad.constrain_fix_rsketch(s, "c")
        s = scad.constrain_major_radius_rsketch(s, "oval", 4.0)
        s = scad.constrain_minor_radius_rsketch(s, "oval", 2.0)
        result = summarize(scad.inspect_sketch_rsketchresult(s))
    """,
    "midpoint_points": """
        s = scad.make_sketch_rsketch("midpoint")
        s = scad.add_point_rsketch(s, "a", 0.0, 0.0)
        s = scad.add_point_rsketch(s, "b", 4.0, 2.0)
        s = scad.add_point_rsketch(s, "m", 1.8, 0.9)
        s = scad.constrain_fix_rsketch(s, "a")
        s = scad.constrain_fix_rsketch(s, "b")
        s = scad.constrain_midpoint_points_rsketch(s, "m", "a", "b")
        result = summarize(scad.inspect_sketch_rsketchresult(s, require_fully_constrained=True))
    """,
    "tangent_line_circle": """
        s = scad.make_sketch_rsketch("tl")
        for pid, (x, y) in {"c": (0, 0), "p0": (-3, 1.4), "p1": (3, 1.6)}.items():
            s = scad.add_point_rsketch(s, pid, float(x), float(y))
        s = scad.add_circle_rsketch(s, "k", "c", 1.0)
        s = scad.add_line_rsketch(s, "l", "p0", "p1")
        s = scad.constrain_fix_rsketch(s, "c")
        s = scad.constrain_radius_rsketch(s, "k", 1.0)
        s = scad.constrain_fix_rsketch(s, "p0")
        s = scad.constrain_length_rsketch(s, "l", 6.0)
        s = scad.constrain_tangent_rsketch(s, "l", "k")
        result = summarize(scad.inspect_sketch_rsketchresult(s, strict=False))
    """,
    "collinear_concentric_equal_radius": """
        s = scad.make_sketch_rsketch("cce")
        for pid, (x, y) in {"a0": (0, 0), "a1": (4, 0.2), "b0": (5, 1), "b1": (9, 1.5), "c1": (0, 5), "c2": (3.2, 5.4)}.items():
            s = scad.add_point_rsketch(s, pid, float(x), float(y))
        s = scad.add_line_rsketch(s, "a", "a0", "a1")
        s = scad.add_line_rsketch(s, "b", "b0", "b1")
        s = scad.add_circle_rsketch(s, "k1", "c1", 1.0)
        s = scad.add_circle_rsketch(s, "k2", "c2", 1.5)
        s = scad.constrain_fix_rsketch(s, "a0")
        s = scad.constrain_fix_rsketch(s, "a1")
        s = scad.constrain_collinear_rsketch(s, "a", "b")
        s = scad.constrain_distance_x_rsketch(s, "a0", "b0", 5.0)
        s = scad.constrain_distance_x_rsketch(s, "b0", "b1", 4.0)
        s = scad.constrain_fix_rsketch(s, "c1")
        s = scad.constrain_concentric_rsketch(s, "k1", "k2")
        s = scad.constrain_radius_rsketch(s, "k1", 2.0)
        s = scad.constrain_equal_radius_rsketch(s, "k1", "k2")
        result = summarize(scad.inspect_sketch_rsketchresult(s, strict=False))
    """,
    "perturbed_angle": """
        import math
        s = scad.make_sketch_rsketch("angle")
        r = math.radians(207.0)
        for pid, (x, y) in {"p0": (0, 0), "p1": (4, 0), "p2": (1, 1), "p3": (1 + 3 * math.cos(r), 1 + 3 * math.sin(r))}.items():
            s = scad.add_point_rsketch(s, pid, float(x), float(y))
        s = scad.add_line_rsketch(s, "a", "p0", "p1")
        s = scad.add_line_rsketch(s, "b", "p2", "p3")
        for p in ("p0", "p1", "p2"):
            s = scad.constrain_fix_rsketch(s, p)
        s = scad.constrain_length_rsketch(s, "b", 3.0)
        s = scad.constrain_angle_rsketch(s, "a", "b", 200.0)
        result = summarize(scad.inspect_sketch_rsketchresult(s))
    """,
    "bspline_reference_length": """
        s = scad.make_sketch_rsketch("spline_measure")
        s = scad.add_point_rsketch(s, "a", 0.0, 0.0)
        s = scad.add_point_rsketch(s, "b", 3.0, 0.0)
        s = scad.add_bspline_rsketch(s, "curve", "a", "b", [(0.0, 0.0), (1.0, 1.0), (2.0, 1.0), (3.0, 0.0)],
                                     knots=[0.0, 1.0], multiplicities=[4, 4])
        s = scad.constrain_fix_rsketch(s, "curve")
        s = scad.constrain_length_rsketch(s, "curve", 0.0, driving=False, constraint_id="curve_length")
        result = summarize(scad.inspect_sketch_rsketchresult(s, require_fully_constrained=True))
    """,
    "midpoint_and_point_on_line": """
        s = scad.make_sketch_rsketch("mp")
        for pid, (x, y) in {"a": (0, 0), "b": (6, 2), "m": (2.5, 0.5), "q": (4, 5)}.items():
            s = scad.add_point_rsketch(s, pid, float(x), float(y))
        s = scad.add_line_rsketch(s, "ab", "a", "b")
        s = scad.constrain_fix_rsketch(s, "a")
        s = scad.constrain_fix_rsketch(s, "b")
        s = scad.constrain_midpoint_rsketch(s, "m", "ab")
        s = scad.constrain_point_on_rsketch(s, "q", "ab")
        s = scad.constrain_distance_x_rsketch(s, "a", "q", 4.5)
        result = summarize(scad.inspect_sketch_rsketchresult(s, require_fully_constrained=True))
    """,
    "conflict_names": """
        s = scad.make_sketch_rsketch("c")
        s = scad.add_point_rsketch(s, "p1", 0.0, 0.0)
        s = scad.add_point_rsketch(s, "p2", 10.0, 0.0)
        s = scad.constrain_distance_rsketch(s, "p1", "p2", 5.0, constraint_id="A")
        s = scad.constrain_distance_rsketch(s, "p1", "p2", 20.0, constraint_id="B")
        s = scad.constrain_distance_rsketch(s, "p1", "p2", 7.0, constraint_id="C")
        r = scad.inspect_sketch_rsketchresult(s, strict=False)
        result = summarize(r)
        result["failed"] = [d.constraint_id for d in r.diagnostics]
        result["codes"] = sorted({d.code for d in r.diagnostics})
    """,
}


def _ours(snippet: str):
    namespace = {"scad": scad_cpp, "result": None}
    exec(textwrap.dedent(_SUMMARY), namespace)
    exec(textwrap.dedent(snippet), namespace)
    return namespace["result"]


# py-slvs reports DOF 0 / "solved" whenever it also reports redundant constraints (status
# code 5), even when degrees of freedom remain; scad-native reports the rank-based count.
# Positions still have to agree.  See docs/sketch-solver.md.
_REPORTS_REAL_DOF = {"arc_radius": {"status": "underconstrained", "dof": 2}}


@pytest.mark.parametrize("name", sorted(_CASES))
def test_solution_matches_reference(name):
    snippet = _CASES[name]
    expected = golden(f"sketch_parity_{name}", textwrap.dedent(_SUMMARY) + textwrap.dedent(snippet))
    actual = _ours(snippet)
    if name in _REPORTS_REAL_DOF:
        for key, value in _REPORTS_REAL_DOF[name].items():
            assert actual[key] == value
            actual[key] = expected[key]
    assert close(actual, expected, rel=1e-6, abs_=1e-6), f"{name}: {actual} != {expected}"

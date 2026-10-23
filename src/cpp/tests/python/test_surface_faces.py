"""Faces from numbers and edges, against the reference SDK (golden files tests/golden/surface_*.json)."""

import math

import pytest

import simplecadapi._cpp as scad
from ref import golden
from surface_support import REF_PRELUDE, arc, circle, close_to, line, measure, rectangle, spline  # noqa: F401


def compare(name, ref_body, native_result, rel=1e-6):
    expected = golden(name, REF_PRELUDE + ref_body)
    assert close_to(native_result, expected, rel=rel), f"{name}:\nnative   {native_result}\nreference {expected}"


WAVE_GRID = [[(i, j, 0.4 * math.sin(i) * math.cos(0.7 * j)) for j in range(5)] for i in range(5)]


def test_bezier_flat_and_curved():
    flat = [[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 0)]]
    curved = [[(0, 0, 0), (0, 1, 0.5), (0, 2, 0)], [(1, 0, 0.2), (1, 1, 1), (1, 2, 0.1)], [(2, 0, 0), (2, 1, 0.3), (2, 2, 0)]]
    compare(
        "surface_bezier",
        f"""
result = {{"flat": measure(scad.make_bezier_surface_rface({flat!r})),
           "curved": measure(scad.make_bezier_surface_rface({curved!r}, tag_prefix="skin"))}}
""",
        {"flat": measure(scad.make_bezier_surface_rface(flat)),
         "curved": measure(scad.make_bezier_surface_rface(curved, tag_prefix="skin"))},
    )
    assert "skin.face" in scad.make_bezier_surface_rface(curved, tag_prefix="skin")._list_tags()


def test_bezier_weighted_and_placed_in_a_workplane():
    grid = [[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 1)]]
    weights = [[1, 1], [1, 2]]
    ref_body = f"""
with scad.Workplane(origin=(10.0, 20.0, 30.0), normal=(0.0, 1.0, 0.0), x_dir=(1.0, 0.0, 0.0)):
    placed = scad.make_bezier_surface_rface({grid!r})
result = {{"weighted": measure(scad.make_bezier_surface_rface({grid!r}, {weights!r})),
           "placed": measure(placed), "center": list(placed.get_center())}}
"""
    with scad.Workplane(origin=(10.0, 20.0, 30.0), normal=(0.0, 1.0, 0.0), x_dir=(1.0, 0.0, 0.0)):
        placed = scad.make_bezier_surface_rface(grid)
    compare(
        "surface_bezier_weighted_placed",
        ref_body,
        {"weighted": measure(scad.make_bezier_surface_rface(grid, weights)), "placed": measure(placed),
         "center": list(placed.get_center())},
    )


def test_cylindrical_surfaces():
    ref_body = """
result = {"full": measure(scad.make_cylindrical_surface_rface(2.0, (0.0, 2 * math.pi), (0.0, 2.0))),
          "partial": measure(scad.make_cylindrical_surface_rface(
              1.5, (0.5, 2.0), (-1.0, 3.0), origin=(1.0, 2.0, 3.0), axis=(1.0, 1.0, 0.0), x_direction=(0.0, 0.0, 1.0),
              tolerance=1e-6, tag_prefix="carrier"))}
"""
    compare(
        "surface_cylinder",
        ref_body,
        {"full": measure(scad.make_cylindrical_surface_rface(2.0, (0.0, 2 * math.pi), (0.0, 2.0))),
         "partial": measure(scad.make_cylindrical_surface_rface(
             1.5, (0.5, 2.0), (-1.0, 3.0), origin=(1.0, 2.0, 3.0), axis=(1.0, 1.0, 0.0), x_direction=(0.0, 0.0, 1.0),
             tolerance=1e-6, tag_prefix="carrier"))},
    )


def test_fit_point_grid():
    compare(
        "surface_fit_point_grid",
        f"""
grid = {WAVE_GRID!r}
result = {{"default": measure(scad.fit_point_grid_rface(grid)),
           "linear": measure(scad.fit_point_grid_rface(grid, degree_min=1, degree_max=1, tolerance=1e-2)),
           "smooth": measure(scad.fit_point_grid_rface(grid, smoothing=(1.0, 0.5, 0.1)))}}
""",
        {"default": measure(scad.fit_point_grid_rface(WAVE_GRID)),
         "linear": measure(scad.fit_point_grid_rface(WAVE_GRID, degree_min=1, degree_max=1, tolerance=1e-2)),
         "smooth": measure(scad.fit_point_grid_rface(WAVE_GRID, smoothing=(1.0, 0.5, 0.1)))},
        rel=1e-7,
    )


def test_ruled_surface():
    compare(
        "surface_ruled",
        """
result = {"lines": measure(scad.make_ruled_surface_rface(line((0, 0, 0), (2, 0, 0)), line((0, 1, 1), (3, 1, 2)))),
          "arcs": measure(scad.make_ruled_surface_rface(arc((1, 0, 0), (0, 1, 0), (-1, 0, 0)),
                                                         arc((2, 0, 1), (0, 2, 1), (-2, 0, 1))))}
""",
        {"lines": measure(scad.make_ruled_surface_rface(line((0, 0, 0), (2, 0, 0)), line((0, 1, 1), (3, 1, 2)))),
         "arcs": measure(scad.make_ruled_surface_rface(arc((1, 0, 0), (0, 1, 0), (-1, 0, 0)),
                                                        arc((2, 0, 1), (0, 2, 1), (-2, 0, 1))))},
    )


def test_gordon_bilinear_network_is_exact():
    profiles = [((0, 0, 0), (1, 0, 0)), ((0, 1, 0), (1, 1, 0))]
    guides = [((0, 0, 0), (0, 1, 0)), ((1, 0, 0), (1, 1, 0))]
    compare(
        "surface_gordon_bilinear",
        f"""
result = measure(scad.make_gordon_surface_rface([line(*p) for p in {profiles!r}], [line(*g) for g in {guides!r}]))
""",
        measure(scad.make_gordon_surface_rface([line(*p) for p in profiles], [line(*g) for g in guides])),
        rel=1e-9,
    )


WAVY_NETWORK = """
n = 6
side, amp = 4.0, 1.0
def z_of(u, v):
    return amp * math.sin(math.pi * u) ** 2 * math.sin(math.pi * v) ** 2 * math.sin(2 * math.pi * u) * math.sin(3 * math.pi * v)
def point_on(u, v):
    return ((u - 0.5) * 2 * side, (v - 0.5) * 2 * side, z_of(u, v))
corners = [(-side, -side, 0.0), (side, -side, 0.0), (side, side, 0.0), (-side, side, 0.0)]
def profile(row):
    if row == 0:
        return line(corners[0], corners[1])
    if row == n - 1:
        return line(corners[3], corners[2])
    return spline([point_on(k / (n - 1), row / (n - 1)) for k in range(n)])
def guide(col):
    if col == 0:
        return line(corners[0], corners[3])
    if col == n - 1:
        return line(corners[1], corners[2])
    return spline([point_on(col / (n - 1), k / (n - 1)) for k in range(n)])
profiles = [profile(r) for r in range(n)]
guides = [guide(c) for c in range(n)]
"""


def test_gordon_wavy_network_matches_within_fit_tolerance():
    scope = {"math": math, "line": line, "spline": spline}
    exec(WAVY_NETWORK, scope)
    expected = golden(
        "surface_gordon_wavy",
        REF_PRELUDE + WAVY_NETWORK + "result = measure(scad.make_gordon_surface_rface(profiles, guides, tolerance=1e-4))",
    )
    got = measure(scad.make_gordon_surface_rface(scope["profiles"], scope["guides"], tolerance=1e-4))
    assert close_to(got, expected, rel=2e-4, abs_=2e-4), f"native {got}\nreference {expected}"


def test_surface_patch_fills_a_square_and_a_point_constraint():
    corners = [(0, 0, 1), (2, 0, 1), (2, 2, 1), (0, 2, 1)]
    ref_body = f"""
corners = {corners!r}
edges = [line(corners[i], corners[(i + 1) % 4]) for i in range(4)]
bounds = [scad.SurfaceBoundary(e) for e in edges]
result = {{"plain": measure(scad.make_surface_patch_rface(bounds, tag_prefix="patch")),
          "pulled": measure(scad.make_surface_patch_rface(bounds, points=[(1.0, 1.0, 1.5)])),
          "holed": measure(scad.make_surface_patch_rface(bounds, holes=[rectangle(0.5, 0.5, center=(1, 1, 1))]))}}
"""
    edges = [line(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    bounds = [scad.SurfaceBoundary(e) for e in edges]
    compare(
        "surface_patch",
        ref_body,
        {"plain": measure(scad.make_surface_patch_rface(bounds, tag_prefix="patch")),
         "pulled": measure(scad.make_surface_patch_rface(bounds, points=[(1.0, 1.0, 1.5)])),
         "holed": measure(scad.make_surface_patch_rface(bounds, holes=[rectangle(0.5, 0.5, center=(1, 1, 1))]))},
        rel=1e-5,
    )

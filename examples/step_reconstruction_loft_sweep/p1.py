# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "p1"
# revision = "1.0.0"
# ///
"""Rebuild varying sections along a recovered curved spine (P1)."""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- params: measured section stations and spine ----
    STATIONS = (
        ((0.0, 0.0, 0.0), (0.3, 0.0, 1.0), 8.0, 4.0),
        ((3.0, 0.0, 10.0), (0.0, 0.0, 1.0), 14.0, 9.0),
        ((0.0, 0.0, 20.0), (-0.3, 0.0, 1.0), 5.0, 3.0),
    )
    PATH_POINTS = ((0.0, 0.0, 0.0), (3.0, 0.0, 10.0), (0.0, 0.0, 20.0))
    return PATH_POINTS, STATIONS


@app.cell
def _(PATH_POINTS, STATIONS):
    # ---- feature: curved-path-loft (build, profile=geometry, path=geometry) ----
    _sections = [
        scad.make_rectangle_rwire(width=width, height=height, center=center, normal=normal)
        for center, normal, width, height in STATIONS
    ]
    _path = scad.make_interpolated_spline_rwire(points=PATH_POINTS)
    curved_path_loft = scad.loft_multisection_rsolid(profiles=_sections, path=_path)
    print("p1 volume", round(curved_path_loft.get_volume(), 6))
    return (curved_path_loft,)


@app.cell
def _(curved_path_loft):
    p1 = scad.Part(part_id="p1", body=curved_path_loft)
    return (p1,)


if __name__ == "__main__":
    app.run()

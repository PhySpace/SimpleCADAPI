# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "s1"
# revision = "1.0.0"
# ///
"""Rebuild the constant-section sweep from the S1 STEP analysis evidence."""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- params: measured profile and recovered path ----
    PROFILE_WIDTH, PROFILE_HEIGHT = 2.0, 1.0
    PATH_POINTS = ((0.0, 0.0, 0.0), (1.0, 0.0, 2.0), (3.0, 1.0, 4.0), (5.0, 0.0, 6.0))
    IS_FRENET = False
    return IS_FRENET, PATH_POINTS, PROFILE_HEIGHT, PROFILE_WIDTH


@app.cell
def _(IS_FRENET, PATH_POINTS, PROFILE_HEIGHT, PROFILE_WIDTH):
    # ---- feature: curved-swept-body (build, profile=geometry, path=geometry) ----
    _profile = scad.make_rectangle_rface(width=PROFILE_WIDTH, height=PROFILE_HEIGHT)
    _path = scad.make_interpolated_spline_rwire(points=PATH_POINTS)
    curved_swept_body = scad.sweep_rsolid(profile=_profile, path=_path, is_frenet=IS_FRENET)
    print("s1 volume", round(curved_swept_body.get_volume(), 6))
    return (curved_swept_body,)


@app.cell
def _(curved_swept_body):
    s1 = scad.Part(part_id="s1", body=curved_swept_body)
    return (s1,)


if __name__ == "__main__":
    app.run()

# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "attractor-porous-canopy"
# ///
"""Attractor-driven porous canopy: a Grasshopper-style PCG case.

A cone crown on a flat datum disc, perforated by a polar grid of holes. A
Gaussian attractor field (``attractor.py``) moves and scales every hole: holes
near the attractor grow and shift outward. Moving the attractor animates the
canopy; ``export.py`` runs this notebook once per frame with the attractor
overridden.

    sca run examples/pcg_attractor_canopy/attractor_canopy.py
    uv run python examples/pcg_attractor_canopy/export.py   # frames, GIF, package, STEP/OBJ/STL
    uv run python examples/pcg_attractor_canopy/verify.py   # reopen + animation evidence
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql

    from attractor import CanopyParams, cell_parameters, params_dict


@app.cell
def _():
    # ---- params: shell ----
    RADIUS_MM = 55.0
    HEIGHT_MM = 34.0
    SHELL_THICKNESS_MM = 3.0
    return HEIGHT_MM, RADIUS_MM, SHELL_THICKNESS_MM


@app.cell
def _():
    # ---- params: hole grid ----
    RINGS = 4
    SECTORS = 12
    HOLE_RADIUS_MM = 5.0
    return HOLE_RADIUS_MM, RINGS, SECTORS


@app.cell
def _():
    # ---- params: attractor ----
    ATTRACTOR_X_MM = 18.0
    ATTRACTOR_Y_MM = 8.0
    ATTRACTOR_STRENGTH = 0.7
    TWIST_DEGREES = 28.0
    return ATTRACTOR_STRENGTH, ATTRACTOR_X_MM, ATTRACTOR_Y_MM, TWIST_DEGREES


@app.cell
def _(
    ATTRACTOR_STRENGTH,
    ATTRACTOR_X_MM,
    ATTRACTOR_Y_MM,
    HEIGHT_MM,
    HOLE_RADIUS_MM,
    RADIUS_MM,
    RINGS,
    SECTORS,
    SHELL_THICKNESS_MM,
    TWIST_DEGREES,
):
    canopy_params = CanopyParams(
        radius_mm=RADIUS_MM,
        height_mm=HEIGHT_MM,
        shell_thickness_mm=SHELL_THICKNESS_MM,
        rings=RINGS,
        sectors=SECTORS,
        hole_radius_mm=HOLE_RADIUS_MM,
        attractor_x_mm=ATTRACTOR_X_MM,
        attractor_y_mm=ATTRACTOR_Y_MM,
        attractor_strength=ATTRACTOR_STRENGTH,
        twist_degrees=TWIST_DEGREES,
    )
    canopy_params.validate()
    return (canopy_params,)


@app.cell
def _(canopy_params):
    # ---- feature: canopy-datum (build, profile=geometry) ----
    _base = scad.make_cylinder_rsolid(
        radius=canopy_params.radius_mm,
        height=canopy_params.shell_thickness_mm,
        bottom_face_center=(0.0, 0.0, 0.0),
        result_tag="pcg.canopy.datum",
    )
    _crown = scad.make_cone_rsolid(
        bottom_radius=canopy_params.radius_mm * 0.96,
        top_radius=canopy_params.radius_mm * 0.12,
        height=canopy_params.height_mm - canopy_params.shell_thickness_mm,
        bottom_face_center=(0.0, 0.0, canopy_params.shell_thickness_mm),
        result_tag="pcg.canopy.crown",
    )
    canopy_datum = scad.union_rsolid(_base, _crown)
    print(f"[canopy-datum] volume={canopy_datum.get_volume():.3f} faces={len(ql.faces().resolve(canopy_datum))}")
    return (canopy_datum,)


@app.cell
def _(canopy_params):
    # ---- feature: attractor-hole-tools (subtract, profile=geometry) ----
    # One through cylinder per polar cell, moved and sized by the field.
    def _hole_tool(ring: int, sector: int) -> scad.Solid:
        _x, _y, _radius, _rotation = cell_parameters(canopy_params, ring, sector)
        return scad.make_cylinder_rsolid(
            radius=_radius,
            height=canopy_params.height_mm + 2.0 * canopy_params.shell_thickness_mm,
            bottom_face_center=(_x, _y, -canopy_params.shell_thickness_mm),
        )

    attractor_hole_tools = [
        _hole_tool(_ring, _sector)
        for _ring in range(canopy_params.rings)
        for _sector in range(canopy_params.sectors)
    ]
    print(f"[attractor-hole-tools] count={len(attractor_hole_tools)}")
    return (attractor_hole_tools,)


@app.cell
def _(attractor_hole_tools, canopy_datum, canopy_params):
    # ---- feature: perforated-canopy (subtract, profile=geometry) ----
    perforated_canopy = scad.cut_rsolid(canopy_datum, attractor_hole_tools)
    perforated_canopy.set_metadata("pcg", "attractor_driven_porous_canopy")
    perforated_canopy.set_metadata("parameters", params_dict(canopy_params))
    perforated_canopy.set_metadata("hole_count", len(attractor_hole_tools))
    perforated_canopy.set_metadata("field_definition", "gaussian_attractor")
    print(
        f"[perforated-canopy] volume={perforated_canopy.get_volume():.3f} "
        f"faces={len(ql.faces().resolve(perforated_canopy))}"
    )
    if perforated_canopy.get_volume() <= 0.0:
        raise ValueError("perforated canopy has non-positive volume")
    return (perforated_canopy,)


@app.cell
def _(perforated_canopy):
    attractor_canopy = scad.make_part_rpart(
        part_id=scad.notebook_id(),
        body=perforated_canopy,
        name="Attractor porous canopy",
    )
    return (attractor_canopy,)


if __name__ == "__main__":
    app.run()

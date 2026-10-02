# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "link_bar"
# ///
"""A forged connecting-rod bar: the part family of the four-bar linkage.

Two chamfered bearing eyes joined by an I-beam web, a bearing bore in each
eye and two lightening holes in the web. The bar runs along +X from the
``pivot_a`` eye center; Z-axis pivot connectors sit at both eye centers.

Each bar of the linkage is a member of this family: the assembly uses the
notebook once per bar, with the bar's id and center distance.

    sca run examples/four_bar_linkage/link_bar.py --id crank --set CENTER_DISTANCE=20
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql

    from dimensions import BAR_THICKNESS, EYE_OUTER_RADIUS, PIVOT_BORE_RADIUS

    # I-beam section: flanges top and bottom, a thin mid web between them.
    FLANGE_HALF_WIDTH = EYE_OUTER_RADIUS * 0.55
    MID_WEB_HALF_WIDTH = FLANGE_HALF_WIDTH * 0.45
    FLANGE_THICKNESS = BAR_THICKNESS * 0.3
    EYE_CHAMFER = 0.6
    LIGHTENING_HOLE_RADIUS = 2.2
    # Through cutters overshoot the bar by 1 mm on each side.
    CUTTER_BOTTOM_Z = -BAR_THICKNESS / 2.0 - 1.0
    CUTTER_HEIGHT = BAR_THICKNESS + 2.0


@app.function
def chamfered_eye(center_x: float) -> scad.Solid:
    """One bearing eye at (center_x, 0), both rims chamfered."""
    eye = scad.make_cylinder_rsolid(
        radius=EYE_OUTER_RADIUS,
        height=BAR_THICKNESS,
        bottom_face_center=(center_x, 0.0, -BAR_THICKNESS / 2.0),
    )
    return scad.chamfer_rsolid(
        solid=eye,
        edges=ql.edges().where(ql.prop("geom.type", "==", "CIRCLE")).exactly(2),
        distance=EYE_CHAMFER,
    )


@app.function
def through_cutter(radius: float, center_x: float) -> scad.Solid:
    """A Z cylinder at (center_x, 0) that cuts through the whole bar."""
    return scad.make_cylinder_rsolid(
        radius=radius,
        height=CUTTER_HEIGHT,
        bottom_face_center=(center_x, 0.0, CUTTER_BOTTOM_Z),
    )


@app.cell
def _():
    # ---- params: center distance ----
    CENTER_DISTANCE = 40.0
    return (CENTER_DISTANCE,)


@app.cell
def _():
    # ---- params: lightening ----
    LIGHTENING_HOLES = True
    return (LIGHTENING_HOLES,)


@app.cell
def _(CENTER_DISTANCE):
    # ---- feature: link-blank (build) ----
    # The eyes and the three I-beam slabs are fused in one union.
    _length = CENTER_DISTANCE + 2.0 * EYE_OUTER_RADIUS

    def _slab(half_width: float, depth: float, bottom_z: float) -> scad.Solid:
        return scad.make_box_rsolid(
            width=_length,
            height=half_width * 2.0,
            depth=depth,
            bottom_face_center=(CENTER_DISTANCE / 2.0, 0.0, bottom_z),
        )

    link_blank = scad.union_rsolid(
        [
            chamfered_eye(0.0),
            chamfered_eye(CENTER_DISTANCE),
            _slab(
                MID_WEB_HALF_WIDTH,
                BAR_THICKNESS - 2.0 * FLANGE_THICKNESS,
                -BAR_THICKNESS / 2.0 + FLANGE_THICKNESS,
            ),
            _slab(FLANGE_HALF_WIDTH, FLANGE_THICKNESS, -BAR_THICKNESS / 2.0),
            _slab(FLANGE_HALF_WIDTH, FLANGE_THICKNESS, BAR_THICKNESS / 2.0 - FLANGE_THICKNESS),
        ]
    )
    return (link_blank,)


@app.cell
def _(CENTER_DISTANCE, link_blank):
    # ---- feature: bearing-bores (subtract) ----
    bearing_bores = scad.cut_rsolid(
        link_blank,
        [
            through_cutter(PIVOT_BORE_RADIUS, 0.0),
            through_cutter(PIVOT_BORE_RADIUS, CENTER_DISTANCE),
        ],
    )
    return (bearing_bores,)


@app.cell
def _(CENTER_DISTANCE, LIGHTENING_HOLES, bearing_bores):
    # ---- feature: lightening-holes (subtract) ----
    # Two holes centered in the web between the eyes; a bar too short for
    # them keeps a solid web.
    if LIGHTENING_HOLES and CENTER_DISTANCE > 3.0 * EYE_OUTER_RADIUS:
        _spacing = 0.5 * (CENTER_DISTANCE - 2.0 * EYE_OUTER_RADIUS)
        lightening_holes = scad.cut_rsolid(
            bearing_bores,
            [
                through_cutter(LIGHTENING_HOLE_RADIUS, CENTER_DISTANCE / 2.0 + _sign * _spacing / 2.0)
                for _sign in (-1.0, 1.0)
            ],
        )
    else:
        lightening_holes = bearing_bores
    return (lightening_holes,)


@app.cell
def _(CENTER_DISTANCE, lightening_holes):
    _part_id = scad.notebook_id()
    _steel = scad.make_material_rmaterial(
        material_id="linkage_steel",
        name="Linkage steel",
        density=7.85e-6,
        density_unit="kg/mm^3",
        color=(0.65, 0.65, 0.68),
    )
    _body = scad.apply_tag(shape=lightening_holes, tag=f"role.link_bar.{_part_id}")
    _part = scad.make_part_rpart(part_id=_part_id, body=_body, name=_part_id.replace("_", " "))
    _part = scad.assign_material_rpart(part=_part, material=_steel)
    for _connector_id, _x in (("pivot_a", 0.0), ("pivot_b", CENTER_DISTANCE)):
        _part = scad.add_connector_rpart(
            part=_part,
            connector=scad.make_placement_connector_rconnector(
                connector_id=_connector_id,
                placement=scad.make_placement_rplacement(origin=(_x, 0.0, 0.0)),
            ),
        )
    link_bar = _part
    return (link_bar,)


if __name__ == "__main__":
    app.run()

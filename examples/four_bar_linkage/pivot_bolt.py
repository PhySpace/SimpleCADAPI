# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "pivot_bolt"
# ///
"""Hex-head pivot bolt for the four-bar linkage joints.

A hex-prism head, a washer shoulder and a plain shank the bar stack rotates
on, along Z with the head above the origin plane and the shank through -Z.
The thread is not modeled: MJCF and STEP treat each pivot as a smooth pin,
and the hex head carries the fastener identity.
"""

import marimo

app = marimo.App()

with app.setup:
    import math

    import simplecadapi as scad

    from dimensions import (
        PIVOT_BOLT_HEAD_RADIUS,
        PIVOT_BOLT_HEAD_THICKNESS,
        PIVOT_BOLT_SHAFT_RADIUS,
        PIVOT_BOLT_SHANK_LENGTH,
    )


@app.cell
def _():
    # ---- params ----
    SHANK_LENGTH = PIVOT_BOLT_SHANK_LENGTH
    return (SHANK_LENGTH,)


@app.cell
def _():
    # ---- feature: hex-head (build) ----
    # A regular hexagon on the head radius, extruded up from -head thickness.
    _corners = [
        (
            PIVOT_BOLT_HEAD_RADIUS * math.cos(math.radians(60.0 * _index)),
            PIVOT_BOLT_HEAD_RADIUS * math.sin(math.radians(60.0 * _index)),
            0.0,
        )
        for _index in range(6)
    ]
    _hexagon = scad.make_face_from_wire_rface(
        wire=scad.make_polyline_rwire(points=[*_corners, _corners[0]])
    )
    _prism = scad.extrude_rsolid(
        _hexagon, direction=(0.0, 0.0, 1.0), distance=PIVOT_BOLT_HEAD_THICKNESS
    )
    hex_head = scad.translate_shape(_prism, vector=(0.0, 0.0, -PIVOT_BOLT_HEAD_THICKNESS))
    return (hex_head,)


@app.cell
def _(SHANK_LENGTH, hex_head):
    # ---- feature: shank (add) ----
    _shank = scad.make_cylinder_rsolid(
        radius=PIVOT_BOLT_SHAFT_RADIUS,
        height=SHANK_LENGTH,
        bottom_face_center=(0.0, 0.0, -SHANK_LENGTH),
    )
    _shoulder = scad.make_cylinder_rsolid(
        radius=PIVOT_BOLT_HEAD_RADIUS * 0.8,
        height=0.6,
        bottom_face_center=(0.0, 0.0, -0.3),
    )
    shank = scad.union_rsolid([hex_head, _shank, _shoulder])
    return (shank,)


@app.cell
def _(shank):
    _steel = scad.make_material_rmaterial(
        material_id="bolt_steel",
        name="Bolt steel",
        density=7.85e-6,
        density_unit="kg/mm^3",
        color=(0.25, 0.27, 0.30),
    )
    _body = scad.apply_tag(shape=shank, tag="role.pivot_bolt")
    _part = scad.make_part_rpart(part_id="pivot_bolt", body=_body, name="pivot bolt")
    _part = scad.assign_material_rpart(part=_part, material=_steel)
    # The axis connector sits at the head center.
    pivot_bolt = scad.add_connector_rpart(
        part=_part,
        connector=scad.make_placement_connector_rconnector(
            connector_id="axis", placement=scad.identity_placement_rplacement()
        ),
    )
    return (pivot_bolt,)


if __name__ == "__main__":
    app.run()

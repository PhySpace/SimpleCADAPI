# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "outer_sleeve"
# ///
"""Outer sleeve of the hydraulic cylinder: barrel, rod gland and rear clevis.

X is the stroke axis, the rod exits at +X. Every face carries a ``sleeve.``
tag, and the gland's mount face holds the ``slide_axis`` connector the
assembly mates the piston rod to.
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql

    from common import named_box


@app.cell
def _():
    # ---- params ----
    BORE_RADIUS = 10.5
    PIN_BORE_RADIUS = 4.6
    BOLT_HOLE_RADIUS = 1.8
    # (hole id, y, z) of the four gland bolt holes on a 16 mm circle.
    GLAND_BOLT_HOLES = (
        ("zplus", 0.0, 16.0),
        ("yplus", 16.0, 0.0),
        ("zminus", 0.0, -16.0),
        ("yminus", -16.0, 0.0),
    )
    return BOLT_HOLE_RADIUS, BORE_RADIUS, GLAND_BOLT_HOLES, PIN_BORE_RADIUS


@app.cell
def _():
    # ---- feature: barrel (build) ----
    barrel = scad.make_cylinder_rsolid(
        radius=16.0,
        height=120.0,
        bottom_face_center=(-60.0, 0.0, 0.0),
        axis=(1.0, 0.0, 0.0),
        tag_prefix="hydraulic.sleeve.barrel",
        result_tag="part.hydraulic.sleeve.barrel",
        start_face_tag="sleeve.barrel.face.rear",
        end_face_tag="sleeve.barrel.face.front",
        side_face_tag="sleeve.barrel.face.outer",
    )
    return (barrel,)


@app.cell
def _(barrel):
    # ---- feature: rod-gland (add) ----
    # A flange at the front of the barrel and a nose around the rod exit.
    _flange = scad.make_cylinder_rsolid(
        radius=22.0,
        height=12.0,
        bottom_face_center=(50.0, 0.0, 0.0),
        axis=(1.0, 0.0, 0.0),
        tag_prefix="hydraulic.sleeve.gland.flange",
        result_tag="part.hydraulic.sleeve.gland.flange",
        start_face_tag="sleeve.gland.face.shoulder",
        end_face_tag="sleeve.gland.face.mount",
        side_face_tag="sleeve.gland.face.outer",
    )
    _nose = scad.make_cylinder_rsolid(
        radius=13.0,
        height=10.0,
        bottom_face_center=(58.0, 0.0, 0.0),
        axis=(1.0, 0.0, 0.0),
        tag_prefix="hydraulic.sleeve.gland.nose",
        result_tag="part.hydraulic.sleeve.gland.nose",
        start_face_tag="sleeve.gland.nose.face.rear",
        end_face_tag="sleeve.gland.nose.face.front",
        side_face_tag="sleeve.gland.nose.face.outer",
    )
    rod_gland = scad.union_rsolid(barrel, _flange, _nose, glue=False)
    return (rod_gland,)


@app.cell
def _(rod_gland):
    # ---- feature: rear-clevis (add) ----
    # A base cap closes the barrel; a neck carries the clevis eye behind it.
    _base_cap = scad.make_cylinder_rsolid(
        radius=18.0,
        height=12.0,
        bottom_face_center=(-66.0, 0.0, 0.0),
        axis=(1.0, 0.0, 0.0),
        tag_prefix="hydraulic.sleeve.base.cap",
        result_tag="part.hydraulic.sleeve.base.cap",
        start_face_tag="sleeve.base.cap.face.rear",
        end_face_tag="sleeve.base.cap.face.front",
        side_face_tag="sleeve.base.cap.face.outer",
    )
    _eye = scad.make_cylinder_rsolid(
        radius=14.0,
        height=12.0,
        bottom_face_center=(-80.0, -6.0, 0.0),
        axis=(0.0, 1.0, 0.0),
        tag_prefix="hydraulic.sleeve.rear.eye",
        result_tag="part.hydraulic.sleeve.rear.eye",
        start_face_tag="sleeve.rear.eye.face.ymin",
        end_face_tag="sleeve.rear.eye.face.ymax",
        side_face_tag="sleeve.rear.eye.face.outer",
    )
    _neck = named_box(
        width=18.0,
        height=14.0,
        depth=16.0,
        bottom_face_center=(-68.0, 0.0, -8.0),
        bottom_face_tag="sleeve.rear.neck.face.bottom",
        top_face_tag="sleeve.rear.neck.face.top",
        side_faces_tag="sleeve.rear.neck.face.side",
        tag_prefix="hydraulic.sleeve.rear.neck",
        result_tag="part.hydraulic.sleeve.rear.neck",
    )
    rear_clevis = scad.union_rsolid(rod_gland, _base_cap, _eye, _neck, glue=False)
    return (rear_clevis,)


@app.cell
def _(BORE_RADIUS, rear_clevis):
    # ---- feature: barrel-bore (subtract) ----
    # Runs from inside the base cap out through the gland nose.
    _bore = scad.make_cylinder_rsolid(
        radius=BORE_RADIUS,
        height=136.0,
        bottom_face_center=(-68.0, 0.0, 0.0),
        axis=(1.0, 0.0, 0.0),
        tag_prefix="hydraulic.sleeve.barrel.bore",
        result_tag="tool.hydraulic.sleeve.barrel.bore",
        start_face_tag="sleeve.barrel.bore.face.rear",
        end_face_tag="sleeve.barrel.bore.face.front",
        side_face_tag="sleeve.barrel.bore.face.wall",
    )
    barrel_bore = scad.cut_rsolid(rear_clevis, _bore)
    return (barrel_bore,)


@app.cell
def _(PIN_BORE_RADIUS, barrel_bore):
    # ---- feature: clevis-pin-bore (subtract) ----
    _pin_bore = scad.make_cylinder_rsolid(
        radius=PIN_BORE_RADIUS,
        height=26.0,
        bottom_face_center=(-80.0, -13.0, 0.0),
        axis=(0.0, 1.0, 0.0),
        tag_prefix="hydraulic.sleeve.rear.eye.pin.bore",
        result_tag="tool.hydraulic.sleeve.rear.eye.pin_bore",
        start_face_tag="sleeve.rear.eye.pin.face.ymin",
        end_face_tag="sleeve.rear.eye.pin.face.ymax",
        side_face_tag="sleeve.rear.eye.pin.face.wall",
    )
    clevis_pin_bore = scad.cut_rsolid(barrel_bore, _pin_bore)
    return (clevis_pin_bore,)


@app.cell
def _(BOLT_HOLE_RADIUS, GLAND_BOLT_HOLES, clevis_pin_bore):
    # ---- feature: gland-bolt-holes (subtract) ----
    _body = clevis_pin_bore
    for _hole_id, _y, _z in GLAND_BOLT_HOLES:
        _hole = scad.make_cylinder_rsolid(
            radius=BOLT_HOLE_RADIUS,
            height=16.0,
            bottom_face_center=(48.0, _y, _z),
            axis=(1.0, 0.0, 0.0),
            tag_prefix=f"hydraulic.sleeve.gland.bolt.{_hole_id}",
            result_tag=f"tool.hydraulic.sleeve.gland.bolt.{_hole_id}",
            start_face_tag=f"sleeve.gland.bolt.{_hole_id}.face.rear",
            end_face_tag=f"sleeve.gland.bolt.{_hole_id}.face.front",
            side_face_tag=f"sleeve.gland.bolt.{_hole_id}.face.wall",
        )
        _body = scad.cut_rsolid(_body, _hole)
    gland_bolt_holes = _body
    return (gland_bolt_holes,)


@app.cell
def _(gland_bolt_holes):
    _body = scad.apply_tag(shape=gland_bolt_holes, tag="part.hydraulic.sleeve.finished")
    _steel = scad.make_material_rmaterial(
        material_id="black_oxide_steel",
        name="Black oxide steel",
        density=7.85e-6,
        density_unit="kg/mm^3",
        color=(0.10, 0.11, 0.12),
    )
    # The slide axis sits on the gland's mount face and points +X, out of
    # the sleeve along the stroke.
    _mount_face = ql.faces().where(ql.tag("sleeve.gland.face.mount")).exactly(1).resolve(_body)[0]
    _part = scad.make_part_rpart(
        part_id="outer_sleeve", body=_body, name="Outer sleeve with clevis and gland"
    )
    _part = scad.assign_material_rpart(part=_part, material=_steel)
    outer_sleeve = scad.add_connector_rpart(
        part=_part,
        connector=scad.make_face_connector_rconnector(connector_id="slide_axis", face=_mount_face),
    )
    return (outer_sleeve,)


if __name__ == "__main__":
    app.run()

# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "piston_rod"
# ///
"""Piston rod of the hydraulic cylinder: piston, chrome rod and eye end.

X is the stroke axis, the eye end is at +X. Every face carries a ``rod.``
tag. The piston's rear face holds the ``slide_axis`` connector, flipped to
point +X like the sleeve's.
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
    ROD_RADIUS = 6.5
    EYE_PIN_RADIUS = 5.5
    return EYE_PIN_RADIUS, ROD_RADIUS


@app.cell
def _():
    # ---- feature: piston (build) ----
    # Two lands around a seal groove.
    _lands_and_groove = [
        scad.make_cylinder_rsolid(
            radius=_radius,
            height=_height,
            bottom_face_center=(_x, 0.0, 0.0),
            axis=(1.0, 0.0, 0.0),
            tag_prefix=f"hydraulic.rod.piston.{_name}",
            result_tag=f"part.hydraulic.rod.piston.{_name}",
            start_face_tag=f"rod.piston.{_name}.face.rear",
            end_face_tag=f"rod.piston.{_name}.face.front",
            side_face_tag=f"rod.piston.{_name}.face.outer",
        )
        for _name, _radius, _height, _x in (
            ("land.left", 10.0, 3.2, -6.0),
            ("groove", 9.0, 6.0, -3.0),
            ("land.right", 10.0, 3.2, 2.6),
        )
    ]
    piston = scad.union_rsolid(*_lands_and_groove, glue=False)
    return (piston,)


@app.cell
def _(ROD_RADIUS, piston):
    # ---- feature: chrome-rod (add) ----
    _rod = scad.make_cylinder_rsolid(
        radius=ROD_RADIUS,
        height=132.0,
        bottom_face_center=(3.0, 0.0, 0.0),
        axis=(1.0, 0.0, 0.0),
        tag_prefix="hydraulic.rod.shaft",
        result_tag="part.hydraulic.rod.shaft",
        start_face_tag="rod.shaft.face.piston",
        end_face_tag="rod.shaft.face.eye",
        side_face_tag="rod.shaft.face.outer",
    )
    chrome_rod = scad.union_rsolid(piston, _rod, glue=False)
    return (chrome_rod,)


@app.cell
def _(chrome_rod):
    # ---- feature: rod-eye (add) ----
    _eye = scad.make_cylinder_rsolid(
        radius=13.0,
        height=9.0,
        bottom_face_center=(143.0, -4.5, 0.0),
        axis=(0.0, 1.0, 0.0),
        tag_prefix="hydraulic.rod.eye",
        result_tag="part.hydraulic.rod.eye",
        start_face_tag="rod.eye.face.ymin",
        end_face_tag="rod.eye.face.ymax",
        side_face_tag="rod.eye.face.outer",
    )
    _neck = named_box(
        width=20.0,
        height=8.0,
        depth=13.0,
        bottom_face_center=(130.0, 0.0, -6.5),
        bottom_face_tag="rod.eye.neck.face.bottom",
        top_face_tag="rod.eye.neck.face.top",
        side_faces_tag="rod.eye.neck.face.side",
        tag_prefix="hydraulic.rod.eye.neck",
        result_tag="part.hydraulic.rod.eye.neck",
    )
    rod_eye = scad.union_rsolid(chrome_rod, _eye, _neck, glue=False)
    return (rod_eye,)


@app.cell
def _(EYE_PIN_RADIUS, rod_eye):
    # ---- feature: eye-pin-bore (subtract) ----
    _pin_bore = scad.make_cylinder_rsolid(
        radius=EYE_PIN_RADIUS,
        height=13.0,
        bottom_face_center=(143.0, -6.5, 0.0),
        axis=(0.0, 1.0, 0.0),
        tag_prefix="hydraulic.rod.eye.pin.bore",
        result_tag="tool.hydraulic.rod.eye.pin_bore",
        start_face_tag="rod.eye.pin.face.ymin",
        end_face_tag="rod.eye.pin.face.ymax",
        side_face_tag="rod.eye.pin.face.wall",
    )
    eye_pin_bore = scad.cut_rsolid(rod_eye, _pin_bore)
    return (eye_pin_bore,)


@app.cell
def _(eye_pin_bore):
    _body = scad.apply_tag(shape=eye_pin_bore, tag="part.hydraulic.rod.finished")
    _steel = scad.make_material_rmaterial(
        material_id="chrome_plated_steel",
        name="Chrome plated steel",
        density=7.85e-6,
        density_unit="kg/mm^3",
        color=(0.78, 0.80, 0.82),
    )
    # The piston's rear face points -X; flip its connector so it points +X
    # like the sleeve's and the prismatic mate slides the rod along +X.
    _rear_face = (
        ql.faces().where(ql.tag("rod.piston.land.left.face.rear")).exactly(1).resolve(_body)[0]
    )
    _part = scad.make_part_rpart(
        part_id="piston_rod", body=_body, name="Inner piston rod with eye end"
    )
    _part = scad.assign_material_rpart(part=_part, material=_steel)
    piston_rod = scad.add_connector_rpart(
        part=_part,
        connector=scad.make_face_connector_rconnector(
            connector_id="slide_axis", face=_rear_face, flip=_rear_face.get_normal_at().x < 0
        ),
    )
    return (piston_rod,)


if __name__ == "__main__":
    app.run()

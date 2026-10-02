# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "caplcd_enclosure_7ep"
# revision = "1.0.0"
# ///
"""Screw-mounted rear enclosure tray for the 7EP-CAPLCD display module.

Module constraints (measured from examples/out/invtest/7EP-CAPLCD-3D-Drawing.stp,
module datum: origin at screen center, +X right, +Y top, +Z front):
  - Module envelope          X [-52.1, 52.1]  Y [-85.09, 85.09]  Z [-10.03, 4.6]
  - Touch glass top          Z = 4.6 (full footprint)
  - LCD cell (7INCH-070II)   X [-49.88, 49.88]  Y [-83.54, 78.06]
  - PCB (HL2412 outline)     99.5 x 161, top Z = -2.12
  - Frame bottom face        Z = -2.4 (support datum)
  - Audio jack (SJ2-35894D)  mouth (X -33.3, Y 79.9, Z -6.2), faces +Y (top edge)
  - USB-C x2 (mouths +Y)     (-20.8, 49.5) and (-6.8, 49.5), mouth plane Y=53.4
  - 47151-0001 (right-angle  socket cavity at the +Y end (X 8.8..14.6,
    10-pin, mouth +Y)         Y 51.4..54.0, Z -5.3..-4.5), exits toward the
                             top edge; through-hole tails at Z -10.03
  - 3-pin PH2.0 connector    (-41.7, 24.2), RIGHT-ANGLE: socket faces -X,
                             plug/wires exit through the LEFT wall
  - 4-pin 1.25 x2 (exit -Z)  (-43.2, 57.3) and (-43.2, -41.0), to Z -8.51
  - Tact button (6x6x7)      (33.85, 71.76), plunger to Z -8.7
  - Speakers (SPK-2030x4)    20 x 55 at X [28.25, 48.25], Y [8.3, 63.3] and
                             Y [-68.7, -13.7], cones face -Z (grilles in rear)
  - 4 corner M2.5 standoffs  (+-45.75, +-73.75), Z -7.7..-2.2

Enclosure scheme (this notebook models the tray):
  - Back tray: base panel Z -13.0..-10.5, walls to the glass plane, outer
    X +-56.0, Y +-89.2 (2.5 wall). Screwed to the module's 8 threaded M2.5
    standoffs (SMTSO-M2_5-4ET have an internal bore) with countersunk M2.5
    screws, so the tray is fixed directly to the back of the display. Rear
    panel openings for connectors, button, speaker grilles; recessed
    interface bay on the top edge so the jack, USB-C and 47151 mouths sit at
    the bay/channel floors and plugs go straight in; open bay on the left
    wall for the 3-pin.
  - Upper cover (not modeled): bezel with LCD window (98.5 x 160, R5), skirt
    wraps the tray rim; 6 M2 countersunk side screws.
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql

    # Module datums: measured from the display's STEP model, not design choices.
    GLASS_Z = 4.6  # touch glass top
    PANEL_INNER_Z = -10.5  # tray panel inner face
    PANEL_OUTER_Z = -13.0
    STANDOFF_FOOT_Z = -7.7  # the module's M2.5 standoffs hang to here
    # The 8 threaded standoffs: 4 corners + 4 inner.
    STANDOFFS = tuple(
        [(sx * 45.75, sy * 73.75) for sx in (-1, 1) for sy in (-1, 1)]
        + [(sx * 18.0, y) for sx in (-1, 1) for y in (36.26, -21.74)]
    )


@app.function
def box(width, height, depth, bottom_face_center) -> scad.Solid:
    return scad.make_box_rsolid(
        width=width, height=height, depth=depth, bottom_face_center=bottom_face_center)


@app.function
def cyl(radius, height, bottom_face_center) -> scad.Solid:
    return scad.make_cylinder_rsolid(
        radius=radius, height=height, bottom_face_center=bottom_face_center)


@app.cell
def _():
    # ---- params ----
    TRAY_X = 56.0  # outer half-width
    TRAY_Y = 89.2  # outer half-height
    WALL_T = 2.5
    return TRAY_X, TRAY_Y, WALL_T


@app.cell
def _(TRAY_X, TRAY_Y, WALL_T):
    # ---- feature: tray-shell (build) ----
    # Base panel + walls up to Z 4.4, just under the glass top (4.6): the
    # module frame is the finished front face, the walls are a guard rim.
    _wall_h = 4.4 - PANEL_INNER_Z
    _walls = [box(WALL_T, 2 * TRAY_Y, _wall_h, (sx * (TRAY_X - WALL_T / 2), 0, PANEL_INNER_Z))
              for sx in (-1, 1)]
    _walls += [box(2 * TRAY_X, WALL_T, _wall_h, (0, sy * (TRAY_Y - WALL_T / 2), PANEL_INNER_Z))
               for sy in (-1, 1)]
    tray_shell = scad.union_rsolid(
        [box(2 * TRAY_X, 2 * TRAY_Y, PANEL_INNER_Z - PANEL_OUTER_Z, (0, 0, PANEL_OUTER_Z))]
        + _walls)
    return (tray_shell,)


@app.cell
def _(tray_shell):
    # ---- feature: standoff-pads (add) ----
    # Pads under the module's 8 standoff feet. The frame bottom (Z -2.4) is
    # not loadable: the PCB (Z -3.7..-2.12, 99.5 x 161) hangs below it over
    # nearly the full footprint. The standoffs are the module's own feet.
    _pad_h = STANDOFF_FOOT_Z - PANEL_INNER_Z
    standoff_pads = scad.union_rsolid(
        [tray_shell] + [cyl(2.75, _pad_h, (x, y, PANEL_INNER_Z)) for x, y in STANDOFFS])
    return (standoff_pads,)


@app.cell
def _(standoff_pads):
    # ---- feature: centering-ribs (add) ----
    # Two bands on the inner wall faces: Z -2.9..0.6 and the frame band 0.8..4.3.
    _ribs = []
    for _z0, _z1 in ((-2.9, 0.6), (0.8, 4.3)):
        _ribs += [box(1.0, 10.0, _z1 - _z0, (sx * 53.0, ry, _z0))
                  for ry in (-55, -20, 20, 55) for sx in (-1, 1)]
        _ribs += [box(10.0, 1.0, _z1 - _z0, (rx, sy * 86.2, _z0))
                  for rx in (-50, -20, 20, 50) for sy in (-1, 1)]
    centering_ribs = scad.union_rsolid([standoff_pads] + _ribs)
    return (centering_ribs,)


@app.cell
def _(centering_ribs):
    # ---- feature: connector-bay (add) ----
    # The plan outline steps INWARD on the connector side: the wall in
    # X -38.6..+24.2 is recessed from Y 89.2 to Y 82.7 (lower band
    # Z -10.5..-2.5), following the PCB's own top-edge notch. The jack mouth
    # (79.9) sits 0.3 mm behind the recessed wall's inner face; USB-C / 47151
    # mouths (53.4 / 54.0) are reached below the PCB. Raised shelves align
    # the plug axes with the mouths.
    connector_bay = scad.union_rsolid([
        centering_ribs,
        box(62.8, 2.5, 8.0, (-7.2, 81.45, -10.5)),   # recessed wall Y 80.2..82.7
        box(32.3, 28.6, 2.2, (-12.15, 65.9, -10.5)),  # USB shelf X -28.3..4.0
        box(20.2, 26.2, 2.2, (14.1, 67.1, -10.5)),    # 47151 shelf X 4.0..24.2
    ])
    return (connector_bay,)


@app.cell
def _(TRAY_X, TRAY_Y, WALL_T, connector_bay):
    # ---- feature: connector-openings (subtract) ----
    # Remove the original wall's lower band behind the recess, open the plug
    # holes through the recessed wall, and open the left wall at the 3-pin
    # socket band (Y 18.76..29.56): the socket faces -X.
    connector_openings = scad.cut_rsolid(connector_bay, [
        box(62.8, 3.5, 8.0, (-7.2, TRAY_Y - WALL_T / 2, -10.5)),  # void Y 86.2..89.7
        box(9.2, 3.1, 5.0, (-33.3, 81.45, -8.4)),   # jack mouth
        box(10.0, 3.1, 5.0, (-20.8, 81.45, -7.8)),  # USB-C 1
        box(10.0, 3.1, 5.0, (-6.8, 81.45, -7.8)),   # USB-C 2
        box(10.0, 3.1, 2.2, (12.5, 81.45, -6.0)),   # 47151
        box(3.0, 10.8, 6.4, (-(TRAY_X - WALL_T / 2), 24.16, -10.3)),  # 3-pin bay
    ])
    return (connector_openings,)


@app.cell
def _(connector_openings):
    # ---- feature: mount-holes (subtract) ----
    # M2.5 clearance through pad + base, with a countersink from the rear.
    _holes = [cyl(1.4, 6.0, (x, y, -13.5)) for x, y in STANDOFFS]
    _sinks = [cyl(2.6, 1.5, (x, y, -13.2)) for x, y in STANDOFFS]
    mount_holes = scad.cut_rsolid(connector_openings, _holes + _sinks)
    return (mount_holes,)


@app.cell
def _(mount_holes):
    # ---- feature: rear-openings (subtract) ----
    # Through the base panel: 4-pin 1.25 x2 (wires exit -Z), tact button,
    # speaker grilles (2 zones x 12 slots, 18 x 1.6 at pitch 4.4), MCU vents.
    _cut = 4.0
    _tools = [
        box(5.8, 11.4, _cut, (-43.16, 57.26, PANEL_OUTER_Z)),
        box(5.8, 11.4, _cut, (-43.16, -40.98, PANEL_OUTER_Z)),
        box(6.0, 6.0, _cut, (33.85, 71.76, PANEL_OUTER_Z)),
    ]
    _tools += [box(18.0, 1.6, _cut, (37.7, zone_y + 4.4 * (k - 0.5), PANEL_OUTER_Z))
               for zone_y in (35.75, -41.24) for k in range(-5, 7)]
    _tools += [cyl(1.25, _cut, (vx, vy, PANEL_OUTER_Z))
               for vx, vy in ((-14.0, 6.5), (-9.5, 6.5), (-14.0, 10.5), (-9.5, 10.5))]
    rear_openings = scad.cut_rsolid(mount_holes, _tools)
    return (rear_openings,)


@app.cell
def _(TRAY_X, TRAY_Y, rear_openings):
    # ---- feature: corner-rounds (subtract) ----
    # R6 plan corners, cut with cylinders centred on the outer corners.
    corner_rounds = scad.cut_rsolid(rear_openings, [
        cyl(6.0, 30.0, (sx * TRAY_X, sy * TRAY_Y, -15.0)) for sx in (-1, 1) for sy in (-1, 1)])
    print("tray volume", round(corner_rounds.get_volume(), 1))
    print("tray faces", len(ql.faces().resolve(corner_rounds)))
    return (corner_rounds,)


@app.cell
def _(corner_rounds):
    _tray = scad.apply_tag(shape=corner_rounds, tag="role.enclosure.tray")
    _part = scad.make_part_rpart(
        part_id="caplcd_enclosure_7ep", body=_tray, name="7EP-CAPLCD rear enclosure tray")
    _part = scad.assign_material_rpart(part=_part, material=scad.make_material_rmaterial(
        material_id="abs_black", name="Black ABS",
        density=1.04e-6, density_unit="kg/mm^3", color=(0.06, 0.06, 0.06)))
    for _connector_id, _origin, _x_axis, _y_axis in (
        ("screen_center", (0.0, 0.0, GLASS_Z), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ("connector_access", (0.0, 81.45, -6.2), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ("rear_mount", (0.0, 0.0, PANEL_OUTER_Z), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    ):
        _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(
            connector_id=_connector_id,
            placement=scad.make_placement_rplacement(origin=_origin, x_axis=_x_axis, y_axis=_y_axis)))
    caplcd_enclosure = _part
    return (caplcd_enclosure,)


if __name__ == "__main__":
    app.run()

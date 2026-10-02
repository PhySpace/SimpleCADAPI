# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "ap242_gmsh_bracket"
# revision = "2.1.0"
# ///
"""Single-solid ribbed L-bracket for the STEP -> Gmsh -> CalculiX chain.

Coordinate convention (BUILD_PLAN.md):
  origin = centre of the wall's bottom face; +X through the wall thickness
  (fixed support at x = -2), +Y across the width (symmetric about y = 0),
  +Z up the wall.

Wall and shelf are boxes, the gusset ribs are transcribed closed profiles,
the hole tools are cylinders (FTC geometry tier). The last two blocks name
the faces the FEM chain selects by tag: ``interface.fixed_support``,
``interface.load_surface``, ``interface.mount_hole_1/2`` and
``interface.load_hole``. ``export_fem_mesh.py`` maps them onto Gmsh
physical groups, so renaming one breaks the mesh mapping.
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql

    # Face-matcher guard: a tagged face must lie within this distance (mm)
    # of its target centre.
    TAG_MATCH_MAX_DISTANCE = 10.0


@app.function
def tag_interface_face(
    body: scad.Solid,
    *,
    center: tuple[float, float, float],
    normal: tuple[float, float, float] | None,
    tag: str,
) -> scad.Solid:
    """Tag the face of *body* nearest *center*, optionally facing *normal*.

    A candidate must face within ~37 deg of *normal* and lie within
    TAG_MATCH_MAX_DISTANCE of *center*; otherwise the parameters no longer
    describe this body and the cell fails instead of tagging a wrong face.
    """
    candidates: list[tuple[float, scad.Face]] = []
    for face in ql.faces().resolve(body):
        actual_center = face.get_center()
        if normal is not None:
            actual_normal = face.get_normal_at()
            alignment = (
                actual_normal.x * normal[0]
                + actual_normal.y * normal[1]
                + actual_normal.z * normal[2]
            )
            if alignment < 0.8:
                continue
        distance_sq = (
            (actual_center.x - center[0]) ** 2
            + (actual_center.y - center[1]) ** 2
            + (actual_center.z - center[2]) ** 2
        )
        candidates.append((distance_sq, face))
    if not candidates:
        raise ValueError(f"no final face matches {tag}")
    distance_sq, selected = min(candidates, key=lambda item: item[0])
    if distance_sq > TAG_MATCH_MAX_DISTANCE**2:
        raise ValueError(f"final face match for {tag} is too distant: distance^2={distance_sq}")
    return scad.apply_tag_rselection(scope=body, targets=[selected], tag=tag)


@app.cell
def _():
    # ---- params: envelope ----
    BRACKET_WIDTH = scad.var("bracket_width", 40.0, unit="mm")
    BRACKET_HEIGHT = scad.var("bracket_height", 36.0, unit="mm")
    BRACKET_DEPTH = scad.var("bracket_depth", 28.0, unit="mm")
    PLATE_THICKNESS = scad.var("plate_thickness", 4.0, unit="mm")
    return BRACKET_DEPTH, BRACKET_HEIGHT, BRACKET_WIDTH, PLATE_THICKNESS


@app.cell
def _():
    # ---- params: holes ----
    # The height ratio is unitless, and a unitless var cannot mix with a
    # unit-declared one in a var expression, so derived coordinates are
    # computed from float(...) values.
    MOUNT_HOLE_RADIUS = scad.var("mount_hole_radius", 2.5, unit="mm", tolerance=0.1)
    MOUNT_HOLE_SPACING = scad.var("mount_hole_spacing", 22.0, unit="mm")
    MOUNT_HOLE_HEIGHT_RATIO = scad.var("mount_hole_height_ratio", 0.62)
    LOAD_HOLE_RADIUS = scad.var("load_hole_radius", 3.0, unit="mm", tolerance=0.1)
    LOAD_HOLE_X = scad.var("load_hole_x", 12.0, unit="mm")
    CUT_OVERSHOOT = scad.var("cut_overshoot", 1.0, unit="mm")
    return (
        CUT_OVERSHOOT,
        LOAD_HOLE_RADIUS,
        LOAD_HOLE_X,
        MOUNT_HOLE_HEIGHT_RATIO,
        MOUNT_HOLE_RADIUS,
        MOUNT_HOLE_SPACING,
    )


@app.cell
def _():
    # ---- params: gusset ribs ----
    RIB_THICKNESS = scad.var("rib_thickness", 3.0, unit="mm")
    RIB_HEIGHT = scad.var("rib_height", 18.0, unit="mm")
    RIB_DEPTH = scad.var("rib_depth", 18.0, unit="mm")
    RIB_OFFSET_Y = scad.var("rib_offset_y", 11.0, unit="mm")
    return RIB_DEPTH, RIB_HEIGHT, RIB_OFFSET_Y, RIB_THICKNESS


@app.cell
def _(
    BRACKET_DEPTH,
    BRACKET_HEIGHT,
    BRACKET_WIDTH,
    CUT_OVERSHOOT,
    LOAD_HOLE_RADIUS,
    LOAD_HOLE_X,
    MOUNT_HOLE_HEIGHT_RATIO,
    MOUNT_HOLE_RADIUS,
    MOUNT_HOLE_SPACING,
    PLATE_THICKNESS,
    RIB_DEPTH,
    RIB_HEIGHT,
    RIB_OFFSET_Y,
    RIB_THICKNESS,
):
    # ---- guard: parameter feasibility ----
    # Infeasible parameters fail here instead of producing a wrong body.
    _t = float(PLATE_THICKNESS)
    _width, _height, _depth = float(BRACKET_WIDTH), float(BRACKET_HEIGHT), float(BRACKET_DEPTH)
    _spacing, _mount_r = float(MOUNT_HOLE_SPACING), float(MOUNT_HOLE_RADIUS)
    _ratio = float(MOUNT_HOLE_HEIGHT_RATIO)
    _load_r, _load_x = float(LOAD_HOLE_RADIUS), float(LOAD_HOLE_X)
    _rib_t, _rib_h = float(RIB_THICKNESS), float(RIB_HEIGHT)
    _rib_d, _rib_y = float(RIB_DEPTH), float(RIB_OFFSET_Y)

    assert 0.0 < 2.0 * _t < min(_width, _height, _depth), "plate thickness must fit all spans"
    assert 2.0 * _mount_r < _spacing, "mount holes would merge"
    assert _spacing / 2.0 + _mount_r < _width / 2.0, "mount holes outside wall width"
    assert 0.0 < _ratio < 1.0, "mount hole height ratio must be in (0, 1)"
    _hole_z = _ratio * _height
    assert _mount_r < _hole_z < _height - _mount_r, "mount hole outside wall height"
    assert -_t / 2.0 + _load_r < _load_x < _depth - _t / 2.0 - _load_r, \
        "load hole outside shelf footprint"
    assert _load_r < _t / 2.0 + _rib_y - _rib_t / 2.0, "load hole would reach rib band"
    assert 2.0 * _rib_y - _rib_t > 0.0, "ribs would overlap at the symmetry plane"
    assert _rib_y - _rib_t / 2.0 > _load_r, "ribs would collide with the load hole"
    assert _rib_h + _t <= _height, "rib would overtop the wall"
    assert _rib_d <= _depth - _t, "rib would overrun the shelf depth"
    assert float(CUT_OVERSHOOT) > 0.0, "cut overshoot must be positive"
    return


@app.cell
def _(BRACKET_HEIGHT, BRACKET_WIDTH, PLATE_THICKNESS):
    # ---- feature: wall (build) ----
    wall = scad.make_box_rsolid(
        width=PLATE_THICKNESS,
        height=BRACKET_WIDTH,
        depth=BRACKET_HEIGHT,
        bottom_face_center=(0.0, 0.0, 0.0),
        tag_prefix="bracket.wall",
    )
    return (wall,)


@app.cell
def _(BRACKET_DEPTH, BRACKET_WIDTH, PLATE_THICKNESS, wall):
    # ---- feature: shelf (add) ----
    _shelf = scad.make_box_rsolid(
        width=BRACKET_DEPTH,
        height=BRACKET_WIDTH,
        depth=PLATE_THICKNESS,
        bottom_face_center=((float(BRACKET_DEPTH) - float(PLATE_THICKNESS)) / 2.0, 0.0, 0.0),
        tag_prefix="bracket.shelf",
    )
    shelf = scad.union_rsolid(wall, _shelf)
    return (shelf,)


@app.cell
def _(PLATE_THICKNESS, RIB_DEPTH, RIB_HEIGHT, RIB_OFFSET_Y, RIB_THICKNESS, shelf):
    # ---- feature: gusset-ribs (add, profile=geometry) ----
    # One triangle per rib in the wall/shelf corner, transcribed from the
    # legacy coordinates and extruded +Y by the rib thickness.
    _t, _rib_t = float(PLATE_THICKNESS), float(RIB_THICKNESS)
    _ribs = []
    for _y_center in (-float(RIB_OFFSET_Y), float(RIB_OFFSET_Y)):
        _y0 = _y_center - _rib_t / 2.0
        _profile = scad.make_polyline_rwire(
            [
                (0.0, _y0, _t),
                (0.0, _y0, _t + float(RIB_HEIGHT)),
                (float(RIB_DEPTH), _y0, _t),
            ],
            closed=True,
        )
        _face = scad.make_face_from_wire_rface(_profile, normal=(0.0, 1.0, 0.0))
        _ribs.append(scad.extrude_rsolid(
            profile=_face,
            direction=(0.0, 1.0, 0.0),
            distance=RIB_THICKNESS,
            tag_prefix="bracket.rib",
        ))
    gusset_ribs = scad.union_rsolid(shelf, *_ribs)
    return (gusset_ribs,)


@app.cell
def _(
    BRACKET_HEIGHT,
    CUT_OVERSHOOT,
    MOUNT_HOLE_HEIGHT_RATIO,
    MOUNT_HOLE_RADIUS,
    MOUNT_HOLE_SPACING,
    PLATE_THICKNESS,
    gusset_ribs,
):
    # ---- feature: mount-holes (subtract, profile=geometry) ----
    _t, _over = float(PLATE_THICKNESS), float(CUT_OVERSHOOT)
    _hole_z = float(MOUNT_HOLE_HEIGHT_RATIO) * float(BRACKET_HEIGHT)
    _half = float(MOUNT_HOLE_SPACING) / 2.0
    _tools = [
        scad.make_cylinder_rsolid(
            radius=MOUNT_HOLE_RADIUS,
            height=_t + 2.0 * _over,
            bottom_face_center=(-_t / 2.0 - _over, _y, _hole_z),
            axis=(1.0, 0.0, 0.0),
            tag_prefix=f"bracket.mount_hole_{_index}",
        )
        for _index, _y in enumerate((-_half, _half), start=1)
    ]
    mount_holes = scad.cut_rsolid(gusset_ribs, _tools, skip_non_intersecting=False)
    return (mount_holes,)


@app.cell
def _(CUT_OVERSHOOT, LOAD_HOLE_RADIUS, LOAD_HOLE_X, PLATE_THICKNESS, mount_holes):
    # ---- feature: load-hole (subtract, profile=geometry) ----
    _t, _over = float(PLATE_THICKNESS), float(CUT_OVERSHOOT)
    _tool = scad.make_cylinder_rsolid(
        radius=LOAD_HOLE_RADIUS,
        height=_t + 2.0 * _over,
        bottom_face_center=(float(LOAD_HOLE_X), 0.0, -_over),
        axis=(0.0, 0.0, 1.0),
        tag_prefix="bracket.load_hole",
    )
    load_hole = scad.cut_rsolid(mount_holes, _tool, skip_non_intersecting=False)
    return (load_hole,)


@app.cell
def _(
    BRACKET_DEPTH,
    BRACKET_HEIGHT,
    LOAD_HOLE_X,
    MOUNT_HOLE_HEIGHT_RATIO,
    MOUNT_HOLE_SPACING,
    PLATE_THICKNESS,
    RIB_DEPTH,
    load_hole,
):
    # ---- feature: role-name (annotate) ----
    # ---- feature: interface-names (annotate) ----
    # Two annotate blocks share a cell: they only add tags and always change
    # together. Each target is the centre of the face the FEM chain needs.
    _t = float(PLATE_THICKNESS)
    _hole_z = float(MOUNT_HOLE_HEIGHT_RATIO) * float(BRACKET_HEIGHT)
    _half = float(MOUNT_HOLE_SPACING) / 2.0
    _body = scad.apply_tag(load_hole, "role.structural_l_bracket")
    _body = tag_interface_face(
        _body,
        center=(0.0, 0.0, float(BRACKET_HEIGHT) / 2.0),
        normal=(-1.0, 0.0, 0.0),
        tag="interface.fixed_support",
    )
    _body = tag_interface_face(
        _body,
        center=((float(BRACKET_DEPTH) + float(RIB_DEPTH) - _t) / 2.0, 0.0, _t),
        normal=(0.0, 0.0, 1.0),
        tag="interface.load_surface",
    )
    for _index, _y in enumerate((-_half, _half), start=1):
        _body = tag_interface_face(
            _body,
            center=(_t / 2.0, _y, _hole_z),
            normal=None,
            tag=f"interface.mount_hole_{_index}",
        )
    interface_names = tag_interface_face(
        _body,
        center=(float(LOAD_HOLE_X), 0.0, _t / 2.0),
        normal=None,
        tag="interface.load_hole",
    )
    return (interface_names,)


@app.cell
def _(interface_names):
    # ---- product: part + material ----
    _part = scad.make_part_rpart(
        part_id="ap242_gmsh_bracket",
        body=interface_names,
        name="Named ribbed L-bracket",
    )
    _material = scad.make_material_rmaterial(
        material_id="aluminum_6061_t6",
        name="Aluminum 6061-T6",
        density=2.70e-6,
        density_unit="kg/mm^3",
        color=(0.72, 0.74, 0.78),
    )
    bracket = scad.assign_material_rpart(_part, _material)
    return (bracket,)


if __name__ == "__main__":
    app.run()

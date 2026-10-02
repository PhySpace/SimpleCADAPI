# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "u-link-motor-mount"
# revision = "1.0.0"
# ///
"""u_link: 参数化 U 形电机连杆上件（机械臂 link，通用电机安装）。

U 形圆杆在背切平面 back_y（底管 75% 高度）剖分；上件带两个电机安装槽
（命名安装面）、剖分面下悬的 boss 柱 + 三角筋（给 shell 打螺丝）、全局
倒角和槽壁走线窗。尺寸与守卫链在 ``dimensions.py``（与 ``shell.py`` 共用），
坐标约定见那里。

    sca run examples/u_link_motor_mount/u_link.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql

    from common import big_box, rounded_rect_prism, sweep_u_rod
    from dimensions import DIMS, TAG_BACK, TAG_MOUNT_LEFT, TAG_MOUNT_RIGHT


@app.function
def mount_floor(x_center: float) -> ql.ShapeSelector:
    """安装面(槽底)几何谓词：平面 +Y @ y=d_motor/2, x=x_center。"""
    y = DIMS.floor_y
    return ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop("geom.normal.y", ">=", 0.999),
        ql.prop("geom.center.y", ">=", y - 0.1),
        ql.prop("geom.center.y", "<=", y + 0.1),
        ql.prop("geom.center.x", ">=", x_center - 0.1),
        ql.prop("geom.center.x", "<=", x_center + 0.1),
    )).exactly(1)


@app.cell
def _():
    # ---- guard: parameter feasibility (REQUIREMENTS.md) ----
    DIMS.check()
    return


@app.cell
def _():
    # ---- feature: u-rod (build) ----
    u_rod = sweep_u_rod(DIMS)
    return (u_rod,)


@app.cell
def _(u_rod):
    # ---- feature: split-plane (subtract) ----
    # 剖分上件 @ back_y（75%），去下半；7.5 以下只剩后面加的 boss+筋，壁让位给 shell
    split_plane = scad.cut_rsolid(u_rod, big_box(DIMS, DIMS.back_y, DIMS.back_y - 60.0))
    return (split_plane,)


@app.cell
def _(split_plane):
    # ---- feature: motor-pockets (subtract) ----
    _depth = DIMS.D - DIMS.floor_y
    _pockets = [
        scad.make_cylinder_rsolid(
            radius=DIMS.pocket_r, height=_depth + 5.0,
            bottom_face_center=(_x, DIMS.floor_y, 0.0), axis=(0.0, 1.0, 0.0))
        for _x in (-DIMS.L / 2.0, DIMS.L / 2.0)
    ]
    motor_pockets = scad.cut_rsolid(split_plane, _pockets)
    return (motor_pockets,)


@app.cell
def _(motor_pockets):
    # ---- feature: boss-columns (add) ----
    # 底=boss 尖端平面精确，顶越界 2 入实体保熔合
    _columns = [
        scad.make_cylinder_rsolid(
            radius=DIMS.boss_d / 2.0, height=DIMS.boss_h + 2.0,
            bottom_face_center=(_sx * DIMS.boss_x, DIMS.boss_tip_y, 0.0),
            axis=(0.0, 1.0, 0.0))
        for _sx in (-1, 1)
    ]
    boss_columns = scad.union_rsolid(motor_pockets, *_columns)
    return (boss_columns,)


@app.cell
def _(boss_columns):
    # ---- feature: boss-holes (subtract) ----
    # 中心自攻盲孔，自柱底向上
    _holes = [
        scad.make_cylinder_rsolid(
            radius=DIMS.boss_hole_d / 2.0, height=DIMS.boss_hole_depth,
            bottom_face_center=(_sx * DIMS.boss_x, DIMS.boss_tip_y, 0.0),
            axis=(0.0, 1.0, 0.0))
        for _sx in (-1, 1)
    ]
    boss_holes = scad.cut_rsolid(boss_columns, _holes)
    return (boss_holes,)


@app.cell
def _(boss_holes):
    # ---- feature: gussets (add) ----
    # 每柱 4 方向三角筋：垂直边贴柱（全高 boss_h），水平边沿剖分面 rib_len
    _by, _bh = DIMS.back_y, DIMS.boss_h
    _br, _rt, _rl = DIMS.boss_d / 2.0, DIMS.rib_t, DIMS.rib_len

    def _triangle(a, b, c):
        return scad.make_face_from_wire_rface(scad.make_wire_from_edges_rwire(edges=[
            scad.make_segment_redge(start=a, end=b),
            scad.make_segment_redge(start=b, end=c),
            scad.make_segment_redge(start=c, end=a),
        ]))

    _ribs = []
    for _sx in (-1, 1):
        _bx = _sx * DIMS.boss_x
        for _dx in (-1, 1):  # ±x：三角形在 (x,y) 面，沿 +z 拉伸
            _z = -_rt / 2
            _tri = _triangle((_bx + _dx * _br, _by, _z), (_bx + _dx * (_br + _rl), _by, _z),
                             (_bx + _dx * _br, _by - _bh, _z))
            _ribs.append(scad.extrude_rsolid(profile=_tri, direction=(0.0, 0.0, 1.0), distance=_rt))
        for _dz in (-1, 1):  # ±z：三角形在 (z,y) 面，沿 +x 拉伸
            _x = _bx - _rt / 2
            _tri = _triangle((_x, _by, _dz * _br), (_x, _by, _dz * (_br + _rl)),
                             (_x, _by - _bh, _dz * _br))
            _ribs.append(scad.extrude_rsolid(profile=_tri, direction=(1.0, 0.0, 0.0), distance=_rt))
    gussets = scad.union_rsolid(boss_holes, *_ribs)
    return (gussets,)


@app.cell
def _(gussets):
    # ---- feature: gusset-chamfer (modify) ----
    # 筋斜边（长 sqrt(rib_len²+boss_h²)，每筋两侧共 16 条）。谓词进图可被翻译器
    # 语义重放；Python 侧 get_edges() 过滤只写拓扑引用，跨内核会漂移。
    _hyp = (DIMS.rib_len ** 2 + DIMS.boss_h ** 2) ** 0.5
    _w = DIMS.boss_d / 2.0 + DIMS.rib_len + 0.4
    _bx = DIMS.boss_x
    _hypotenuses = ql.edges().where(ql.and_(
        ql.prop("geom.length", ">=", _hyp - 0.15),
        ql.prop("geom.length", "<=", _hyp + 0.15),
        ql.prop("geom.center.y", ">=", DIMS.boss_tip_y - 0.3),
        ql.prop("geom.center.y", "<=", DIMS.back_y + 0.3),
        ql.or_(
            ql.and_(ql.prop("geom.center.x", ">=", -_bx - _w),
                    ql.prop("geom.center.x", "<=", -_bx + _w)),
            ql.and_(ql.prop("geom.center.x", ">=", _bx - _w),
                    ql.prop("geom.center.x", "<=", _bx + _w)),
        ),
    )).exactly(16)
    gusset_chamfer = scad.chamfer_rsolid(
        solid=gussets, edges=_hypotenuses, distance=DIMS.gusset_chamfer)
    return (gusset_chamfer,)


@app.cell
def _(gusset_chamfer):
    # ---- feature: edge-fillet (modify) ----
    # 只倒 y > (back_y+d_motor/2)/2 的圆边（安装槽 rim/臂顶/拐角圈，恰含安装面
    # rim）。限定 CIRCLE：同窗内的 LINE 全是周期面接缝伪影，位置随内核而变，
    # fillet 贡献为 0。剖分面与 boss 尖端弦边不倒（内核静默负体积）；剖分
    # 接口锐边本就是正确的配合设计。
    _edges = ql.edges().where(ql.and_(
        ql.prop("geom.type", "==", "CIRCLE"),
        ql.prop("geom.center.y", ">", (DIMS.back_y + DIMS.floor_y) / 2.0),
        ql.prop("geom.length", ">=", 2.0 * DIMS.fillet_r + 0.3),
    ))
    edge_fillet = scad.fillet_rsolid(
        solid=gusset_chamfer, edges=_edges, radius=DIMS.fillet_r,
        generated_faces_tag="fillet.global_patch")
    return (edge_fillet,)


@app.cell
def _(edge_fillet):
    # ---- feature: cable-windows (subtract) ----
    # 每槽 4 窗（相位差 90°，对角布置避让内向盲区）：两条过轴圆角矩形棱柱各切
    # 对向 2 窗；窗底边 = 安装面 + cable_w_off。最后切：圆角矩形源型自带角
    # 圆角，成品拓扑上直接切出，无需再倒角。
    _span = DIMS.r + 3.0
    _y0 = DIMS.floor_y + DIMS.cable_w_off
    _hw = DIMS.cable_w_w / 2.0
    _prism = rounded_rect_prism(
        -_span, _span, _y0, _y0 + DIMS.cable_w_h, -_hw, _hw, DIMS.cable_w_rr)
    _windows = []
    for _angle in (DIMS.cable_w_phase, DIMS.cable_w_phase + 90.0):
        _turned = scad.rotate_shape(shape=_prism, axis=(0.0, 1.0, 0.0), angle=_angle)
        for _xc in (-DIMS.L / 2.0, DIMS.L / 2.0):
            _windows.append(scad.translate_shape(shape=_turned, vector=(_xc, 0.0, 0.0)))
    cable_windows = scad.cut_rsolid(edge_fillet, _windows)
    return (cable_windows,)


@app.cell
def _(cable_windows):
    # ---- product: named faces, part, back datum ----
    # 拓扑稳定后统一打确定性命名
    _body = scad.apply_tag_rselection(
        scope=cable_windows, targets=mount_floor(-DIMS.L / 2.0), tag=TAG_MOUNT_LEFT)
    _body = scad.apply_tag_rselection(
        scope=_body, targets=mount_floor(DIMS.L / 2.0), tag=TAG_MOUNT_RIGHT)
    _back = ql.faces().where(ql.and_(  # 大面积区分 boss 顶环小面
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop("geom.normal.y", "<=", -0.999),
        ql.prop("geom.center.y", ">=", DIMS.back_y - 0.1),
        ql.prop("geom.center.y", "<=", DIMS.back_y + 0.1),
        ql.prop("geom.area", ">=", 100.0),
    )).exactly(1)
    _body = scad.apply_tag_rselection(scope=_body, targets=_back, tag=TAG_BACK)
    _part = scad.make_part_rpart(
        part_id="u-link-motor-mount",
        body=_body,
        name="Parametric U link with named motor mount faces",
    )
    u_link = scad.add_connector_rpart(
        part=_part,
        connector=scad.make_placement_connector_rconnector(
            connector_id="back_datum",
            placement=scad.make_placement_rplacement(
                origin=(0.0, DIMS.back_y, 0.0), x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 0.0, 1.0)),
            name="Back face datum (z out -Y)",
        ),
    )
    return (u_link,)


if __name__ == "__main__":
    app.run()

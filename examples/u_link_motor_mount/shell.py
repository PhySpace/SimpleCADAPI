# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "u-link-shell"
# revision = "1.0.0"
# ///
"""u_link shell: 下半件外壳（两刀工艺，平底 @ 第一刀平面）。

用户定序（S11 修正版）：
  第一刀 @ back_y - boss_h - wall_t (=0.5)：切掉下半部 → shell 平底面；
  第二刀 @ back_y (=7.5)：分离壳体与上件。
shell = rod ∩ [0.5, 7.5] − 内偏移扫掠∩[boss_tip(2.5), 7.5]
→ 平底 0.5（整弦截面）+ 实体地板 [0.5, 2.5]（顶面贴 boss 尖端）
+ 轮廓壁 wall_t 的腔体 [2.5, 7.5]（容 boss+线束）。
两端腔高走线口；地板沉头孔（Ø boss_hole_d 通 + 90° 锥口自平底向上）。
建模于安装位；共用尺寸在 ``dimensions.py``。

    sca run examples/u_link_motor_mount/shell.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql

    from common import big_box, rounded_rect_prism, sweep_eroded_rod, sweep_u_rod
    from dimensions import DIMS, TAG_SHELL_FLOOR, TAG_SHELL_RIM


@app.cell
def _():
    # ---- params: cable notches ----
    NOTCH_W = 9.0  # 走线口宽（z 向）；S11 用户定向加大
    NOTCH_SILL = 0.5  # 走线口上下台阶高（离地板顶/rim；口角圆角承载体）
    NOTCH_RR = 1.5  # 走线口角圆角半径（rounded-rect 轮廓，防割手；S12 用户定向）
    return NOTCH_RR, NOTCH_SILL, NOTCH_W


@app.cell
def _():
    # ---- params: countersunk holes ----
    CSINK_D = 5.4  # 沉头孔锥口大端直径（M3 沉头）
    CSINK_DEPTH = 1.35  # 沉头锥深（< wall_t-0.5，90°锥）
    return CSINK_D, CSINK_DEPTH


@app.cell
def _():
    # ---- params: edge safety ----
    SAFE_FILLET_R = 0.6  # 防割手圆角（平底外缘；走线口防割由 NOTCH_RR 轮廓承担）
    return (SAFE_FILLET_R,)


@app.cell
def _(CSINK_D, CSINK_DEPTH, NOTCH_RR, NOTCH_SILL):
    # ---- guard: parameter feasibility ----
    DIMS.check()
    _notch_h = DIMS.back_y - DIMS.boss_tip_y - 2.0 * NOTCH_SILL
    assert _notch_h > 2.0 * NOTCH_RR, f"走线口高 {_notch_h:.2f} 须大于两倍口角圆角 {NOTCH_RR}"
    assert CSINK_DEPTH < DIMS.wall_t - 0.5, f"沉头锥深 {CSINK_DEPTH} 须 < wall_t-0.5（地板留实体）"
    assert CSINK_D > DIMS.boss_hole_d, f"沉头锥口 {CSINK_D} 须大于孔径 {DIMS.boss_hole_d}"
    return


@app.cell
def _():
    # ---- feature: u-rod (build) ----
    u_rod = sweep_u_rod(DIMS)
    return (u_rod,)


@app.cell
def _(u_rod):
    # ---- feature: flat-bottom (subtract) ----
    # 第一刀 @ shell_bottom_y：切掉下半部，平底面产生于此
    _y = DIMS.shell_bottom_y
    flat_bottom = scad.cut_rsolid(u_rod, big_box(DIMS, _y, _y - 60.0))
    return (flat_bottom,)


@app.cell
def _(flat_bottom):
    # ---- feature: split-plane (subtract) ----
    # 第二刀 @ back_y：与上件分离，保留带 [shell_bottom_y, back_y]
    split_plane = scad.cut_rsolid(flat_bottom, big_box(DIMS, DIMS.back_y + 60.0, DIMS.back_y))
    return (split_plane,)


@app.cell
def _(split_plane):
    # ---- feature: cavity (subtract) ----
    # 内偏移扫掠 ∩ [boss_tip_y, back_y]：轮廓壁 wall_t，地板保持实体
    _cavity = scad.intersect_rsolid(
        sweep_eroded_rod(DIMS), big_box(DIMS, DIMS.back_y, DIMS.boss_tip_y))
    cavity = scad.cut_rsolid(split_plane, _cavity)
    return (cavity,)


@app.cell
def _(NOTCH_RR, NOTCH_SILL, NOTCH_W, cavity):
    # ---- feature: cable-notches (subtract) ----
    # 圆角矩形轮廓（口角圆角融入源型，免 fillet——矩形口边缘 fillet 在口角三面
    # 圆角相遇处内核稳定崩溃）；上下各留 sill 台阶，不与地板顶/rim 共面
    _xc = DIMS.L / 2.0 - DIMS.r_corner + 1.45 * DIMS.r
    _half_len = (DIMS.r + 4.0) / 2.0
    _y_lo = DIMS.boss_tip_y + NOTCH_SILL
    _y_hi = DIMS.back_y - NOTCH_SILL
    _notches = [
        rounded_rect_prism(
            _sx * _xc - _half_len, _sx * _xc + _half_len, _y_lo, _y_hi,
            -NOTCH_W / 2.0, NOTCH_W / 2.0, NOTCH_RR)
        for _sx in (-1, 1)
    ]
    cable_notches = scad.cut_rsolid(cavity, _notches)
    return (cable_notches,)


@app.cell
def _(SAFE_FILLET_R, cable_notches):
    # ---- feature: bottom-edge-fillet (modify) ----
    # 防割手圆角（S12 用户定向）：平底外缘，打孔前执行
    _bottom = ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop("geom.normal.y", "<=", -0.999),
        ql.prop("geom.center.y", ">=", DIMS.shell_bottom_y - 0.1),
        ql.prop("geom.center.y", "<=", DIMS.shell_bottom_y + 0.1),
        ql.prop("geom.area", ">=", 500.0),
    )).resolve(cable_notches)
    assert len(_bottom) == 1, f"平底面识别异常 n={len(_bottom)}"
    _rim = ql.edges().resolve(_bottom[0].get_outer_wire())
    assert len(_rim) >= 4, f"平底外缘边识别异常 n={len(_rim)}"
    bottom_edge_fillet = scad.fillet_rsolid(solid=cable_notches, edges=_rim, radius=SAFE_FILLET_R)
    return (bottom_edge_fillet,)


@app.cell
def _(CSINK_D, CSINK_DEPTH, bottom_edge_fillet):
    # ---- feature: countersunk-holes (subtract) ----
    # 通孔穿地板 + 自平底 90° 锥口，螺钉贴 boss 尖端拧入
    _y = DIMS.shell_bottom_y
    _hole_r = DIMS.boss_hole_d / 2.0
    _tools = []
    for _sx in (-1, 1):
        _bx = _sx * DIMS.boss_x
        _tools.append(scad.make_cylinder_rsolid(
            radius=_hole_r, height=DIMS.wall_t + 2.0,
            bottom_face_center=(_bx, _y - 1.0, 0.0), axis=(0.0, 1.0, 0.0)))
        _tools.append(scad.make_cone_rsolid(
            bottom_radius=CSINK_D / 2.0, top_radius=_hole_r, height=CSINK_DEPTH,
            bottom_face_center=(_bx, _y, 0.0), axis=(0.0, 1.0, 0.0)))
    countersunk_holes = scad.cut_rsolid(bottom_edge_fillet, _tools)
    return (countersunk_holes,)


@app.cell
def _(countersunk_holes):
    # ---- product: named faces, part, rim datum ----
    scad.apply_tag(shape=countersunk_holes, tag="role.shell")
    _flat_bottom = ql.faces().where(ql.and_(  # 整弦截面大面积 −Y 面
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop("geom.normal.y", "<=", -0.999),
        ql.prop("geom.center.y", ">=", DIMS.shell_bottom_y - 0.1),
        ql.prop("geom.center.y", "<=", DIMS.shell_bottom_y + 0.1),
        ql.prop("geom.area", ">=", 500.0),
    ))
    _rim = ql.faces().where(ql.and_(  # 第二刀平面，可能被接缝分面——全部命中
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop("geom.normal.y", ">=", 0.999),
        ql.prop("geom.center.y", ">=", DIMS.back_y - 0.1),
        ql.prop("geom.center.y", "<=", DIMS.back_y + 0.1),
        ql.prop("geom.area", ">=", 100.0),
    ))
    _body = scad.apply_tag_rselection(
        scope=countersunk_holes, targets=_flat_bottom, tag=TAG_SHELL_FLOOR)
    _body = scad.apply_tag_rselection(scope=_body, targets=_rim, tag=TAG_SHELL_RIM)
    _part = scad.make_part_rpart(part_id="u-link-shell", body=_body, name="U link shell")
    shell = scad.add_connector_rpart(
        part=_part,
        connector=scad.make_placement_connector_rconnector(
            connector_id="shell_rim",
            placement=scad.make_placement_rplacement(
                origin=(0.0, DIMS.back_y, 0.0), x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 0.0, 1.0)),
            name="Shell rim datum (z out -Y)",
        ),
    )
    return (shell,)


if __name__ == "__main__":
    app.run()

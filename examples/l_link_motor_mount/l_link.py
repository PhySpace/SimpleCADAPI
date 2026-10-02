# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "l-link-body"
# revision = "1.0.0"
# ///
"""l_link: 参数化 L 形垂直双电机连杆 —— 上件（l-link-body）。

L 形圆杆扫掠，两电机槽（左 +Y、右 +X）+ 命名安装面，"l" 剖分去壳区，剖分面下悬
长 boss + 十字筋（给壳体打螺丝），两端盖 rim 圆角，最后切走线窗 / 三叉凹槽 / 径向沉头。
尺寸与守卫链在 ``dimensions.py``（三件共用，坐标约定见那里），共用几何在 ``common.py``。

    sca run examples/l_link_motor_mount/l_link.py
"""

import marimo

app = marimo.App()

with app.setup:
    import math

    import simplecadapi as scad
    from simplecadapi import ql

    from common import (
        key_star_face,
        motor_left_placement,
        mount2_datum_placement,
        rounded_rect_face,
        split_datum_placement,
        split_region_tool,
        sweep_l_rod,
    )
    from dimensions import (
        BOSS_ROOT_OVERSHOOT,
        TAG_MOUNT_LEFT,
        TAG_MOUNT_RIGHT,
        back_y,
        boss_xs,
        check_body,
        mount_x,
        pad_top,
        params,
        pocket_r,
        radial_angles,
        radial_x,
        rib_low_x,
        x_end,
    )


@app.function
def mount_floor_selector(p: dict, side: str) -> ql.ShapeSelector:
    """安装面几何谓词：左 = 平面 +Y @ y=d_motor/2（x≈0）；右 = 平面 +X @ x=L-plate_t（y≈0）。"""
    if side == "left":
        axis, value, lateral = "y", p["d_motor"] / 2.0, "x"
    else:
        axis, value, lateral = "x", mount_x(p), "y"
    return ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop(f"geom.normal.{axis}", ">=", 0.999),
        ql.prop(f"geom.center.{axis}", ">=", value - 0.1),
        ql.prop(f"geom.center.{axis}", "<=", value + 0.1),
        ql.prop(f"geom.center.{lateral}", ">=", -0.1),
        ql.prop(f"geom.center.{lateral}", "<=", 0.1),
    )).exactly(1)


@app.function
def cross_rib_tools(p: dict) -> list:
    """每 boss 两片十字筋（沿 X、沿 Z），共 4 个三角筋。

    XY 六边形约束草图（dof=0，原点 = boss 轴 ∩ 剖分面）：顶边 y=+overshoot 伸入上件 → 竖直外边 u=±(br+rib_len)
    → 斜边到 (±x_i, −gusset_h) → 底边穿过 boss 内部；extrude +Z rib_t 并居中，Z 向片再绕 Y 转 90°（度制）。
    """
    a, xi, gh, ovs = p["boss_d"] / 2.0 + p["rib_len"], rib_low_x(p), p["gusset_h"], BOSS_ROOT_OVERSHOOT
    sketch = scad.make_sketch_rsketch(name="boss_cross_rib", plane="XY")
    seeds = {"top_l": (-a, ovs), "top_r": (a, ovs), "tip_r": (a, 0.0), "low_r": (xi, -gh),
             "low_l": (-xi, -gh), "tip_l": (-a, 0.0)}
    for pid, (x, y) in seeds.items():
        sketch = scad.add_point_rsketch(sketch=sketch, point_id=pid, x=x, y=y)
    for eid, start, end in (("top", "top_l", "top_r"), ("side_r", "top_r", "tip_r"), ("hyp_r", "tip_r", "low_r"),
                            ("bottom", "low_r", "low_l"), ("hyp_l", "low_l", "tip_l"), ("side_l", "tip_l", "top_l")):
        sketch = scad.add_line_rsketch(sketch=sketch, entity_id=eid, start=start, end=end)
    for pid in ("tip_r", "low_r", "low_l", "tip_l"):
        sketch = scad.constrain_fix_rsketch(sketch=sketch, target=pid)
    sketch = scad.constrain_horizontal_rsketch(sketch=sketch, line="top")
    sketch = scad.constrain_vertical_rsketch(sketch=sketch, line="side_r")
    sketch = scad.constrain_vertical_rsketch(sketch=sketch, line="side_l")
    sketch = scad.constrain_distance_y_rsketch(sketch=sketch, a="tip_r", b="top_r", value=ovs)
    face = scad.make_face_from_sketch_rface(sketch=sketch, require_fully_constrained=True)
    rib_x = scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=p["rib_t"])
    rib_x = scad.translate_shape(shape=rib_x, vector=(0.0, 0.0, -p["rib_t"] / 2.0))
    rib_z = scad.rotate_shape(shape=rib_x, angle=90.0, axis=(0.0, 1.0, 0.0))
    by = back_y(p)
    return [scad.translate_shape(shape=rib, vector=(bx, by, 0.0)) for bx in boss_xs(p) for rib in (rib_x, rib_z)]


@app.function
def cable_window_tools(p: dict) -> list:
    """8 走线窗（U-link 同法）：共享圆角矩形 extrude 过轴线（±rod_d），一棱柱切对侧 2 窗；
    绕各自电机轴 rotate phase / phase+90 → 每槽 4 窗。左：宽切向 x、高轴向 y，绕 Y；右：高轴向 x、宽切向 y，绕 X。"""
    span, off, wh, ww, wr = p["rod_d"], p["cable_w_off"], p["cable_w_h"], p["cable_w_w"], p["cable_w_rr"]
    sides = ((rounded_rect_face(name="cable_window_left", w=ww, h=wh, rr=wr), (0.0, 1.0, 0.0),
              (0.0, p["d_motor"] / 2.0 + off + wh / 2.0, 0.0)),
             (rounded_rect_face(name="cable_window_right", w=wh, h=ww, rr=wr), (1.0, 0.0, 0.0),
              (p["L"] + off + wh / 2.0, 0.0, 0.0)))
    tools = []
    for face, axis, at in sides:
        prism = scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=2.0 * span)
        prism = scad.translate_shape(shape=prism, vector=(0.0, 0.0, -span))
        for rot in (p["cable_w_phase"], p["cable_w_phase"] + 90.0):
            tools.append(scad.translate_shape(shape=scad.rotate_shape(shape=prism, angle=rot, axis=axis), vector=at))
    return tools


@app.function
def radial_csink_tools(p: dict) -> list:
    """径向 M2 沉头（纯圆柱 / 锥，geometry tier）：沿 +Y 建一组（锪平 ⌀rad_spot_d 自 r−spot_depth 越出外皮、
    90° 锥自锪平底向内收到过孔、过孔自槽内 −1 越过），绕 X rotate 到各 radial_angles。"""
    r, rp, xs = p["rod_d"] / 2.0, pocket_r(p), radial_x(p)
    hr, cr, sr = p["rad_clear_d"] / 2.0, p["rad_csink_d"] / 2.0, p["rad_spot_d"] / 2.0
    # 锥 overshoot 须留在锪平圆柱内（cr+ovs < sr）：越出则在锪平侧壁上削出锥带，带在 z 向端点贴皮而随
    # rad_spot_d 断成数片（S10 rad_spot_d 边界：默认余量仅 0.002）
    ys, ovs = r - p["rad_spot_depth"], min(0.2, (sr - cr) / 2.0)
    one = [scad.make_cylinder_rsolid(radius=sr, height=r + 1.0 - ys, bottom_face_center=(xs, ys, 0.0), axis=(0.0, 1.0, 0.0)),
           scad.make_cone_rsolid(bottom_radius=cr + ovs, top_radius=hr, height=(cr - hr) + ovs,
                                 bottom_face_center=(xs, ys + ovs, 0.0), axis=(0.0, -1.0, 0.0)),
           scad.make_cylinder_rsolid(radius=hr, height=(r - rp) + 2.0, bottom_face_center=(xs, rp - 1.0, 0.0),
                                     axis=(0.0, 1.0, 0.0))]
    return [scad.rotate_shape(shape=t, angle=a, axis=(1.0, 0.0, 0.0)) for a in radial_angles(p) for t in one]


@app.cell
def _():
    # ---- params: shared dimensions (dimensions.py) ----
    p = params()
    return (p,)


@app.cell
def _(p):
    # ---- guard: parameter feasibility (REQUIREMENTS.md) ----
    check_body(p)
    return


@app.cell
def _(p):
    # ---- feature: l-rod (build, profile=geometry, path=sketch) ----
    l_rod = sweep_l_rod(p, p["rod_d"])
    scad.apply_tag(shape=l_rod, tag="role.l_rod")
    return (l_rod,)


@app.cell
def _(l_rod, p):
    # ---- feature: motor-pockets (subtract, profile=geometry) ----
    # 两电机槽刀具（纯圆柱）：左 轴 +Y 自 y=d_motor/2；右 轴 +X 自 x=L-plate_t；均越过端盖 5（overshoot，否则留皮）
    _rp, _fy, _fx = pocket_r(p), p["d_motor"] / 2.0, mount_x(p)
    _pockets = [
        scad.make_cylinder_rsolid(radius=_rp, height=(p["D"] - _fy) + 5.0,
                                  bottom_face_center=(0.0, _fy, 0.0), axis=(0.0, 1.0, 0.0)),
        scad.make_cylinder_rsolid(radius=_rp, height=(x_end(p) - _fx) + 5.0,
                                  bottom_face_center=(_fx, 0.0, 0.0), axis=(1.0, 0.0, 0.0)),
    ]
    motor_pockets = scad.cut_rsolid(l_rod, _pockets)
    return (motor_pockets,)


@app.cell
def _(motor_pockets, p):
    # ---- feature: l-split (subtract, profile=sketch) ----
    # 与壳体 shell-region 共用同一把壳区刀具：上件 = 杆 − 壳区
    l_split = scad.cut_rsolid(motor_pockets, split_region_tool(p))
    return (l_split,)


@app.cell
def _(l_split, p):
    # ---- feature: boss-columns (add, profile=geometry) ----
    # boss 柱（纯圆柱）：轴 +Y 自 pad_top 至 back_y+overshoot（伸入上件，并集不留缝）
    _y0, _y1 = pad_top(p), back_y(p) + BOSS_ROOT_OVERSHOOT
    _columns = [scad.make_cylinder_rsolid(radius=p["boss_d"] / 2.0, height=_y1 - _y0,
                                          bottom_face_center=(_bx, _y0, 0.0), axis=(0.0, 1.0, 0.0))
                for _bx in boss_xs(p)]
    boss_columns = scad.union_rsolid(l_split, *_columns)
    return (boss_columns,)


@app.cell
def _(boss_columns, p):
    # ---- feature: boss-cross-ribs (add, profile=sketch) ----
    boss_cross_ribs = scad.union_rsolid(boss_columns, *cross_rib_tools(p))
    return (boss_cross_ribs,)


@app.cell
def _(boss_cross_ribs, p):
    # ---- feature: rib-chamfer (modify) ----
    # 筋斜边（每筋两侧面各 1 条）：长度 √((br+rl−x_i)² + gh²) 窗 + y 带 [by−gh, by] → 恰 16
    _by, _gh = back_y(p), p["gusset_h"]
    _hyp = math.hypot(p["boss_d"] / 2.0 + p["rib_len"] - rib_low_x(p), _gh)
    _hypotenuses = ql.edges().where(ql.and_(
        ql.prop("geom.length", ">=", _hyp - 0.15), ql.prop("geom.length", "<=", _hyp + 0.15),
        ql.prop("geom.center.y", ">=", _by - _gh - 0.3), ql.prop("geom.center.y", "<=", _by + 0.3),
    )).exactly(16)
    rib_chamfer = scad.chamfer_rsolid(solid=boss_cross_ribs, edges=_hypotenuses, distance=p["gusset_chamfer"])
    return (rib_chamfer,)


@app.cell
def _(p, rib_chamfer):
    # ---- feature: boss-holes (subtract, profile=geometry) ----
    # boss 自攻盲孔（纯圆柱）：自 pad_top 下方 1（overshoot）向 +Y 至 pad_top + boss_hole_depth
    _y0 = pad_top(p) - 1.0
    _holes = [scad.make_cylinder_rsolid(radius=p["boss_hole_d"] / 2.0, height=p["boss_hole_depth"] + 1.0,
                                        bottom_face_center=(_bx, _y0, 0.0), axis=(0.0, 1.0, 0.0))
              for _bx in boss_xs(p)]
    boss_holes = scad.cut_rsolid(rib_chamfer, _holes)
    return (boss_holes,)


@app.cell
def _(boss_holes, p):
    # ---- feature: cap-rim-fillet (modify) ----
    # 只倒 4 条端盖 rim：两端盖平面（+Y @ y=D、+X @ x=x_end）的边界 = 外环 r + 槽口 rp ×2；
    # 槽底边 / 剖分接口边 / boss·筋保持锐（REQUIREMENTS §9）
    _rims = ql.faces().where(ql.and_(ql.prop("geom.type", "==", "PLANE"), ql.or_(
        ql.and_(ql.prop("geom.normal.y", ">=", 0.999), ql.prop("geom.center.y", ">=", p["D"] - 0.05)),
        ql.and_(ql.prop("geom.normal.x", ">=", 0.999), ql.prop("geom.center.x", ">=", x_end(p) - 0.05)),
    ))).boundary("edge").exactly(4)
    cap_rim_fillet = scad.fillet_rsolid(boss_holes, _rims, p["fillet_r"])
    return (cap_rim_fillet,)


@app.cell
def _(cap_rim_fillet, p):
    # ---- feature: cable-windows (subtract, profile=sketch) ----
    # 倒角后切削：窗 / 凹槽 / 径向孔不在 rim 圆角带内（守卫），圆角先做 rim 选择器保持恰 4
    cable_windows = scad.cut_rsolid(cap_rim_fillet, cable_window_tools(p))
    return (cable_windows,)


@app.cell
def _(cable_windows, p):
    # ---- feature: key-groove (subtract, profile=sketch) ----
    # 安装面 2 三叉凹槽：星形草图（臂宽 key_w+2·gap、臂长 key_r_out+gap）自槽底 x=L−plate_t−groove_d
    # 向 +X 拉伸 groove_d + 1（越过安装面 overshoot）
    _gd = p["groove_d"]
    _face = key_star_face("key_groove", p["key_w"] + 2.0 * p["key_gap"], p["key_r_out"] + p["key_gap"], p["key_phase"])
    _tool = scad.extrude_rsolid(profile=_face, direction=(0.0, 0.0, 1.0), distance=_gd + 1.0)
    _tool = scad.rotate_shape(shape=_tool, angle=90.0, axis=(0.0, 1.0, 0.0))
    _tool = scad.translate_shape(shape=_tool, vector=(mount_x(p) - _gd, 0.0, 0.0))
    key_groove = scad.cut_rsolid(cable_windows, _tool)
    return (key_groove,)


@app.cell
def _(key_groove, p):
    # ---- feature: radial-csinks (subtract, profile=geometry) ----
    radial_csinks = scad.cut_rsolid(key_groove, radial_csink_tools(p))
    return (radial_csinks,)


@app.cell
def _(p, radial_csinks):
    # ---- feature: mount-face-names (annotate) ----
    # tag 不跨 cut_rsolid / fillet_rsolid 存活 → 命名放在最后一次布尔 / 圆角之后
    _body = scad.apply_tag_rselection(scope=radial_csinks, targets=mount_floor_selector(p, "left"),
                                      tag=TAG_MOUNT_LEFT)
    mount_face_names = scad.apply_tag_rselection(scope=_body, targets=mount_floor_selector(p, "right"),
                                                 tag=TAG_MOUNT_RIGHT)
    return (mount_face_names,)


@app.cell
def _(mount_face_names, p):
    # ---- product: part + assembly datums (modeled in install position -> identity placements) ----
    _part = scad.make_part_rpart(part_id="l-link-body", body=mount_face_names,
                                 name="L link upper body (two perpendicular motors)")
    for _connector_id, _placement, _name in (
            ("split_datum", split_datum_placement(p), "Split plane datum (z out -Y)"),
            ("mount2_datum", mount2_datum_placement(p), "Mount face 2 datum (z out +X, x along key phase)"),
            ("motor_left", motor_left_placement(p), "Left motor interface (mount face centre, z = motor axis +Y)")):
        _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(
            connector_id=_connector_id, placement=_placement, name=_name))
    l_link_body = _part
    return (l_link_body,)


if __name__ == "__main__":
    app.run()

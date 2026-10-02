# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "l-link-shell"
# revision = "1.0.0"
# ///
"""l_link shell（l-link-shell）—— "l" 剖分下侧的圆底管壳。

与上件同坐标系、装配位建模（placement=identity）；剖分刀具取自 ``common.split_region_tool``，
上件 = 杆 − 壳区、壳体 = 杆 ∩ 壳区（一刀两件，接口平面 y=back_y / 相切弧 / 平面 x=x_b 天然贴合）。
壳区不含任何电机槽（``dimensions.check_body`` S3 守卫），故壳体直接取自实心杆。
内腔 = 内缩扫掠（r−wall_t，同 L 路径）∩ 腔区（剖分面敞口；弧/竖直端壁内偏 wall_t → 等厚弧形端壁）。

    sca run examples/l_link_motor_mount/shell.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql

    from common import rounded_rect_face, split_datum_placement, split_region_tool, sweep_l_rod
    from dimensions import (
        CAVITY_OVERSHOOT,
        TAG_SHELL_RIM,
        TAG_SKIN,
        back_y,
        boss_xs,
        check_shell,
        coax_hole_x,
        coax_tool_top,
        notch_band,
        pad_top,
        params,
        shell_csink_depth,
        split_xs,
        spot_y,
    )


@app.function
def cavity_region_tool(p: dict) -> scad.Solid:
    """腔区刀具：XY 闭合约束草图（dof=0）→ 拉伸居中。

    顶 y=back_y+ovs（剖分面敞口）至 x_a → 台阶下到 back_y−wall_t → 同心弧 R=Rs−wall_t（心同剖分弧）
    → 竖直 x=x_b−wall_t 至杆下方 → 底边 → 后边。
    """
    r, wt, ovs, by = p["rod_d"] / 2.0, p["wall_t"], CAVITY_OVERSHOOT, back_y(p)
    xa, xb = split_xs(p)
    cy, lo = by - (xb - xa), -r - ovs
    sketch = scad.make_sketch_rsketch(name="shell_cavity_region", plane="XY")
    seeds = {"top_l": (lo, by + ovs), "top_r": (xa, by + ovs), "step_foot": (xa, by - wt),
             "arc_c": (xa, cy), "arc_b": (xb - wt, cy), "drop_foot": (xb - wt, lo), "foot": (lo, lo)}
    for pid, (x, y) in seeds.items():
        sketch = scad.add_point_rsketch(sketch=sketch, point_id=pid, x=x, y=y)
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="top", start="top_l", end="top_r")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="step", start="top_r", end="step_foot")
    sketch = scad.add_arc_rsketch(sketch=sketch, entity_id="bend", start="arc_b", end="step_foot",
                                  center="arc_c")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="drop", start="arc_b", end="drop_foot")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="floor", start="drop_foot", end="foot")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="back", start="foot", end="top_l")
    sketch = scad.constrain_fix_rsketch(sketch=sketch, target="arc_c")
    sketch = scad.constrain_fix_rsketch(sketch=sketch, target="step_foot")
    sketch = scad.constrain_vertical_rsketch(sketch=sketch, line="step")
    sketch = scad.constrain_horizontal_rsketch(sketch=sketch, line="top")
    sketch = scad.constrain_vertical_rsketch(sketch=sketch, line="drop")
    sketch = scad.constrain_horizontal_rsketch(sketch=sketch, line="floor")
    sketch = scad.constrain_vertical_rsketch(sketch=sketch, line="back")
    sketch = scad.constrain_tangent_rsketch(sketch=sketch, a="bend", b="drop", at_a="start")
    sketch = scad.constrain_distance_y_rsketch(sketch=sketch, a="step_foot", b="top_r", value=wt + ovs)
    sketch = scad.constrain_distance_x_rsketch(sketch=sketch, a="top_l", b="top_r", value=xa - lo)
    sketch = scad.constrain_distance_y_rsketch(sketch=sketch, a="foot", b="step_foot", value=by - wt - lo)
    face = scad.make_face_from_sketch_rface(sketch=sketch, require_fully_constrained=True)
    depth = r + ovs
    tool = scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=2.0 * depth)
    return scad.translate_shape(shape=tool, vector=(0.0, 0.0, -depth))


@app.function
def notch_outer_selector(p: dict) -> ql.ShapeSelector:
    """左端走线口外环 = 走线口面（x<0、y 带、z 带）与杆外皮（TAG_SKIN）的共享边 → 恰 8。"""
    y_bot, y_top = notch_band(p)
    hw = p["notch_w"] / 2.0 + 0.1
    notch_faces = ql.faces().where(ql.and_(
        ql.prop("geom.center.x", "<", 0.0),
        ql.prop("geom.center.y", ">=", y_bot - 0.1), ql.prop("geom.center.y", "<=", y_top + 0.1),
        ql.prop("geom.center.z", ">=", -hw), ql.prop("geom.center.z", "<=", hw)))
    return notch_faces.shared_boundary(ql.faces().where(ql.tag(TAG_SKIN)), to_kind="edge").exactly(8)


@app.function
def coax_outer_selector(p: dict) -> ql.ShapeSelector:
    """同轴孔外环 = 孔面（x/z 窗 + 壁厚 y 带）的边中 center.y ≤ 壁中面 −(r−wall_t/2) 者 → 恰 8。"""
    r, wt, cx = p["rod_d"] / 2.0, p["wall_t"], coax_hole_x(p)
    hx, hw = p["notch_h"] / 2.0 + 0.05, p["notch_w"] / 2.0 + 0.05
    hole = ql.faces().where(ql.and_(
        ql.prop("geom.center.x", ">=", cx - hx), ql.prop("geom.center.x", "<=", cx + hx),
        ql.prop("geom.center.y", ">=", -r - 0.05), ql.prop("geom.center.y", "<=", -(r - wt) + 0.05),
        ql.prop("geom.center.z", ">=", -hw), ql.prop("geom.center.z", "<=", hw)))
    return hole.boundary("edge").where(ql.prop("geom.center.y", "<=", -(r - wt / 2.0))).exactly(8)


@app.cell
def _():
    # ---- params: shared dimensions (dimensions.py) ----
    p = params()
    return (p,)


@app.cell
def _(p):
    # ---- guard: parameter feasibility (REQUIREMENTS.md; includes the body chain) ----
    check_shell(p)
    return


@app.cell
def _(p):
    # ---- feature: l-rod (build, profile=geometry, path=sketch) ----
    # 外皮打 TAG_SKIN：opening-fillets 用皮面选走线口外环（任何 fillet 后即失效）
    l_rod = sweep_l_rod(p, p["rod_d"], skin_tag=TAG_SKIN)
    return (l_rod,)


@app.cell
def _(l_rod, p):
    # ---- feature: shell-region (intersect, profile=sketch) ----
    shell_region = scad.intersect_rsolid(l_rod, split_region_tool(p))
    scad.apply_tag(shape=shell_region, tag="role.shell")
    return (shell_region,)


@app.cell
def _(p, shell_region):
    # ---- feature: shell-cavity (subtract, profile=sketch) ----
    _cavity = scad.intersect_rsolid(sweep_l_rod(p, p["rod_d"] - 2.0 * p["wall_t"]), cavity_region_tool(p))
    shell_cavity = scad.cut_rsolid(shell_region, _cavity)
    return (shell_cavity,)


@app.cell
def _(p, shell_cavity):
    # ---- feature: cable-notch (subtract, profile=sketch) ----
    # 左端走线口：圆角矩形（宽 notch_w 沿 z、高 notch_h 沿 y）沿 +X 自杆外 ovs 至左电机轴 x=0；
    # extrude +Z 后绕 Y 转 90°（+Z→+X，度制），再平移一次到位
    _lo = -p["rod_d"] / 2.0 - CAVITY_OVERSHOOT
    _y_bot, _y_top = notch_band(p)
    _face = rounded_rect_face(name="shell_notch", w=p["notch_w"], h=p["notch_h"], rr=p["notch_rr"])
    _tool = scad.extrude_rsolid(profile=_face, direction=(0.0, 0.0, 1.0), distance=-_lo)
    _tool = scad.rotate_shape(shape=_tool, angle=90.0, axis=(0.0, 1.0, 0.0))
    _tool = scad.translate_shape(shape=_tool, vector=(_lo, (_y_bot + _y_top) / 2.0, 0.0))
    cable_notch = scad.cut_rsolid(shell_cavity, _tool)
    return (cable_notch,)


@app.cell
def _(cable_notch, p):
    # ---- feature: boss-pads (add, profile=geometry) ----
    # pad（纯圆柱）：轴 +Y 自壳壁中面 −(r−wall_t/2)（埋入壁内）至平顶 pad_top
    _y0, _y1 = -(p["rod_d"] / 2.0 - p["wall_t"] / 2.0), pad_top(p)
    _pads = [scad.make_cylinder_rsolid(radius=p["pad_d"] / 2.0, height=_y1 - _y0,
                                       bottom_face_center=(_bx, _y0, 0.0), axis=(0.0, 1.0, 0.0))
             for _bx in boss_xs(p)]
    boss_pads = scad.union_rsolid(cable_notch, *_pads)
    return (boss_pads,)


@app.cell
def _(boss_pads, p):
    # ---- feature: spot-faces (subtract, profile=geometry) ----
    # 外侧锪平（纯圆柱）：自管底外 1（overshoot）至锪平平面 spot_y
    _y0 = -p["rod_d"] / 2.0 - 1.0
    _spots = [scad.make_cylinder_rsolid(radius=p["spot_d"] / 2.0, height=spot_y(p) - _y0,
                                        bottom_face_center=(_bx, _y0, 0.0), axis=(0.0, 1.0, 0.0))
              for _bx in boss_xs(p)]
    spot_faces = scad.cut_rsolid(boss_pads, _spots)
    return (spot_faces,)


@app.cell
def _(p, spot_faces):
    # ---- feature: csink-holes (subtract, profile=geometry) ----
    # 90° 沉头锥（锥口自锪平面下 0.2 overshoot，半径同步 +0.2）+ 通孔（两端 overshoot 1）
    _ys, _cr, _hr, _ovs = spot_y(p), p["csink_d"] / 2.0, p["shell_hole_d"] / 2.0, 0.2
    _y0, _y1 = -p["rod_d"] / 2.0 - 1.0, pad_top(p) + 1.0
    _tools = []
    for _bx in boss_xs(p):
        _tools.append(scad.make_cone_rsolid(bottom_radius=_cr + _ovs, top_radius=_hr,
                                            height=shell_csink_depth(p) + _ovs,
                                            bottom_face_center=(_bx, _ys - _ovs, 0.0), axis=(0.0, 1.0, 0.0)))
        _tools.append(scad.make_cylinder_rsolid(radius=_hr, height=_y1 - _y0, bottom_face_center=(_bx, _y0, 0.0),
                                                axis=(0.0, 1.0, 0.0)))
    csink_holes = scad.cut_rsolid(spot_faces, _tools)
    return (csink_holes,)


@app.cell
def _(csink_holes, p):
    # ---- feature: coax-cable-hole (subtract, profile=sketch) ----
    # 壳底 −Y 同轴走线孔：共享圆角矩形（notch_h 沿 x、notch_w 沿 z）extrude +Z →
    # 绕 X 转 +90°（+Z→−Y，度制）→ 平移一次到 (cx, 腔内 y1, 0)；向下越过管底 overshoot
    _y1 = coax_tool_top(p)
    _face = rounded_rect_face(name="shell_coax_hole", w=p["notch_h"], h=p["notch_w"], rr=p["notch_rr"])
    _tool = scad.extrude_rsolid(profile=_face, direction=(0.0, 0.0, 1.0),
                                distance=_y1 + p["rod_d"] / 2.0 + CAVITY_OVERSHOOT)
    _tool = scad.rotate_shape(shape=_tool, angle=90.0, axis=(1.0, 0.0, 0.0))
    _tool = scad.translate_shape(shape=_tool, vector=(coax_hole_x(p), _y1, 0.0))
    coax_cable_hole = scad.cut_rsolid(csink_holes, _tool)
    return (coax_cable_hole,)


@app.cell
def _(coax_cable_hole, p):
    # ---- feature: opening-fillets (modify) ----
    # 只倒两口外环（内环倒会漫到腔壁 / rim 相邻面，锪平边太薄）；皮面 tag 在第一次 fillet 后失效
    # → 先倒走线口（皮面选择器），再倒同轴孔（几何选择器）
    _shell = scad.fillet_rsolid(coax_cable_hole, notch_outer_selector(p), p["safe_fillet_r"])
    opening_fillets = scad.fillet_rsolid(_shell, coax_outer_selector(p), p["safe_fillet_r"])
    return (opening_fillets,)


@app.cell
def _(opening_fillets, p):
    # ---- feature: rim-name (annotate) ----
    # rim = 平面 +Y @ y=back_y 且在弧起点 x_a 左侧（接口水平段）；tag 不跨布尔 / 圆角存活 → 最后打
    _by = back_y(p)
    _xa, _ = split_xs(p)
    _rim = ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop("geom.normal.y", ">=", 0.999),
        ql.prop("geom.center.y", ">=", _by - 0.05),
        ql.prop("geom.center.y", "<=", _by + 0.05),
        ql.prop("geom.center.x", "<", _xa),
    )).exactly(1)
    rim_name = scad.apply_tag_rselection(scope=opening_fillets, targets=_rim, tag=TAG_SHELL_RIM)
    return (rim_name,)


@app.cell
def _(p, rim_name):
    # ---- product: part + rim datum (= body split_datum) ----
    _part = scad.make_part_rpart(part_id="l-link-shell", body=rim_name, name="L link shell")
    l_link_shell = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(
        connector_id="shell_rim", placement=split_datum_placement(p), name="Shell rim datum (z out -Y)"))
    return (l_link_shell,)


if __name__ == "__main__":
    app.run()

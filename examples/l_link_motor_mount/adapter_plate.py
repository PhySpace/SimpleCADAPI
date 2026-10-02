# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "l-link-adapter-star3"
# revision = "1.0.0"
# ///
"""电机2 转接板（l-link-adapter-<preset>）—— 零件族，每个 preset 一个成员。

与上件同坐标系、装配位建模（placement=identity）：圆盘轴 X，背面 x=L−plate_t 贴安装面 2，
外表面 x=L = 电机2 落座面（tag feature.motor_seat_right）；三叉凸起自背面向 −X 伸入上件凹槽。
盘面拓扑由 ``PlatePreset`` 的 if 分支决定（孔数 / 孔相位 / 凸起臂段 / 有无中心孔），Var 只承载标量尺寸。
凸起草图与上件凹槽共用 ``common.key_star_face``；径向导孔与上件径向沉头共用 ``dimensions.radial_x / radial_angles``。

族成员 id = ``dimensions.plate_part_id(preset)``：

    sca run examples/l_link_motor_mount/adapter_plate.py
    sca run examples/l_link_motor_mount/adapter_plate.py --id l-link-adapter-center4 --set PRESET=center4
"""

import marimo

app = marimo.App()

with app.setup:
    import math

    import simplecadapi as scad
    from simplecadapi import ql

    from common import key_star_face, motor_right_placement, mount2_datum_placement
    from dimensions import (
        KEY_ROOT_OVERSHOOT,
        TAG_BACK,
        TAG_KEY_TOP,
        TAG_SEAT,
        PlatePreset,
        check_plate,
        hole_angles,
        mount_x,
        params,
        pilot_inner_r,
        plate_layout,
        plate_part_id,
        plate_r,
        polar,
        radial_angles,
        radial_x,
    )


@app.function
def plane_x_selector(x: float, sign: float, count: int, lateral: bool = True) -> ql.ShapeSelector:
    """法向 ±X、心 x 的 PLANE（lateral: 心在轴线上，对称盘面）→ 恰 count。"""
    preds = [ql.prop("geom.type", "==", "PLANE"),
             ql.prop("geom.normal.x", ">=" if sign > 0 else "<=", 0.999 * sign),
             ql.prop("geom.center.x", ">=", x - 0.05), ql.prop("geom.center.x", "<=", x + 0.05)]
    if lateral:
        preds += [ql.prop(f"geom.center.{a}", op, v) for a in ("y", "z") for op, v in ((">=", -0.1), ("<=", 0.1))]
    return ql.faces().where(ql.and_(*preds)).exactly(count)


@app.function
def key_hub_relief_tool(p: dict, preset: PlatePreset) -> scad.Solid:
    """STAR3 中心柱：半径 key_r0，自凸起顶外 1 至板背面。"""
    return scad.make_cylinder_rsolid(radius=plate_layout(p, preset)["key_r0"], height=p["key_h"] + 1.0,
                                     bottom_face_center=(mount_x(p) - p["key_h"] - 1.0, 0.0, 0.0),
                                     axis=(1.0, 0.0, 0.0))


@app.function
def center_bore_tool(p: dict, preset: PlatePreset) -> scad.Solid:
    """STAR3 中心过孔：直径 bore_d，自凸起顶外 1 贯穿板体。"""
    return scad.make_cylinder_rsolid(radius=plate_layout(p, preset)["bore_d"] / 2.0,
                                     height=p["plate_t"] + p["key_h"] + 2.0,
                                     bottom_face_center=(mount_x(p) - p["key_h"] - 1.0, 0.0, 0.0),
                                     axis=(1.0, 0.0, 0.0))


@app.cell
def _():
    # ---- params: shared dimensions (dimensions.py) ----
    p = params()
    return (p,)


@app.cell
def _():
    # ---- params: plate preset (family member) ----
    PRESET = "star3"
    return (PRESET,)


@app.cell
def _(PRESET, p):
    # ---- guard: parameter feasibility (REQUIREMENTS.md; body + shell + both presets) ----
    preset = PlatePreset(PRESET)
    check_plate(p)
    assert scad.notebook_id() == plate_part_id(preset), \
        f"notebook id {scad.notebook_id()!r} must be {plate_part_id(preset)!r} for preset {PRESET!r}"
    return (preset,)


@app.cell
def _(p):
    # ---- feature: plate-disk (build, profile=geometry) ----
    # 板体圆盘（纯圆柱）：轴 +X，x∈[L−plate_t, L]
    plate_disk = scad.make_cylinder_rsolid(radius=plate_r(p), height=p["plate_t"],
                                           bottom_face_center=(mount_x(p), 0.0, 0.0), axis=(1.0, 0.0, 0.0))
    return (plate_disk,)


@app.cell
def _(p, plate_disk):
    # ---- feature: plate-rim-fillet (modify) ----
    # 外圆两 rim 在凸起 / 孔之前倒（守卫保证其余特征不进圆角带）；凸起根部 / 顶边保持锐（配合面）
    # 选择：边长 2π·plate_r 窗 → 恰 2（孔 / 沉头口边长远小于此）
    _c = 2.0 * math.pi * plate_r(p)
    _rims = ql.edges().where(ql.and_(ql.prop("geom.length", ">=", _c - 0.1),
                                     ql.prop("geom.length", "<=", _c + 0.1))).exactly(2)
    plate_rim_fillet = scad.fillet_rsolid(plate_disk, _rims, p["safe_fillet_r"])
    return (plate_rim_fillet,)


@app.cell
def _(p, plate_rim_fillet, preset):
    # ---- feature: locating-key (add, profile=sketch) ----
    # 共享星形草图（臂宽 key_w、臂长 key_r1）extrude +Z → rotate +90° 绕 Y → translate 到背面外；
    # 高 key_h + 伸入板体 KEY_ROOT_OVERSHOOT
    _face = key_star_face(f"plate_key_{preset.value}", p["key_w"], plate_layout(p, preset)["key_r1"], p["key_phase"])
    _key = scad.extrude_rsolid(profile=_face, direction=(0.0, 0.0, 1.0), distance=p["key_h"] + KEY_ROOT_OVERSHOOT)
    _key = scad.rotate_shape(shape=_key, angle=90.0, axis=(0.0, 1.0, 0.0))
    _key = scad.translate_shape(shape=_key, vector=(mount_x(p) - p["key_h"], 0.0, 0.0))
    locating_key = scad.union_rsolid(plate_rim_fillet, _key)
    return (locating_key,)


@app.cell
def _(locating_key, p, preset):
    # ---- feature: key-hub-relief (subtract, profile=geometry) ----
    # STAR3 臂段 r ≥ key_r0：自凸起顶外 1 至板背面的中心柱（CENTER4 中心星不切，原样传递）。
    # 须在并入板体之后切——单独 cut 星形得 3 段分离臂，cut_rsolid 只保留其中一段
    key_hub_relief = (scad.cut_rsolid(locating_key, key_hub_relief_tool(p, preset))
                      if preset is PlatePreset.STAR3 else locating_key)
    return (key_hub_relief,)


@app.cell
def _(key_hub_relief, p, preset):
    # ---- feature: motor-screw-csinks (subtract, profile=geometry) ----
    # 过孔贯穿；90° 锥自背面（锥口 overshoot 0.2）向 +X 收到过孔
    _x0, _hr, _cr, _ovs, _rc = mount_x(p), p["m2_hole_d"] / 2.0, p["m2_csink_d"] / 2.0, 0.2, p["m2_pcd"] / 2.0
    _tools = []
    for _a in hole_angles(p, preset):
        _y, _z = polar(_rc, _a)
        _tools.append(scad.make_cylinder_rsolid(radius=_hr, height=p["plate_t"] + 2.0,
                                                bottom_face_center=(_x0 - 1.0, _y, _z), axis=(1.0, 0.0, 0.0)))
        _tools.append(scad.make_cone_rsolid(bottom_radius=_cr + _ovs, top_radius=_hr, height=(_cr - _hr) + _ovs,
                                            bottom_face_center=(_x0 - _ovs, _y, _z), axis=(1.0, 0.0, 0.0)))
    motor_screw_csinks = scad.cut_rsolid(key_hub_relief, _tools)
    return (motor_screw_csinks,)


@app.cell
def _(motor_screw_csinks, p, preset):
    # ---- feature: center-bore (subtract, profile=geometry) ----
    # STAR3 中心过孔（避让电机轴 / 卡簧）；CENTER4 无中心孔，原样传递
    center_bore = (scad.cut_rsolid(motor_screw_csinks, center_bore_tool(p, preset))
                   if preset is PlatePreset.STAR3 else motor_screw_csinks)
    return (center_bore,)


@app.cell
def _(center_bore, p, preset):
    # ---- feature: radial-pilots (subtract, profile=geometry) ----
    # 径向自攻导孔（纯圆柱）：沿 +Y 自截短内端 pilot_inner_r 越出板外圆 1，绕 X rotate 到各 radial_angles
    _t0 = pilot_inner_r(p, preset)
    _one = scad.make_cylinder_rsolid(radius=p["rad_pilot_d"] / 2.0, height=plate_r(p) + 1.0 - _t0,
                                     bottom_face_center=(radial_x(p), _t0, 0.0), axis=(0.0, 1.0, 0.0))
    _pilots = [scad.rotate_shape(shape=_one, angle=_a, axis=(1.0, 0.0, 0.0)) for _a in radial_angles(p)]
    radial_pilots = scad.cut_rsolid(center_bore, _pilots)
    return (radial_pilots,)


@app.cell
def _(p, preset, radial_pilots):
    # ---- feature: plate-face-names (annotate) ----
    # tag 不跨布尔 / 圆角存活 → 最后一次布尔之后打。
    # STAR3 三段分离臂各 1 顶面（心不在轴线）；CENTER4 中心星 1 面
    _fx = mount_x(p)
    _plate = scad.apply_tag_rselection(scope=radial_pilots, targets=plane_x_selector(p["L"], 1.0, 1), tag=TAG_SEAT)
    _plate = scad.apply_tag_rselection(scope=_plate, targets=plane_x_selector(_fx, -1.0, 1), tag=TAG_BACK)
    plate_face_names = scad.apply_tag_rselection(scope=_plate, tag=TAG_KEY_TOP, targets=plane_x_selector(
        _fx - p["key_h"], -1.0, plate_layout(p, preset)["key_faces"], lateral=preset is PlatePreset.CENTER4))
    plate_face_names.set_metadata("plate_preset", preset.value)
    return (plate_face_names,)


@app.cell
def _(p, plate_face_names, preset):
    # ---- product: part + plate_back / motor_right connectors ----
    # plate_back 与上件 mount2_datum 同帧：固定约束 = 背面贴安装面 2 + 三叉入槽同相
    _part = scad.make_part_rpart(part_id=scad.notebook_id(), body=plate_face_names,
                                 name=f"Motor 2 adapter plate ({preset.value})")
    for _cid, _placement, _name in (
            ("plate_back", mount2_datum_placement(p), "Plate back datum (z out +X, x along key phase)"),
            ("motor_right", motor_right_placement(p), "Motor 2 interface (seat face centre, z = motor axis +X)")):
        _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(
            connector_id=_cid, placement=_placement, name=_name))
    adapter_plate = _part
    return (adapter_plate,)


if __name__ == "__main__":
    app.run()

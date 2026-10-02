# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "flange-plate"
# revision = "1.0.0"
# ///
"""flange_plate: 参数化法兰盘（几何体素路线，无草图层）。

Coordinate convention (REQUIREMENTS.md):
  origin = 法兰轴线 ∩ 盘底平面; +Z 凸台方向.
  受控基准面: 盘底 z=0, 盘顶 z=flange_t, 凸台顶 z=boss_top_z; 回转轴 = Z 轴.

体素路线依据 (FTC geometry tier case 3): 盘/凸台/孔刀全部是完全含于圆柱基本体
的纯工具体 —— 基元即完整设计形状, 无需 profile. 一个 feature 一个 cell, 圆角最后.
"""

import marimo

app = marimo.App()

with app.setup:
    import math

    import simplecadapi as scad
    from simplecadapi import ql

    # 刀具过切量（feature-ordering: 孔刀须越过进出面）
    OVERSHOOT = 5.0


@app.function
def fact_card(slug: str, body: scad.Solid) -> None:
    """小事实卡（incremental grounding）：体积 + 面数，不打印整个实体。"""
    faces = ql.faces().resolve(body)
    print(f"[{slug}] volume={body.get_volume():.3f} faces={len(faces)}")


@app.function
def edge_card(slug: str, selector: ql.ShapeSelector, body: scad.Solid) -> None:
    """选边卡（geometric-validation 选边证据门）：QL resolve 数量 + 逐边长度与中心。"""
    card = selector.resolve(body)
    print(f"[{slug}] selection card: n={len(card)}")
    for edge in card:
        c = edge.get_center()
        print(f"  len={edge.get_length():.3f} center=({c.x:.2f},{c.y:.2f},{c.z:.2f})")


@app.cell
def _():
    # ---- params: disc ----
    FLANGE_OD = scad.var("flange_od", 100.0, comment="法兰盘外径", unit="mm")
    FLANGE_T = scad.var("flange_t", 10.0, comment="法兰盘厚度", unit="mm")
    EDGE_FILLET_R = scad.var("edge_fillet_r", 2.0, comment="法兰外缘上下圆角", unit="mm")
    MIN_EDGE_WEB = scad.var("min_edge_web", 2.0,
                            comment="轮辐宽下限：孔边到外缘最小筋宽（ASSUMED=取 edge_fillet_r）", unit="mm")
    return EDGE_FILLET_R, FLANGE_OD, FLANGE_T, MIN_EDGE_WEB


@app.cell
def _():
    # ---- params: boss and bore ----
    BOSS_OD = scad.var("boss_od", 55.0, comment="中心凸台外径", unit="mm")
    BOSS_TOP_Z = scad.var("boss_top_z", 30.0, comment="凸台顶面到盘底距离", unit="mm")
    BORE_D = scad.var("bore_d", 30.0, comment="中心通孔直径", unit="mm")
    BOSS_FILLET_R = scad.var("boss_fillet_r", 3.0, comment="凸台根部圆角", unit="mm")
    return BORE_D, BOSS_FILLET_R, BOSS_OD, BOSS_TOP_Z


@app.cell
def _():
    # ---- params: bolt pattern ----
    BOLT_D = scad.var("bolt_d", 11.0, comment="螺栓通孔直径", unit="mm")
    BOLT_PCD = scad.var("bolt_pcd", 84.5,
                        comment="螺栓孔分布圆直径 PCD；USER 第 2 轮 78→88 被 G2a 拒（web 0.5<2）；"
                                "85 时 web==R_edge 精确相切（G2b 禁止，实证孔壁被圆角吞并），"
                                "按 0.5mm 网格取严格可行最大值 84.5", unit="mm")
    BOLT_COUNT = scad.var("bolt_count", 8, comment="螺栓孔数（均布，首孔 +X/0°）；USER 第 2 轮 6→8")
    return BOLT_COUNT, BOLT_D, BOLT_PCD


@app.cell
def _(
    BOLT_D,
    BOLT_PCD,
    BORE_D,
    BOSS_FILLET_R,
    BOSS_OD,
    BOSS_TOP_Z,
    EDGE_FILLET_R,
    FLANGE_OD,
    FLANGE_T,
    MIN_EDGE_WEB,
):
    # ---- guard: parameter feasibility (REQUIREMENTS.md V3) ----
    # 不可行参数显式失败，绝不静默；verify/s3_guard_evidence.py 用 overrides 逐条触发。
    _od, _t = float(FLANGE_OD), float(FLANGE_T)
    _boss_od, _top, _bore = float(BOSS_OD), float(BOSS_TOP_Z), float(BORE_D)
    _bolt_d, _pcd = float(BOLT_D), float(BOLT_PCD)
    _r_root, _r_edge, _min_web = float(BOSS_FILLET_R), float(EDGE_FILLET_R), float(MIN_EDGE_WEB)
    # G1 中心孔 < 凸台（壁厚须同时扛住根部圆角）
    _wall = (_boss_od - _bore) / 2.0
    assert _bore < _boss_od, f"G1 中心孔 {_bore} 不小于凸台外径 {_boss_od}"
    assert _wall > _r_root, f"G1 凸台环形壁厚 {_wall:.3f} 必须大于根部圆角 {_r_root}"
    # G2 螺栓孔到外缘轮辐宽（两句：宽度下限 + 拓扑非相切）
    _web = _od / 2.0 - _pcd / 2.0 - _bolt_d / 2.0
    assert _web >= _min_web, (
        f"G2a 轮辐宽不足: web = {_od}/2 - {_pcd}/2 - {_bolt_d}/2 "
        f"= {_web:.3f} < min_edge_web = {_min_web}")
    assert _web > _r_edge, (
        f"G2b 孔缘与外缘圆角相切: web = {_web:.3f} 不大于 edge_fillet_r = {_r_edge}；"
        "web==R_edge 时孔口圆与圆角切圆内切，边圆角会吞并相切孔壁（2026-09-05 实证: "
        "8 孔 PCD 85 → 0° 孔壁消失、体积反常 +950），须严格大于")
    # G3 螺栓孔与凸台根部圆角不干涉
    _gap = _pcd / 2.0 - _bolt_d / 2.0 - _boss_od / 2.0 - _r_root
    assert _gap > 0.0, f"G3 螺栓孔内缘侵入根部圆角区: PCD/2 - d/2 - boss_od/2 - R = {_gap:.3f} <= 0"
    # G4 根部圆角不超凸台高出盘面的高度
    _boss_h = _top - _t
    assert _r_root <= _boss_h, f"G4 根部圆角 {_r_root} 超过凸台高出盘面高度 {_boss_h:.3f}"
    return


@app.cell
def _(FLANGE_OD, FLANGE_T):
    # ---- feature: flange-disc (build) ----
    flange_disc = scad.make_cylinder_rsolid(
        radius=FLANGE_OD / 2.0, height=FLANGE_T,
        bottom_face_center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0))
    fact_card("flange-disc", flange_disc)
    return (flange_disc,)


@app.cell
def _(BOSS_OD, BOSS_TOP_Z, FLANGE_T, flange_disc):
    # ---- feature: center-boss (add) ----
    _boss = scad.make_cylinder_rsolid(
        radius=BOSS_OD / 2.0, height=BOSS_TOP_Z - FLANGE_T,
        bottom_face_center=(0.0, 0.0, FLANGE_T), axis=(0.0, 0.0, 1.0))
    center_boss = scad.union_rsolid(flange_disc, _boss)
    fact_card("center-boss", center_boss)
    return (center_boss,)


@app.cell
def _(BORE_D, BOSS_TOP_Z, center_boss):
    # ---- feature: center-bore (subtract) ----
    _bore_tool = scad.make_cylinder_rsolid(
        radius=BORE_D / 2.0, height=BOSS_TOP_Z + 2.0 * OVERSHOOT,
        bottom_face_center=(0.0, 0.0, -OVERSHOOT), axis=(0.0, 0.0, 1.0))
    center_bore = scad.cut_rsolid(center_boss, _bore_tool)
    fact_card("center-bore", center_bore)
    return (center_bore,)


@app.cell
def _(BOLT_COUNT, BOLT_D, BOLT_PCD, FLANGE_T, center_bore):
    # ---- feature: bolt-holes (subtract) ----
    # 原型孔刀 @(+X, PCD/2) + radial_pattern（首孔 +X，均布 360°，含原型）
    _proto = scad.make_cylinder_rsolid(
        radius=BOLT_D / 2.0, height=FLANGE_T + 2.0 * OVERSHOOT,
        bottom_face_center=(BOLT_PCD / 2.0, 0.0, -OVERSHOOT), axis=(0.0, 0.0, 1.0))
    _tools = scad.radial_pattern_rsolidlist(
        shape=_proto, center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
        count=int(float(BOLT_COUNT)), total_rotation_angle=360.0)
    bolt_holes = scad.cut_rsolid(center_bore, _tools)
    fact_card("bolt-holes", bolt_holes)
    return (bolt_holes,)


@app.cell
def _(BOSS_FILLET_R, BOSS_OD, FLANGE_T, bolt_holes):
    # ---- feature: boss-root-fillet (modify) ----
    # 选边卡先行（REQUIREMENTS 要求 2）：数量 + 边长，exactly(1) 承重，选边失败显式抛错
    _t, _boss_od = float(FLANGE_T), float(BOSS_OD)
    _root = ql.edges().where(ql.and_(
        ql.prop("geom.type", "==", "CIRCLE"),
        ql.prop("geom.center.z", ">=", _t - 0.1),
        ql.prop("geom.center.z", "<=", _t + 0.1),
        ql.prop("geom.length", ">=", math.pi * _boss_od - 0.5),
        ql.prop("geom.length", "<=", math.pi * _boss_od + 0.5),
    )).exactly(1)
    edge_card("boss-root-fillet", _root, bolt_holes)
    boss_root_fillet = scad.fillet_rsolid(
        solid=bolt_holes, edges=_root, radius=BOSS_FILLET_R,
        generated_faces_tag="fillet.boss_root")
    fact_card("boss-root-fillet", boss_root_fillet)
    return (boss_root_fillet,)


@app.cell
def _(EDGE_FILLET_R, FLANGE_OD, FLANGE_T, boss_root_fillet):
    # ---- feature: flange-edge-fillets (modify) ----
    _t, _od = float(FLANGE_T), float(FLANGE_OD)
    _rims = ql.edges().where(ql.and_(
        ql.prop("geom.type", "==", "CIRCLE"),
        ql.prop("geom.length", ">=", math.pi * _od - 0.5),
        ql.prop("geom.length", "<=", math.pi * _od + 0.5),
        ql.or_(
            ql.and_(ql.prop("geom.center.z", ">=", -0.1),
                    ql.prop("geom.center.z", "<=", 0.1)),
            ql.and_(ql.prop("geom.center.z", ">=", _t - 0.1),
                    ql.prop("geom.center.z", "<=", _t + 0.1)),
        ),
    )).exactly(2)
    edge_card("flange-edge-fillets", _rims, boss_root_fillet)
    flange_edge_fillets = scad.fillet_rsolid(
        solid=boss_root_fillet, edges=_rims, radius=EDGE_FILLET_R,
        generated_faces_tag="fillet.flange_edge")
    fact_card("flange-edge-fillets", flange_edge_fillets)
    return (flange_edge_fillets,)


@app.cell
def _(flange_edge_fillets):
    flange_plate = scad.Part(part_id="flange-plate", body=flange_edge_fillets,
                             name="Eight-bolt flange plate")
    return (flange_plate,)


if __name__ == "__main__":
    app.run()

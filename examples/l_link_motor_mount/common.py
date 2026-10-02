"""l_link_motor_mount: 三件共用的几何（L 杆扫掠、"l" 剖分刀具、共享草图轮廓、装配基准）。

纯函数，参数 ``p`` 为 ``dimensions.params()`` 的字典。上件 cut / 壳体 intersect 共用
``split_region_tool``（一刀两件，接口天然贴合）；上件凹槽 / 转接板凸起共用 ``key_star_face``；
壳体走线口 / 上件走线窗共用 ``rounded_rect_face``。
"""
from __future__ import annotations

import math

import simplecadapi as scad

from dimensions import SPLIT_OVERSHOOT, back_y, mount_x, split_xs, x_end


def l_rod_path(p: dict) -> scad.Wire:
    """L 路径约束草图（3 实体开放链：臂 → 拐角弧 → 直段）→ dof=0 提升为扫掠路径。

    切线连续由 2 条端点 tangent 约束承担；q 只改 rod_d 时路径不变（壳体内偏移扫掠复用）。
    """
    d, r_c, xe = p["D"], p["r_corner"], x_end(p)
    sketch = scad.make_sketch_rsketch(name="l_path", plane="XY")
    seeds = {"arm_top": (0.0, d), "arm_foot": (0.0, r_c), "corner_c": (r_c, r_c),
             "run_start": (r_c, 0.0), "run_end": (xe, 0.0)}
    for pid, (x, y) in seeds.items():
        sketch = scad.add_point_rsketch(sketch=sketch, point_id=pid, x=x, y=y)
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="arm", start="arm_top", end="arm_foot")
    sketch = scad.add_arc_rsketch(sketch=sketch, entity_id="corner", start="arm_foot",
                                  end="run_start", center="corner_c")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="run", start="run_start", end="run_end")
    sketch = scad.constrain_fix_rsketch(sketch=sketch, target="run_start")
    sketch = scad.constrain_vertical_rsketch(sketch=sketch, line="arm")
    sketch = scad.constrain_horizontal_rsketch(sketch=sketch, line="run")
    sketch = scad.constrain_tangent_rsketch(sketch=sketch, a="arm", b="corner", at_b="start")
    sketch = scad.constrain_tangent_rsketch(sketch=sketch, a="corner", b="run", at_a="end")
    sketch = scad.constrain_radius_rsketch(sketch=sketch, circle="corner", value=r_c)
    sketch = scad.constrain_distance_x_rsketch(sketch=sketch, a="arm_top", b="run_end", value=xe)
    sketch = scad.constrain_distance_y_rsketch(sketch=sketch, a="run_start", b="arm_top", value=d)
    return scad.make_wire_from_sketch_rwire(sketch=sketch, require_fully_constrained=True)


def sweep_l_rod(p: dict, rod_d: float, skin_tag: str | None = None) -> scad.Solid:
    """圆截面（⌀rod_d，起于左臂端 y=D）沿 L 路径扫掠；skin_tag 给侧面（外皮）打 tag（壳体选外环用）。"""
    profile = scad.make_circle_rface(center=(0.0, p["D"], 0.0), radius=rod_d / 2.0,
                                     normal=(0.0, -1.0, 0.0))
    kw = {"side_faces_tag": skin_tag} if skin_tag else {}
    return scad.sweep_rsolid(profile=profile, path=l_rod_path(p), **kw)


def split_region_tool(p: dict) -> scad.Solid:
    """"l" 剖分壳区刀具（上件 cut / 壳体 intersect 共用，一刀两件接口天然贴合）。

    XY 闭合约束草图（dof=0）：水平段 y=back_y 自杆后方至 x_a → 相切弧（向 −Y 弯，R=x_b−x_a）
    → 竖直段 x=x_b 至杆下方 → 底边 → 后边；拉伸 +Z 后平移一次居中（两侧越过杆面 overshoot）。
    """
    r, by = p["rod_d"] / 2.0, back_y(p)
    xa, xb = split_xs(p)
    rs, lo = xb - xa, -r - SPLIT_OVERSHOOT
    sketch = scad.make_sketch_rsketch(name="l_split_region", plane="XY")
    seeds = {"back_top": (lo, by), "arc_a": (xa, by), "arc_c": (xa, by - rs),
             "arc_b": (xb, by - rs), "drop_foot": (xb, lo), "back_foot": (lo, lo)}
    for pid, (x, y) in seeds.items():
        sketch = scad.add_point_rsketch(sketch=sketch, point_id=pid, x=x, y=y)
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="flat", start="back_top", end="arc_a")
    # 弧 CCW 自 start 到 end：arc_b（弧底右端）→ arc_a（水平段止点）
    sketch = scad.add_arc_rsketch(sketch=sketch, entity_id="bend", start="arc_b", end="arc_a",
                                  center="arc_c")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="drop", start="arc_b", end="drop_foot")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="floor", start="drop_foot", end="back_foot")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="back", start="back_foot", end="back_top")
    sketch = scad.constrain_fix_rsketch(sketch=sketch, target="arc_a")
    sketch = scad.constrain_horizontal_rsketch(sketch=sketch, line="flat")
    sketch = scad.constrain_vertical_rsketch(sketch=sketch, line="drop")
    sketch = scad.constrain_horizontal_rsketch(sketch=sketch, line="floor")
    sketch = scad.constrain_vertical_rsketch(sketch=sketch, line="back")
    sketch = scad.constrain_radius_rsketch(sketch=sketch, circle="bend", value=rs)
    sketch = scad.constrain_tangent_rsketch(sketch=sketch, a="flat", b="bend", at_b="end")
    sketch = scad.constrain_tangent_rsketch(sketch=sketch, a="bend", b="drop", at_a="start")
    sketch = scad.constrain_distance_x_rsketch(sketch=sketch, a="back_top", b="arc_a", value=xa - lo)
    sketch = scad.constrain_distance_y_rsketch(sketch=sketch, a="back_foot", b="arc_a", value=by - lo)
    face = scad.make_face_from_sketch_rface(sketch=sketch, require_fully_constrained=True)
    depth = r + SPLIT_OVERSHOOT
    tool = scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=2.0 * depth)
    return scad.translate_shape(shape=tool, vector=(0.0, 0.0, -depth))


def rounded_rect_face(name: str, w: float, h: float, rr: float) -> scad.Face:
    """XY 圆角矩形约束草图（4 线 + 4 相切弧、等半径，dof=0），中心在原点、宽 w（x）高 h（y）。

    共享轮廓：壳体走线口 / 电机槽走线窗（调用方 extrude +Z → rotate → translate 一次）。
    """
    x0, x1, y0, y1 = -w / 2.0, w / 2.0, -h / 2.0, h / 2.0
    sketch = scad.make_sketch_rsketch(name=name, plane="XY")
    seeds = {"b0": (x0 + rr, y0), "b1": (x1 - rr, y0), "r0": (x1, y0 + rr), "r1": (x1, y1 - rr),
             "t0": (x1 - rr, y1), "t1": (x0 + rr, y1), "l0": (x0, y1 - rr), "l1": (x0, y0 + rr),
             "c_br": (x1 - rr, y0 + rr), "c_tr": (x1 - rr, y1 - rr), "c_tl": (x0 + rr, y1 - rr),
             "c_bl": (x0 + rr, y0 + rr)}
    for pid, (x, y) in seeds.items():
        sketch = scad.add_point_rsketch(sketch=sketch, point_id=pid, x=x, y=y)
    # CCW 环：弧均自 start 逆时针到 end
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="bottom", start="b0", end="b1")
    sketch = scad.add_arc_rsketch(sketch=sketch, entity_id="br", start="b1", end="r0", center="c_br")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="right", start="r0", end="r1")
    sketch = scad.add_arc_rsketch(sketch=sketch, entity_id="tr", start="r1", end="t0", center="c_tr")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="top", start="t0", end="t1")
    sketch = scad.add_arc_rsketch(sketch=sketch, entity_id="tl", start="t1", end="l0", center="c_tl")
    sketch = scad.add_line_rsketch(sketch=sketch, entity_id="left", start="l0", end="l1")
    sketch = scad.add_arc_rsketch(sketch=sketch, entity_id="bl", start="l1", end="b0", center="c_bl")
    for line in ("bottom", "top"):
        sketch = scad.constrain_horizontal_rsketch(sketch=sketch, line=line)
    for line in ("right", "left"):
        sketch = scad.constrain_vertical_rsketch(sketch=sketch, line=line)
    for line, arc in (("bottom", "br"), ("right", "tr"), ("top", "tl"), ("left", "bl")):
        sketch = scad.constrain_tangent_rsketch(sketch=sketch, a=line, b=arc, at_b="start")
    for arc, line in (("br", "right"), ("tr", "top"), ("tl", "left"), ("bl", "bottom")):
        sketch = scad.constrain_tangent_rsketch(sketch=sketch, a=arc, b=line, at_a="end")
    sketch = scad.constrain_radius_rsketch(sketch=sketch, circle="br", value=rr)
    for arc in ("tr", "tl", "bl"):
        sketch = scad.constrain_equal_radius_rsketch(sketch=sketch, a="br", b=arc)
    sketch = scad.constrain_fix_rsketch(sketch=sketch, target="c_bl")
    sketch = scad.constrain_distance_x_rsketch(sketch=sketch, a="l0", b="r0", value=w)
    sketch = scad.constrain_distance_y_rsketch(sketch=sketch, a="b0", b="t0", value=h)
    return scad.make_face_from_sketch_rface(sketch=sketch, require_fully_constrained=True)


def key_star_face(name: str, w: float, arm: float, phase: float) -> scad.Face:
    """三叉（奔驰标）约束草图：3 条自中心起的半带（宽 w、长 arm）@ phase + k·120° 之并 = 9 顶点闭合多边形。

    草图 (u, v) = (−z, y)：调用方 extrude +Z → rotate +90° 绕 Y（+Z→+X，u→−z）→ translate 到 x 位；
    内凹顶点在两臂平分线上 (w/2)/sin60°。上件凹槽 / 转接板凸起共享。顶点由参数算出后 fix（dof=0）。
    """
    hw, c = w / 2.0, w / 2.0 / math.sin(math.radians(60.0))
    pts = []
    for k in range(3):
        th = math.radians(phase + 120.0 * k)
        u, n = (math.cos(th), math.sin(th)), (-math.sin(th), math.cos(th))  # (y, z) 臂向 / 左法向
        pts += [(arm * u[0] - hw * n[0], arm * u[1] - hw * n[1]), (arm * u[0] + hw * n[0], arm * u[1] + hw * n[1])]
        pts.append((c * math.cos(th + math.radians(60.0)), c * math.sin(th + math.radians(60.0))))
    sketch = scad.make_sketch_rsketch(name=name, plane="XY")
    ids = [f"v{i}" for i in range(len(pts))]
    for pid, (y, z) in zip(ids, pts):
        sketch = scad.add_point_rsketch(sketch=sketch, point_id=pid, x=-z, y=y)
    for i, pid in enumerate(ids):
        sketch = scad.add_line_rsketch(sketch=sketch, entity_id=f"e{i}", start=pid, end=ids[(i + 1) % len(ids)])
    for pid in ids:
        sketch = scad.constrain_fix_rsketch(sketch=sketch, target=pid)
    return scad.make_face_from_sketch_rface(sketch=sketch, require_fully_constrained=True)


# ---- assembly datums (placement connectors; parts are modeled in install position -> identity placements) ----
def split_datum_placement(p: dict) -> scad.Placement:
    """剖分水平接口面 y=back_y：z 出 −Y（上件 split_datum = 壳体 shell_rim）。"""
    return scad.make_placement_rplacement(
        origin=(0.0, back_y(p), 0.0), x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 0.0, 1.0))


def mount2_datum_placement(p: dict) -> scad.Placement:
    """安装面 2 x=L−plate_t：z 出 +X，x 轴 = key_phase 方向（YZ 面内自 +Y 量向 +Z）→ 固定约束同时锁定三叉相位。"""
    a = math.radians(p["key_phase"])
    return scad.make_placement_rplacement(
        origin=(mount_x(p), 0.0, 0.0), x_axis=(0.0, math.cos(a), math.sin(a)), y_axis=(0.0, -math.sin(a), math.cos(a)))


def motor_left_placement(p: dict) -> scad.Placement:
    """左电机接口：左安装面心 (0, d_motor/2, 0)，z 出 +Y（电机轴），x 轴指向电机2。"""
    return scad.make_placement_rplacement(
        origin=(0.0, p["d_motor"] / 2.0, 0.0), x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 0.0, -1.0))


def motor_right_placement(p: dict) -> scad.Placement:
    """电机2 接口：板外表面心 (L,0,0)（tag feature.motor_seat_right），z 出 +X（电机轴），x 轴 = key_phase 方向。"""
    mount = mount2_datum_placement(p)
    return scad.make_placement_rplacement(origin=(p["L"], 0.0, 0.0), x_axis=mount.x_axis, y_axis=mount.y_axis)

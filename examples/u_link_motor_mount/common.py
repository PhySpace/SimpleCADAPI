"""u_link_motor_mount: 上件与下壳共用的几何工具。

两件都从同一根 U 形扫掠杆切出，也共用剖分大盒与圆角矩形棱柱刀具。
这些函数只做几何，在调用它的 notebook cell 里记录特征。
"""

from __future__ import annotations

import math

import simplecadapi as scad

from dimensions import ULinkDimensions


def u_path_wire(dims: ULinkDimensions) -> scad.Wire:
    """U 路径约束草图（5 实体开放链）→ 求解后提升为扫掠路径 wire。

    切线连续由 4 条端点 tangent 约束承担；dof=0 全约束提升（sweep 路径本就
    开放，闭合性由消费端契约管）。路径与 rod_d 无关，内偏移扫掠复用它。
    """
    l, d, r_c = dims.L, dims.D, dims.r_corner
    xl, xr = -l / 2.0, l / 2.0
    sketch = scad.make_sketch_rsketch(name="u_path", plane="XY")
    seeds = {
        "lt": (xl, d), "l1": (xl, r_c), "cl": (xl + r_c, r_c),
        "b1": (xl + r_c, 0.0), "b2": (xr - r_c, 0.0), "cr": (xr - r_c, r_c),
        "r1": (xr, r_c), "rt": (xr, d),
    }
    for pid, (x, y) in seeds.items():
        sketch = scad.add_point_rsketch(sketch, pid, x, y)
    sketch = scad.add_line_rsketch(sketch, "arm_l", "lt", "l1")
    sketch = scad.add_arc_rsketch(sketch, "corner_l", "l1", "b1", "cl")
    sketch = scad.add_line_rsketch(sketch, "bottom", "b1", "b2")
    sketch = scad.add_arc_rsketch(sketch, "corner_r", "b2", "r1", "cr")
    sketch = scad.add_line_rsketch(sketch, "arm_r", "r1", "rt")
    sketch = scad.constrain_fix_rsketch(sketch, "b1")
    sketch = scad.constrain_vertical_rsketch(sketch, "arm_l")
    sketch = scad.constrain_vertical_rsketch(sketch, "arm_r")
    sketch = scad.constrain_horizontal_rsketch(sketch, "bottom")
    sketch = scad.constrain_tangent_rsketch(sketch, "arm_l", "corner_l", at_b="start")
    sketch = scad.constrain_tangent_rsketch(sketch, "corner_l", "bottom", at_a="end")
    sketch = scad.constrain_tangent_rsketch(sketch, "bottom", "corner_r", at_b="start")
    sketch = scad.constrain_tangent_rsketch(sketch, "corner_r", "arm_r", at_a="end")
    sketch = scad.constrain_equal_radius_rsketch(sketch, "corner_l", "corner_r")
    sketch = scad.constrain_radius_rsketch(sketch, "corner_l", r_c)
    sketch = scad.constrain_distance_x_rsketch(sketch, "lt", "rt", l)
    sketch = scad.constrain_distance_y_rsketch(sketch, "b1", "lt", d)
    sketch = scad.constrain_distance_y_rsketch(sketch, "b1", "rt", d)
    return scad.make_wire_from_sketch_rwire(sketch=sketch, require_fully_constrained=True)


def _swept_circle(dims: ULinkDimensions, radius: float) -> scad.Solid:
    """半径 *radius* 的圆截面沿 U 路径扫掠（端盖平面在 y=D）。"""
    profile = scad.make_circle_rface(
        center=(-dims.L / 2.0, dims.D, 0.0), radius=radius, normal=(0.0, -1.0, 0.0))
    return scad.sweep_rsolid(profile=profile, path=u_path_wire(dims))


def sweep_u_rod(dims: ULinkDimensions) -> scad.Solid:
    """U 形杆坯：圆截面 rod_d 沿 U 路径扫掠（开口 +Y）。"""
    rod = _swept_circle(dims, dims.r)
    scad.apply_tag(shape=rod, tag="role.u_rod")
    return rod


def sweep_eroded_rod(dims: ULinkDimensions) -> scad.Solid:
    """轮廓内偏移体：半径 r-wall_t 沿同一 U 路径扫掠。

    圆截面扫掠的内偏移 = 缩径扫掠，直段/圆弧段均精确——"贴合背板轮廓"的实现。
    """
    return _swept_circle(dims, dims.r - dims.wall_t)


def big_box(dims: ULinkDimensions, y_top: float, y_bot: float) -> scad.Solid:
    """y∈[y_bot, y_top] 的大包围盒（剖分/切带刀具）。

    纪律（s10 探针教训）：cut 盒在非剖分侧必须越界出杆料——盒顶停在臂盖区
    内部会触发内核布尔垃圾结果。
    """
    overshoot = 10.0
    return scad.make_box_rsolid(
        width=dims.L + 4.0 * dims.r + 2.0 * overshoot, height=y_top - y_bot,
        depth=2.0 * (dims.r + overshoot),
        bottom_face_center=(0.0, (y_top + y_bot) / 2.0, -(dims.r + overshoot)))


def rounded_rect_prism(x_lo: float, x_hi: float, y_lo: float, y_hi: float,
                       z_lo: float, z_hi: float, rr: float) -> scad.Solid:
    """y-z 平面圆角矩形沿 +x 拉伸（shell 走线口 / 电机槽走线窗共用刀具）。

    注: wire 画在 x_lo 处、extrude distance=x_hi-x_lo——**不要**再平移（S12b 事故：
    extrude 后再 translate(+x_lo) 双重平移使工具落空且 cut 静默跳过）。
    """
    c45 = math.cos(math.pi / 4)

    def arc(cy: float, cz: float, sy: float, sz: float) -> scad.Edge:
        return scad.make_three_point_arc_redge(
            start=(x_lo, cy + sy * rr, cz),
            middle=(x_lo, cy + sy * rr * c45, cz + sz * rr * c45),
            end=(x_lo, cy, cz + sz * rr))

    y0r, y1r, z0r, z1r = y_lo + rr, y_hi - rr, z_lo + rr, z_hi - rr
    wire = scad.make_wire_from_edges_rwire(edges=[
        scad.make_segment_redge(start=(x_lo, y_lo, z0r), end=(x_lo, y_lo, z1r)),
        arc(y0r, z1r, -1, 1),
        scad.make_segment_redge(start=(x_lo, y0r, z_hi), end=(x_lo, y1r, z_hi)),
        arc(y1r, z1r, 1, 1),
        scad.make_segment_redge(start=(x_lo, y_hi, z1r), end=(x_lo, y_hi, z0r)),
        arc(y1r, z0r, 1, -1),
        scad.make_segment_redge(start=(x_lo, y1r, z_lo), end=(x_lo, y0r, z_lo)),
        arc(y0r, z0r, -1, -1),
    ])
    face = scad.make_face_from_wire_rface(wire=wire)
    return scad.extrude_rsolid(profile=face, direction=(1.0, 0.0, 0.0), distance=x_hi - x_lo)

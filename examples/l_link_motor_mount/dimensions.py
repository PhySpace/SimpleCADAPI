"""l_link_motor_mount: 共享尺寸、派生基准与参数守卫链。

上件（``l_link.py``）、壳体（``shell.py``）与电机2 转接板（``adapter_plate.py``）
建模于同一坐标系、装配位（placement=identity），共用一套尺寸：放在这里，三个
notebook 都在 params cell 里取同一个 ``params()``，装配时三件天然一致。

Coordinate convention (REQUIREMENTS.md):
  origin = 左电机轴线 ∩ 底部直段轴线; +X 沿连杆指向电机2; +Y 向上（左槽开口）; +Z 横向.
  受控基准: 左安装面 y=d_motor/2; 电机2 落座面 x=L; 左臂端面 y=D;
  右端面 x=x_end=L+(D-d_motor/2). 关于 XY 平面（z 镜像）对称.

守卫链逐件累加：``check_body`` ⊂ ``check_shell`` ⊂ ``check_plate``（转接板链对两个
preset 都检查——上件凹槽与 preset 无关）。
"""
from __future__ import annotations

import math
from enum import Enum

import simplecadapi as scad

# ---- params: upper body ----
L = scad.var("L", 80.0, comment="左电机轴线 → 电机2 落座面（转接板外表面）X 距离", unit="mm")
D = scad.var("D", 20.0, comment="左臂端面高度（自 y=0）", unit="mm")
ROD_D = scad.var("rod_d", 30.0, comment="圆杆直径", unit="mm")
D_MOTOR = scad.var("d_motor", 19.0, comment="电机深度（左槽底 y=d_motor/2；槽深 D-d_motor/2 两电机同规格）", unit="mm")
R_CORNER = scad.var("r_corner", 17.0, comment="拐角中心线圆弧半径（须∈(rod_d/2, D)）", unit="mm")
THICKNESS = scad.var("thickness", 6.0, comment="电机槽壁余量（槽 ⌀rod_d-thickness，端面槽壁 thickness/2）", unit="mm")
PLATE_T = scad.var("plate_t", 5.0, comment="电机2 转接板厚（用户 ≥5）；安装面 2 自落座面 x=L 下沉 plate_t", unit="mm")
WALL_T = scad.var("wall_t", 2.0, comment="标准壁厚（壳体壁 / 左槽底到剖分面 / 左槽最小侧壁下限）", unit="mm")
BACK_CUT_FRAC = scad.var("back_cut_frac", 0.75, comment="剖分水平段高度 back_y = r(2·frac−1)（沿用 U-link）", unit="1")
SPLIT_ARC_FRAC = scad.var("split_arc_frac", 0.60, comment="\"l\" 剖分：水平段止于 x_a = frac·L，起相切弧", unit="1")
SPLIT_END_FRAC = scad.var("split_end_frac", 0.75, comment="\"l\" 剖分：竖直段 x_b = frac·L（弧半径 x_b−x_a）", unit="1")
BOSS_D = scad.var("boss_d", 5.0, comment="长 boss 直径（自剖分面向下悬伸到壳体 pad 顶）", unit="mm")
BOSS_HOLE_D = scad.var("boss_hole_d", 2.7, comment="boss 自攻盲孔直径（M3 自攻）", unit="mm")
BOSS_HOLE_DEPTH = scad.var("boss_hole_depth", 6.0, comment="boss 盲孔深（自 boss 底向 +Y；M3×8 入 boss ≈5.3）", unit="mm")
BOSS_X1 = scad.var("boss_x1", 25.0, comment="boss 1 x（直段腔内，筋距拐角 ≥2）", unit="mm")
BOSS_X2 = scad.var("boss_x2", 40.0, comment="boss 2 x（筋尖距剖分弧起点 x_a ≥2）", unit="mm")
RIB_T = scad.var("rib_t", 1.2, comment="boss 根部十字筋厚", unit="mm")
RIB_LEN = scad.var("rib_len", 3.0, comment="十字筋水平边（自 boss 面沿剖分面外伸）", unit="mm")
GUSSET_H = scad.var("gusset_h", 5.0, comment="十字筋高（自剖分面沿 boss 向下）", unit="mm")
GUSSET_CHAMFER = scad.var("gusset_chamfer", 0.3, comment="十字筋斜边倒角（防割手）", unit="mm")
PAD_T = scad.var("pad_t", 1.0, comment="壳体 pad 加厚（boss 长 = back_y − pad_top，上件/壳体共用）", unit="mm")
FILLET_R = scad.var("fillet_r", 1.2, comment="上件两端盖 rim 圆角（外环 r + 槽口 rp；须 < thickness/4）", unit="mm")
CABLE_W_OFF = scad.var("cable_w_off", 3.0, comment="走线窗底边距各自电机落座面（左 y=d_motor/2，右 x=L 板面）", unit="mm")
CABLE_W_H = scad.var("cable_w_h", 5.0, comment="走线窗高（沿电机轴）", unit="mm")
CABLE_W_W = scad.var("cable_w_w", 10.0, comment="走线窗宽（切向）", unit="mm")
CABLE_W_RR = scad.var("cable_w_rr", 1.2, comment="走线窗圆角", unit="mm")
CABLE_W_PHASE = scad.var("cable_w_phase", 45.0, comment="走线窗相位（绕各自电机轴 +Y / +X 右手转，自 +Z 量起；4 窗 phase+k·90）", unit="deg")
KEY_W = scad.var("key_w", 2.5, comment="三叉凸起臂宽（转接板）；凹槽宽 key_w+2·key_gap", unit="mm")
KEY_GAP = scad.var("key_gap", 0.1, comment="三叉凹槽单边间隙（宽向与臂端）", unit="mm")
KEY_PHASE = scad.var("key_phase", 0.0, comment="三叉 / 径向螺丝相位（YZ 面内自 +Y 量向 +Z）", unit="deg")
KEY_R_OUT = scad.var("key_r_out", 10.9, comment="三叉凸起臂外端半径（凹槽臂长 key_r_out+key_gap）", unit="mm")
GROOVE_D = scad.var("groove_d", 2.2, comment="三叉凹槽深（自安装面 2 向 −X，用户给定）", unit="mm")
RAD_SCREW_N = scad.var("rad_screw_n", 3, comment="径向 M2 沉头自攻数（等分，与三叉臂同相）", unit="1")
RAD_CLEAR_D = scad.var("rad_clear_d", 2.2, comment="径向螺丝套筒过孔", unit="mm")
RAD_CSINK_D = scad.var("rad_csink_d", 4.0, comment="径向螺丝 90° 沉头口径", unit="mm")
RAD_SPOT_D = scad.var("rad_spot_d", 4.2, comment="径向沉头外侧锪平直径（≥ 沉头口 + 0.2）", unit="mm")
RAD_SPOT_DEPTH = scad.var("rad_spot_depth", 0.25, comment="锪平深（自 r=rod_d/2；≥ 曲面矢高 + 0.1）", unit="mm")

# ---- params: shell ----
NOTCH_W = scad.var("notch_w", 9.0, comment="走线口宽（z 向，U-link S11 值）", unit="mm")
NOTCH_H = scad.var("notch_h", 7.0, comment="走线口高（y 向）", unit="mm")
NOTCH_SILL = scad.var("notch_sill", 0.5, comment="走线口顶距剖分面台阶（rim 不被劈开）", unit="mm")
NOTCH_RR = scad.var("notch_rr", 1.5, comment="走线口角圆角半径（rounded-rect 源型，防割手）", unit="mm")
PAD_D = scad.var("pad_d", 8.0, comment="壳底内侧 pad 直径（boss 底端落座；= boss_d+3）", unit="mm")
SHELL_HOLE_D = scad.var("shell_hole_d", 2.7, comment="壳底螺丝通孔直径", unit="mm")
CSINK_D = scad.var("csink_d", 5.4, comment="90° 沉头口直径（锥深 = (csink_d−shell_hole_d)/2 派生）", unit="mm")
SPOT_D = scad.var("spot_d", 5.9, comment="壳底外侧锪平直径（沉头口外留平台环）", unit="mm")
SAFE_FILLET_R = scad.var("safe_fillet_r", 0.6, comment="壳体两走线口（左端口 + 同轴孔）外环圆角（防割线；须 < notch_rr、≤ wall_t−0.5）", unit="mm")
SPOT_DEPTH = scad.var("spot_depth", 0.4, comment="锪平深（自管底 y=−r；须 ≥ 曲面矢高 + 0.1，否则锪平侧壁成 0.007 薄片）", unit="mm")

# ---- params: adapter plate ----
PLATE_GAP = scad.var("plate_gap", 0.1, comment="转接板外圆到槽壁径向间隙（板 ⌀ = 2·rp − 2·gap）", unit="mm")
M2_HOLE_D = scad.var("m2_hole_d", 2.7, comment="电机2 螺丝过孔（M2.5）", unit="mm")
M2_PCD = scad.var("m2_pcd", 16.0, comment="电机2 螺孔分布圆直径", unit="mm")
M2_CSINK_D = scad.var("m2_csink_d", 5.1, comment="电机螺丝 90° 沉头口径（自板背面）", unit="mm")
M2_HEAD_DK = scad.var("m2_head_dk", 4.7, comment="电机螺丝沉头头径（头顶沉入 (csink−dk)/2）", unit="mm")
M2_CENTER_D = scad.var("m2_center_d", 6.0, comment="中心过孔（STAR3；避让电机轴 / 卡簧）", unit="mm")
KEY_H = scad.var("key_h", 2.0, comment="三叉凸起高（用户给定；< 凹槽深 groove_d）", unit="mm")
KEY_R_IN = scad.var("key_r_in", 4.2, comment="CENTER4 中心短臂外端半径（沉头口以内）", unit="mm")
MIN_WEB = scad.var("min_web", 0.3, comment="板上特征间最小剩余壁（凸起 / 孔 / 沉头 / 导孔 / 外圆）", unit="mm")
RAD_PILOT_D = scad.var("rad_pilot_d", 1.6, comment="径向 M2 自攻导孔", unit="mm")
RAD_PILOT_DEPTH = scad.var("rad_pilot_depth", 4.0, comment="径向导孔深（自板外圆；每变体按 min_web 截短）", unit="mm")

_ALL_VARS = (
    L, D, ROD_D, D_MOTOR, R_CORNER, THICKNESS, PLATE_T, WALL_T, BACK_CUT_FRAC, SPLIT_ARC_FRAC,
    SPLIT_END_FRAC, BOSS_D, BOSS_HOLE_D, BOSS_HOLE_DEPTH, BOSS_X1, BOSS_X2, RIB_T, RIB_LEN, GUSSET_H,
    GUSSET_CHAMFER, PAD_T, FILLET_R, CABLE_W_OFF, CABLE_W_H, CABLE_W_W, CABLE_W_RR, CABLE_W_PHASE,
    KEY_W, KEY_GAP, KEY_PHASE, KEY_R_OUT, GROOVE_D, RAD_SCREW_N, RAD_CLEAR_D, RAD_CSINK_D, RAD_SPOT_D,
    RAD_SPOT_DEPTH,
    NOTCH_W, NOTCH_H, NOTCH_SILL, NOTCH_RR, PAD_D, SHELL_HOLE_D, CSINK_D, SPOT_D, SAFE_FILLET_R, SPOT_DEPTH,
    PLATE_GAP, M2_HOLE_D, M2_PCD, M2_CSINK_D, M2_HEAD_DK, M2_CENTER_D, KEY_H, KEY_R_IN, MIN_WEB,
    RAD_PILOT_D, RAD_PILOT_DEPTH,
)

# 命名特征面 tag（QL 索引入口）
TAG_MOUNT_LEFT = "feature.motor_mount_floor_left"
TAG_MOUNT_RIGHT = "feature.motor_mount_floor_right"
TAG_SHELL_RIM = "feature.shell_rim_face"  # 剖分水平接口面（贴上件下底面）
TAG_SKIN = "construct.shell_skin"  # 杆外皮（扫掠侧面）：S6 走线口外环 = 口面 ∩ 皮面边界；任何 fillet 后即失效
TAG_SEAT = "feature.motor_seat_right"  # 板外表面 x=L（电机2 落座面）
TAG_BACK = "feature.plate_back_face"  # 板背面 x=L−plate_t（贴安装面 2）
TAG_KEY_TOP = "feature.plate_key_top"  # 凸起顶面 x=L−plate_t−key_h（对凹槽底留 groove_d−key_h）

SPLIT_OVERSHOOT = 10.0  # 剖分刀具越过杆外表面（刀具必须 overshoot）
BOSS_ROOT_OVERSHOOT = 1.0  # boss / 筋顶越过剖分面伸入上件（并集不留缝）
# 左窗贯穿棱柱朝 +X 时沿拐角内弯（弧心 (r_corner, r_corner)）钻进臂身：S10 相位扫描（默认几何）
# |phase mod 90 − 45| ≤ 6° 内弯 torus 保持一整面、偏窗体积 ≤ +5%，≥ 7° 被切成两片 → 取 5°（经验界，留 1°）
CABLE_W_PHASE_TOL = 5.0
CAVITY_OVERSHOOT = 10.0  # 壳体腔区顶越过剖分面 / 刀具越过杆外表面
KEY_HUB_CLEAR = 0.5  # STAR3 三叉臂内端距中心孔（臂段 r ≥ m2_center_d/2 + 0.5）
KEY_ROOT_OVERSHOOT = 0.5  # 凸起伸入板体（并集不留缝）
# 臂端角到板背面外圆圆角的平面环宽：=0 时臂端割断背面平面环（背面 tag 选择器 0 命中，S10 key_r_out 边界）；
# 旧默认 key_r_out 11.2 仅留 0.03 → 取 0.3 并把 key_r_out 默认降到 10.9
KEY_TIP_LAND = 0.3
RAD_SCREW_LENGTHS = (4.0, 5.0, 6.0, 8.0)  # M2 沉头自攻标准长度（选型见 radial_screw_len）


class PlatePreset(Enum):
    """兼容盘面（上件凹槽为完整三叉，两种凸起均为其子集）。"""
    STAR3 = "star3"      # 3 孔 @ 两臂之间 + 中心过孔 + 完整三叉臂（避让中心孔）
    CENTER4 = "center4"  # 4 孔 90° + 中心 3 短臂（沉头口以内，无中心孔）


def plate_part_id(preset: PlatePreset) -> str:
    return f"l-link-adapter-{preset.value}"


def assembly_id(preset: PlatePreset) -> str:
    return f"l-link-motor-mount-{preset.value}"


def _value(value: object) -> float:
    evaluate = getattr(value, "evaluate", None)
    return float(evaluate()) if callable(evaluate) else float(value)


def params() -> dict:
    """全部默认尺寸 {name: value}（三件共用一份）。"""
    return {var.name: _value(var) for var in _ALL_VARS}


# ---- derived datums: upper body ----
def pocket_r(p: dict) -> float:
    return (p["rod_d"] - p["thickness"]) / 2.0


def mount_x(p: dict) -> float:
    """安装面 2（槽底，贴转接板背面）x = L - plate_t。"""
    return p["L"] - p["plate_t"]


def x_end(p: dict) -> float:
    """右端面 x：电机2 侧槽深（自落座面 x=L）= 左槽深 D-d_motor/2（同规格）。"""
    return p["L"] + (p["D"] - p["d_motor"] / 2.0)


def back_y(p: dict) -> float:
    """剖分水平段 y（上件/壳体接口平面）。"""
    return p["rod_d"] / 2.0 * (2.0 * p["back_cut_frac"] - 1.0)


def split_xs(p: dict) -> tuple[float, float]:
    """"l" 剖分 (x_a, x_b)：水平段止点 / 竖直段位置；弧半径 x_b−x_a，弧心 (x_a, back_y−(x_b−x_a))。"""
    return p["split_arc_frac"] * p["L"], p["split_end_frac"] * p["L"]


def pad_top(p: dict) -> float:
    """壳体 pad 顶面 y（boss 底端贴合面）= −(r − wall_t − pad_t)。"""
    return -(p["rod_d"] / 2.0 - p["wall_t"] - p["pad_t"])


def boss_xs(p: dict) -> tuple[float, float]:
    return p["boss_x1"], p["boss_x2"]


def radial_x(p: dict) -> float:
    """径向 M2 沉头孔轴向位置：转接板厚中面 x = L − plate_t/2。"""
    return p["L"] - p["plate_t"] / 2.0


def radial_angles(p: dict) -> list[float]:
    """径向孔 / 三叉臂角度（度，YZ 面内自 +Y 量向 +Z；rotate_shape 绕 +X 正向即 +Y→+Z）。"""
    n = int(p["rad_screw_n"])
    return [p["key_phase"] + 360.0 / n * k for k in range(n)]


def rib_low_x(p: dict) -> float:
    """筋斜边低端 x_i = √(br² − (rt/2)²)：恰落在 boss 柱面与筋两侧面的交线上。"""
    br = p["boss_d"] / 2.0
    return math.sqrt(br * br - (p["rib_t"] / 2.0) ** 2)


# ---- derived datums: shell ----
def notch_band(p: dict) -> tuple[float, float]:
    """走线口 y 带 [底, 顶]：顶 = back_y − notch_sill。"""
    top = back_y(p) - p["notch_sill"]
    return top - p["notch_h"], top


def shell_csink_depth(p: dict) -> float:
    """壳底 90° 沉头锥深（派生）。"""
    return (p["csink_d"] - p["shell_hole_d"]) / 2.0


def spot_y(p: dict) -> float:
    """锪平平面 y = −r + spot_depth（沉头锥口所在平面）。"""
    return -p["rod_d"] / 2.0 + p["spot_depth"]


def coax_hole_x(p: dict) -> float:
    """同轴走线孔中心 x：boss 2 筋尖 与 竖直端壁内面 x_b−wall_t 的中点。"""
    _, xb = split_xs(p)
    return ((p["boss_x2"] + p["boss_d"] / 2.0 + p["rib_len"]) + (xb - p["wall_t"])) / 2.0


def coax_tool_top(p: dict) -> float:
    """同轴孔刀具顶 y = −(r−wall_t)/2（落在腔内，孔只穿壳底壁）。"""
    return -(p["rod_d"] / 2.0 - p["wall_t"]) / 2.0


def notch_blend_rise(p: dict) -> float:
    """走线口上边外环圆角沿拐角环面向上的高度（z=0 截面，边内角 90°+tilt）。"""
    _, y_top = notch_band(p)
    tilt = math.asin((p["r_corner"] - y_top) / (p["r_corner"] + p["rod_d"] / 2.0))
    return p["safe_fillet_r"] / math.tan((math.pi / 2.0 + tilt) / 2.0) * math.cos(tilt)


# ---- derived datums: adapter plate ----
def plate_r(p: dict) -> float:
    return pocket_r(p) - p["plate_gap"]


def motor_csink_depth(p: dict) -> float:
    """电机螺丝 90° 沉头锥深（派生）。"""
    return (p["m2_csink_d"] - p["m2_hole_d"]) / 2.0


def head_recess(p: dict) -> float:
    """沉头头顶低于板背面的量（派生）：(m2_csink_d − m2_head_dk)/2。"""
    return (p["m2_csink_d"] - p["m2_head_dk"]) / 2.0


def plate_layout(p: dict, preset: PlatePreset) -> dict:
    """盘面拓扑（if 分支决定结构，而非仅改数值）：孔数 / 孔相位 / 凸起臂段 [key_r0, key_r1] / 中心孔 / 凸起顶面数。"""
    if preset is PlatePreset.STAR3:
        # 3 孔落在两臂之间（+60°）；臂避让中心孔 → 3 段分离臂
        return dict(hole_n=3, hole_phase=p["key_phase"] + 60.0, key_r0=p["m2_center_d"] / 2.0 + KEY_HUB_CLEAR,
                    key_r1=p["key_r_out"], bore_d=p["m2_center_d"], key_faces=3)
    elif preset is PlatePreset.CENTER4:
        # 4 孔 mod 90° 与三叉 mod 120° 的最大最小角距 = 15°（相位 +45°）；短臂连成中心星，无中心孔
        return dict(hole_n=4, hole_phase=p["key_phase"] + 45.0, key_r0=0.0, key_r1=p["key_r_in"],
                    bore_d=0.0, key_faces=1)
    raise ValueError(f"unknown plate preset: {preset!r}")


def hole_angles(p: dict, preset: PlatePreset) -> list[float]:
    lay = plate_layout(p, preset)
    return [lay["hole_phase"] + 360.0 / lay["hole_n"] * k for k in range(lay["hole_n"])]


def polar(radius: float, angle: float) -> tuple[float, float]:
    """YZ 面内角度（自 +Y 量向 +Z）→ (y, z)。"""
    a = math.radians(angle)
    return radius * math.cos(a), radius * math.sin(a)


def pilot_inner_r(p: dict, preset: PlatePreset) -> float:
    """径向导孔内端半径：自板外圆向内 rad_pilot_depth，截短至到电机孔 / 中心孔剩余壁 ≥ min_web
    （导孔轴在 x=radial_x 平面内，孔轴 ∥ X → YZ 面内点到线段距离；沉头锥不到导孔 x 带，见守卫）。"""
    lay, pr, web = plate_layout(p, preset), p["rad_pilot_d"] / 2.0, p["min_web"]
    t = plate_r(p) - p["rad_pilot_depth"]
    c, rc = p["m2_hole_d"] / 2.0 + pr + web, p["m2_pcd"] / 2.0
    for ap in radial_angles(p):
        for ah in hole_angles(p, preset):
            d = math.radians(ah - ap)
            perp, along = rc * abs(math.sin(d)), rc * math.cos(d)
            if perp < c and along > 0.0:
                t = max(t, along + math.sqrt(c * c - perp * perp))
    if lay["bore_d"] > 0.0:
        t = max(t, lay["bore_d"] / 2.0 + web)
    return t


def radial_screw_len(p: dict, preset: PlatePreset) -> float | None:
    """径向 M2 沉头自攻选型：头顶齐锪平面 r−rad_spot_depth；尖端距导孔底 ≥ 0.5、入板 ≥ 1.5 的最长标准长度。"""
    head, t_in, rpl = p["rod_d"] / 2.0 - p["rad_spot_depth"], pilot_inner_r(p, preset), plate_r(p)
    fits = [ls for ls in RAD_SCREW_LENGTHS if head - ls >= t_in + 0.5 - 1e-9 and rpl - (head - ls) >= 1.5 - 1e-9]
    return max(fits) if fits else None


def _web_to_arms(p: dict, preset: PlatePreset, center_r: float, angle: float, radius: float) -> float:
    """圆（心在 (center_r, angle)、半径 radius）到三叉凸起臂（t∈[key_r0,key_r1]、|s|≤key_w/2）的最小净距。"""
    lay, hw = plate_layout(p, preset), p["key_w"] / 2.0
    best = math.inf
    for ak in radial_angles(dict(p, rad_screw_n=3)):
        d = math.radians(angle - ak)
        along, perp = center_r * math.cos(d), center_r * abs(math.sin(d))
        dt = max(lay["key_r0"] - along, 0.0, along - lay["key_r1"])
        best = min(best, math.hypot(dt, max(perp - hw, 0.0)) - radius)
    return best


# ---- guard chain ----
def check_body(p: dict | None = None) -> None:
    """上件参数约束链（REQUIREMENTS.md；逐阶段追加，S10 统一边界扫描）。"""
    p = params() if p is None else p
    r = p["rod_d"] / 2.0
    assert p["d_motor"] / 2.0 < p["D"], "d_motor/2 必须小于 D（左槽底低于臂端）"
    assert p["r_corner"] > r, "r_corner 必须大于杆半径（拐角内侧退化会静默产出坏几何）"
    assert p["r_corner"] < p["D"], "r_corner 必须小于 D（左臂直段存在）"
    assert x_end(p) > p["r_corner"], "x_end 必须大于 r_corner（底部直段存在）"
    # S2（槽 / 安装面 2 下沉）：
    assert 0.0 < p["thickness"] < p["rod_d"], "thickness 须∈(0, rod_d)（槽壁存在）"
    assert p["plate_t"] >= 5.0, "plate_t 须 ≥ 5（用户要求转接板至少 5mm）"
    assert mount_x(p) > p["r_corner"] + pocket_r(p), \
        "安装面 2 须位于底部直段（右槽不进入拐角区）"
    # S3（"l" 剖分；壳体 = 杆 ∩ 壳区 的前提是两槽永不进入壳区）：
    by, (xa, xb) = back_y(p), split_xs(p)
    assert 0.5 <= p["back_cut_frac"] < 1.0, "back_cut_frac 须∈[0.5, 1)（剖分面在轴线上方且在杆内）"
    assert p["d_motor"] / 2.0 >= by + p["wall_t"] - 1e-9, \
        "左槽底须高于剖分面至少 wall_t（左槽底到壳腔壁）"
    assert xa > p["r_corner"] + 2.0, "x_a 须越过拐角 r_corner+2（水平段落在直段）"
    assert xa < xb, "split_arc_frac 须小于 split_end_frac（相切弧存在）"
    # 弧底 y=back_y−Rs 须高于壳腔底 −(r−wall_t) ≥ 1：否则腔内端壁内弧（R=Rs−wall_t）穿出腔底、竖直段消失；
    # 弧底贴杆底（Rs=back_y+r，旧界）时竖直剖分面整面消失（S10 L 边界）
    assert xb - xa <= by + r - p["wall_t"] - 1.0 + 1e-9, \
        "弧底须高于壳腔底 ≥ 1：x_b−x_a ≤ back_y+r−wall_t−1（竖直段落在杆内且腔内端壁竖直段存在）"
    assert xb <= mount_x(p) - p["wall_t"] + 1e-9, \
        "x_b 须距安装面 2 至少 wall_t（右槽与电机2 套筒整圆保持完整）"
    # S5（长 boss + 十字筋，悬伸在壳腔直段内）：
    reach = p["boss_d"] / 2.0 + p["rib_len"]
    assert p["boss_x1"] - reach >= p["r_corner"] + 2.0 - 1e-9, "boss_x1 筋根须距拐角 r_corner ≥ 2"
    assert p["boss_x2"] + reach <= xa - 2.0 + 1e-9, "boss_x2 筋尖须距剖分弧起点 x_a ≥ 2（壳腔端界）"
    assert p["boss_x2"] - p["boss_x1"] >= 2.0 * reach + 1.0 - 1e-9, "两 boss 十字筋须相距 ≥ 1（不相碰）"
    assert (r - p["wall_t"]) ** 2 > by * by and reach <= math.sqrt((r - p["wall_t"]) ** 2 - by * by) - 0.5 + 1e-9, \
        "十字筋 z 向须落在剖分面处壳腔开口内（半宽 −0.5）"
    assert 0.0 < p["boss_hole_depth"] <= by - pad_top(p) - 0.5 + 1e-9, "boss 盲孔深须∈(0, boss 长 − 0.5]（不打穿根部）"
    assert 0.0 < p["boss_hole_d"] <= p["boss_d"] - 2.0 + 1e-9, "boss_hole_d 须∈(0, boss_d − 2]（盲孔壁 ≥ 1）"
    assert p["rib_len"] > 0.0, "rib_len 须 > 0（筋尖伸出 boss 面）"
    assert p["gusset_chamfer"] > 0.0, "gusset_chamfer 须 > 0（斜边倒角存在）"
    assert p["rib_t"] >= 2.0 * p["gusset_chamfer"] + 0.3 - 1e-9, "rib_t 须 ≥ 2·gusset_chamfer + 0.3（倒角后筋有余量）"
    assert p["rib_t"] < p["boss_d"], "rib_t 须 < boss_d（筋低端落在 boss 柱面上）"
    assert 0.0 < p["gusset_h"] <= by - pad_top(p) - 0.5 + 1e-9, "gusset_h 须∈(0, boss 长 − 0.5]（筋低端不触 pad）"
    assert math.hypot(rib_low_x(p), by - p["gusset_h"]) <= r - p["wall_t"] - 0.5 + 1e-9, \
        "筋低端须在壳腔内（距腔壁 ≥ 0.5；筋截面凸，两端在腔内即全在）"
    # S6（端盖 rim 圆角：外环 + 槽口两圆角共用端面槽壁 thickness/2）：
    rf = p["fillet_r"]
    assert 0.0 < rf < p["thickness"] / 4.0, "fillet_r 须∈(0, thickness/4)（端面槽壁 thickness/2 容两圆角）"
    assert rf < p["D"] - p["d_motor"] / 2.0, "fillet_r 须 < 槽深 D−d_motor/2（槽口圆角不进槽底）"
    assert rf < pocket_r(p), "fillet_r 须 < 槽半径"
    # S7（倒角后切削：走线窗 / 三叉凹槽 / 径向沉头）：
    rp, off, wh, ww, wr = pocket_r(p), p["cable_w_off"], p["cable_w_h"], p["cable_w_w"], p["cable_w_rr"]
    assert 3.0 - 1e-9 <= off <= 5.0 + 1e-9, "cable_w_off 须∈[3, 5]"
    assert p["d_motor"] / 2.0 + off + wh <= p["D"] - 2.0 + 1e-9 and p["L"] + off + wh <= x_end(p) - 2.0 + 1e-9, \
        "走线窗顶须距各自槽口 ≥ 2（避开 rim 圆角）"
    assert 0.0 < 2.0 * wr < min(ww, wh), "走线窗圆角须 0 < 2·cable_w_rr < min(w, h)"
    assert ww <= 1.6 * rp + 1e-9, "cable_w_w 须 ≤ 1.6·rp（窗间壁保留）"
    assert abs(p["cable_w_phase"] % 90.0 - 45.0) <= CABLE_W_PHASE_TOL + 1e-9, \
        "cable_w_phase 须∈45°±5°（mod 90）：左窗朝 +X 会隧穿拐角内弯（经验界）"
    hr, cr, sr, sd = p["rad_clear_d"] / 2.0, p["rad_csink_d"] / 2.0, p["rad_spot_d"] / 2.0, p["rad_spot_depth"]
    assert int(p["rad_screw_n"]) >= 1, "rad_screw_n 须 ≥ 1"
    assert cr > hr, "rad_csink_d 须 > rad_clear_d（沉头存在）"
    assert p["rad_spot_d"] >= p["rad_csink_d"] + 0.2 - 1e-9, "rad_spot_d 须 ≥ rad_csink_d + 0.2（锪平平台环）"
    assert sd - (r - math.sqrt(r * r - sr * sr)) >= 0.1 - 1e-9, "rad_spot_depth 须 ≥ 锪平曲面矢高 + 0.1（侧壁不成薄片）"
    assert (r - rp) - sd - (cr - hr) >= 1.0 - 1e-9, "径向沉头下剩余孔壁须 ≥ 1"
    xs = radial_x(p)
    assert mount_x(p) + 1e-9 < xs - sr and xs + sr < p["L"] - 1e-9, \
        "径向孔 x 区间须落在转接板厚内 (L−plate_t, L)（不碰凹槽 / 走线窗）"
    assert p["key_w"] > 0.0, "key_w 须 > 0（三叉臂存在）"
    assert p["key_r_out"] + p["key_gap"] <= rp - 0.5 + 1e-9, "三叉凹槽臂长须 ≤ rp − 0.5（安装面 2 外环保留）"
    assert mount_x(p) - p["groove_d"] >= xb + p["wall_t"] - 1e-9, "凹槽底后须保留 ≥ wall_t 实心套筒（至 x_b）"


def check_shell(p: dict | None = None) -> None:
    """壳体参数约束链（含上件链：剖分/槽守卫共用）。"""
    p = params() if p is None else p
    check_body(p)
    r, rc, wt = p["rod_d"] / 2.0, p["r_corner"], p["wall_t"]
    xa, xb = split_xs(p)
    # S4（腔 / 走线口）：
    assert xb - xa - wt >= 1.0, "弧形端壁内弧半径 Rs−wall_t 须 ≥ 1（腔区弧存在）"
    assert 2.0 * p["notch_rr"] < min(p["notch_w"], p["notch_h"]), "notch_rr 须 < min(notch_w, notch_h)/2"
    assert p["notch_sill"] > 0.0, "notch_sill 须 > 0（走线口不劈开 rim 接口面）"
    assert p["notch_w"] / 2.0 < r - wt, "notch_w/2 须 < r−wall_t（走线口在腔宽内）"
    y_bot, _ = notch_band(p)
    # 走线口刀具止于左电机轴 x=0：口底、口侧处的拐角内壁 x 须 ≤ −0.5（贯穿，不留盲皮）
    d = rc + math.sqrt((r - wt) ** 2 - (p["notch_w"] / 2.0) ** 2)
    assert d * d > (rc - y_bot) ** 2 and rc - math.sqrt(d * d - (rc - y_bot) ** 2) <= -0.5, \
        "走线口须贯穿左端拐角壁（口底过低时刀具止于 x=0 前未穿壁）"
    # S5（pad / 锪平 / 沉头通孔，boss 正下方）：
    pt, rho = pad_top(p), p["pad_d"] / 2.0
    assert rho < r - wt and pt >= -math.sqrt((r - wt) ** 2 - rho * rho) - 1e-9, \
        "pad 顶面须完整高于其边缘处的内壁（pad 顶面整圆贴合 boss）"
    assert p["pad_d"] >= p["boss_d"] + 1.0 - 1e-9, "pad_d 须 ≥ boss_d + 1（pad 覆盖 boss 底端）"
    assert math.sqrt(r * r - rho * rho) > r - wt / 2.0, "pad 底须埋入壳壁（pad 刀具起点 y=−(r−wall_t/2) 在料内）"
    assert p["spot_depth"] - (r - math.sqrt(r * r - (p["spot_d"] / 2.0) ** 2)) >= 0.1 - 1e-9, \
        "锪平须整平且侧壁 ≥ 0.1（spot_depth − spot_d/2 处曲面矢高 ≥ 0.1，否则 z 向端点侧壁成薄片边）"
    assert p["spot_d"] >= p["csink_d"] + 0.2 - 1e-9, "spot_d 须 ≥ csink_d + 0.2（沉头口外留锪平平台环）"
    assert p["csink_d"] > p["shell_hole_d"], "csink_d 须 > shell_hole_d（沉头锥存在）"
    assert pt - (spot_y(p) + shell_csink_depth(p)) >= 1.0 - 1e-9, "沉头锥下剩余孔壁须 ≥ 1.0"
    # S6（同轴走线孔 + 两走线口外环圆角）：
    hw, hl, sf = p["notch_w"] / 2.0, p["notch_h"], p["safe_fillet_r"]
    near = p["boss_x2"] + max(p["boss_d"] / 2.0 + p["rib_len"], rho, p["spot_d"] / 2.0)
    assert (xb - wt) - near >= hl + 2.0 - 1e-9, \
        "同轴孔窗口（boss 2 筋尖/pad/锪平 → 端壁内面）须 ≥ notch_h + 2（孔两侧各留 ≥1）"
    y1 = coax_tool_top(p)
    assert y1 > -math.sqrt((r - wt) ** 2 - hw * hw) + 0.5, "同轴孔刀具顶须在腔内（孔穿透壳底壁）"
    cx = coax_hole_x(p)
    if cx + hl / 2.0 > xa:
        assert back_y(p) - (xb - xa) + math.sqrt((xb - xa - wt) ** 2 - (cx + hl / 2.0 - xa) ** 2) >= y1 + 1.0, \
            "同轴孔刀具顶须低于端壁内弧至少 1（不削端壁）"
    assert math.sqrt(r * r - hw * hw) > r - wt / 2.0, "同轴孔外环须可按 y 与内环分离（notch_w 不过宽）"
    assert 0.0 < sf < p["notch_rr"], "safe_fillet_r 须∈(0, notch_rr)（口角圆角包住外环圆角）"
    assert sf + 0.5 <= wt + 1e-9, "safe_fillet_r 须 ≤ wall_t − 0.5（圆角不吃穿壁）"
    assert notch_blend_rise(p) <= p["notch_sill"] - 0.05 + 1e-9, \
        "走线口上边圆角顶须低于剖分面 0.05（圆角不劈 rim 接口面）"


def check_plate(p: dict | None = None) -> None:
    """转接板约束链（含上件 / 壳体链；两个 preset 均须可行——上件凹槽与 preset 无关）。"""
    p = params() if p is None else p
    check_shell(p)
    web, rpl, rf = p["min_web"], plate_r(p), p["safe_fillet_r"]
    assert p["plate_gap"] > 0.0, "plate_gap 须 > 0（板在槽内可推入）"
    assert p["key_gap"] > 0.0, "key_gap 须 > 0（凸起在凹槽内有侧隙）"
    assert p["min_web"] > 0.0, "min_web 须 > 0"
    assert p["key_h"] > 0.0, "key_h 须 > 0（凸起存在）"
    assert p["groove_d"] > p["key_h"], "groove_d 须 > key_h（凸起顶不顶凹槽底，板背面贴安装面 2）"
    assert head_recess(p) >= 0.1 - 1e-9, "m2_csink_d 须 ≥ m2_head_dk + 0.2（电机螺丝头沉入背面 ≥ 0.1，不顶安装面 2）"
    assert motor_csink_depth(p) + head_recess(p) <= p["plate_t"] - 2.0 + 1e-9, "电机沉头锥深 + 头沉入须 ≤ plate_t − 2"
    assert p["m2_pcd"] / 2.0 + p["m2_csink_d"] / 2.0 <= rpl - rf - web + 1e-9, "电机沉头口须距板外圆圆角 ≥ min_web"
    assert 0.0 < p["key_r_in"] <= p["key_r_out"], "key_r_in 须∈(0, key_r_out]（短臂为完整臂子集）"
    assert math.hypot(p["key_r_out"], p["key_w"] / 2.0) <= rpl - rf - KEY_TIP_LAND + 1e-9, \
        "三叉臂端角须落在板背面平面内且距外圆圆角 ≥ KEY_TIP_LAND（背面平面环不被臂端割断）"
    xs, pr = radial_x(p), p["rad_pilot_d"] / 2.0
    assert xs - pr >= mount_x(p) + max(rf, motor_csink_depth(p)) + web - 1e-9, \
        "径向导孔 x 带须距背面圆角 / 电机沉头锥 ≥ min_web"
    assert xs + pr <= p["L"] - rf - web + 1e-9, "径向导孔 x 带须距落座面圆角 ≥ min_web"
    assert 0.0 < p["rad_pilot_d"] < p["rad_clear_d"], "rad_pilot_d 须∈(0, rad_clear_d)（自攻导孔小于套筒过孔）"
    assert p["m2_center_d"] > 0.0, "m2_center_d 须 > 0（STAR3 中心孔存在）"
    for preset in PlatePreset:
        lay = plate_layout(p, preset)
        for ah in hole_angles(p, preset):
            assert _web_to_arms(p, preset, p["m2_pcd"] / 2.0, ah, p["m2_csink_d"] / 2.0) >= web - 1e-9, \
                f"{preset.value}: 三叉凸起到电机沉头口须 ≥ min_web"
        if lay["bore_d"] > 0.0:
            assert p["m2_pcd"] / 2.0 - p["m2_csink_d"] / 2.0 - lay["bore_d"] / 2.0 >= web - 1e-9, \
                f"{preset.value}: 电机沉头口到中心孔须 ≥ min_web"
        assert rpl - pilot_inner_r(p, preset) >= 2.0 - 1e-9, f"{preset.value}: 径向导孔截短后深度须 ≥ 2"
        assert radial_screw_len(p, preset) is not None, f"{preset.value}: 无可用径向 M2 螺丝长度（尖端 / 入板）"

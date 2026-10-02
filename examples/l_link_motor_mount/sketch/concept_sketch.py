"""l_link 概念示意图（非 CAD 几何；按 REQUIREMENTS.md 默认参数解析栅格化 z=0 剖面）。

面板:
  (a) 当前方案 XY 剖面 z=0：套筒实心
  (b) 方案 1：内腔延伸到右槽底后，拆壳后球头内六角斜向拧紧电机2
  (c) 方案 1 右槽底端视（x=78，自 −X 看向 +X）：孔位/螺丝头/腔
  (d) 方案 2：转接盘 + 卡口
  (e) 方案 3：开口夹紧套筒（仅外壳不转的电机）
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patches
from matplotlib.colors import ListedColormap

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

# ---- 默认参数（REQUIREMENTS.md）----
L, D, ROD_D, THICK, D_MOTOR, RC, WALL = 80.0, 20.0, 30.0, 6.0, 19.0, 17.0, 2.0
R = ROD_D / 2
RP = (ROD_D - THICK) / 2
FLOOR_L = D_MOTOR / 2                     # 左安装面 y
DEPTH = D - FLOOR_L                       # 槽深 10.5
X_END = L + DEPTH                         # 右端面 90.5
BACK_Y = 7.5
XA, XB = 0.60 * L, 0.75 * L               # 48, 60
RS = XB - XA                              # 12
CX, CY = XA, BACK_Y - RS                  # 弧心 (48, -4.5)
BOSS_X = (25.0, 40.0)
BOSS_R, PAD_T, PAD_HW = 2.5, 1.0, 4.0
PC, HEAD_R = 8.0, 2.25

UPPER, SHELL, CAV_COL = "#9cc3e6", "#f4b183", "white"


def path_dist(x, y):
    """到 L 形扫掠中心线的距离（端盖平面截止：臂 y<=D，直段 x<=X_END）。"""
    big = np.full_like(x, 1e9)
    d_arm = np.where((y >= RC) & (y <= D), np.abs(x), big)
    d_arc = np.where((x <= RC) & (y <= RC), np.abs(np.hypot(x - RC, y - RC) - RC), big)
    d_bot = np.where((x >= RC) & (x <= X_END), np.abs(y), big)
    return np.minimum(np.minimum(d_arm, d_arc), d_bot)


def upper_side(x, y):
    """"l" 剖分线上/右侧 = 上件。"""
    arc_y = CY + np.sqrt(np.clip(RS**2 - (x - CX) ** 2, 0.0, None))
    shell = ((x <= XA) & (y < BACK_Y)) | ((x > XA) & (x < XB) & (y < arc_y))
    return ~shell


def section(option: int):
    xs = np.arange(-20, 101, 0.08)
    ys = np.arange(-22, 31, 0.08)
    x, y = np.meshgrid(xs, ys)
    d = path_dist(x, y)
    rod = d <= R
    eroded = d <= R - WALL
    up = upper_side(x, y)

    if option == 0:  # 壳体腔：y<=back_y，右端弧形端壁内偏 wall_t（凹侧 → 同心 r=RS-WALL）
        arc_ok = (x <= XA) | ((y > CY) & (np.hypot(x - CX, y - CY) <= RS - WALL)) | \
                 ((y <= CY) & (x <= XB - WALL))
        cavity = eroded & (y <= BACK_Y) & arc_ok
    else:            # 方案 1：腔连续延伸到右槽底后 wall_t，套筒段为薄壁管
        cavity = eroded & (x <= L - WALL) & ((y <= BACK_Y) | (x >= XB))

    pocket_l = (np.abs(x) <= RP) & (y >= FLOOR_L)
    pocket_r = (np.abs(y) <= RP) & (x >= L)

    boss = np.zeros_like(rod)
    pad = np.zeros_like(rod)
    holes = np.zeros_like(rod)
    y_pad_top = -(R - WALL - PAD_T)       # -12
    for bx in BOSS_X:
        boss |= (np.abs(x - bx) <= BOSS_R) & (y >= y_pad_top) & (y <= BACK_Y)
        for s in (-1, 1):                 # ±x 三角筋
            u = s * (x - bx) - BOSS_R
            boss |= (u >= 0) & (u <= 3.0) & (y <= BACK_Y) & (y >= BACK_Y - 5.0 + u * 5.0 / 3.0)
        pad |= (np.abs(x - bx) <= PAD_HW) & (y >= -(R - WALL)) & (y <= y_pad_top)
        holes |= (np.abs(x - bx) <= 1.35) & (y >= y_pad_top) & (y <= y_pad_top + 6.0)
        csk_r = np.clip(2.7 - (y + R - 0.3), 1.35, 2.7)
        holes |= (np.abs(x - bx) <= csk_r) & (y <= y_pad_top)
        holes |= (np.abs(x - bx) <= 3.5) & (y <= -R + 0.3)
    notch = (x < -8) & (y >= 0) & (y <= 7) & (d > R - WALL - 0.01)

    material = rod & ~cavity & ~pocket_l & ~pocket_r
    material = (material | ((boss | pad) & rod)) & ~holes & ~notch
    code = np.zeros(x.shape, dtype=int)
    code[material & up] = 1
    code[material & ~up] = 2
    code[material & boss] = 1             # boss 属上件（悬伸在剖分线下方）
    return xs, ys, code


def draw_section(ax, option, title):
    xs, ys, code = section(option)
    # 方案1 画面里壳体已拆下 → 淡色幽灵显示
    cmap = ListedColormap(["white", UPPER, SHELL if option == 0 else "#fdeee2"])
    ax.imshow(code, origin="lower", extent=(xs[0], xs[-1], ys[0], ys[-1]),
              cmap=cmap, vmin=0, vmax=2, interpolation="nearest")
    # "l" 剖分线
    t = np.linspace(math.pi / 2, 0, 50)
    lx = np.r_[-16, XA, CX + RS * np.cos(t), XB]
    ly = np.r_[BACK_Y, BACK_Y, CY + RS * np.sin(t), -17]
    ax.plot(lx, ly, color="crimson", lw=1.6, ls="--")
    ax.annotate('"l" 剖分线', xy=(55, 3.5), xytext=(46, 22), color="crimson",
                arrowprops=dict(arrowstyle="->", color="crimson"), fontsize=9)
    # 电机（虚线）与轴线
    ax.add_patch(patches.Rectangle((-12, FLOOR_L), 24, 19, fill=False, ls=":", lw=1.2, ec="k"))
    ax.text(0, FLOOR_L + 13.5, "电机1\n(轴 Y)", ha="center", fontsize=8)
    ax.add_patch(patches.Rectangle((L, -12), 19, 24, fill=False, ls=":", lw=1.2, ec="k"))
    ax.text(L + 13.5, 0, "电机2\n(轴 X)", ha="center", va="center", fontsize=8)
    ax.plot([0, 0], [-20, 30], "k-.", lw=0.6)
    ax.plot([-20, 100], [0, 0], "k-.", lw=0.6)
    # 安装面
    ax.plot([-RP, RP], [FLOOR_L, FLOOR_L], color="#2e7d32", lw=3)
    ax.plot([L, L], [-RP, RP], color="#2e7d32", lw=3)
    ax.text(-RP - 1, FLOOR_L + 0.8, "安装面1", color="#2e7d32", ha="right", fontsize=8)
    ax.text(L - 1, RP + 1.2, "安装面2", color="#2e7d32", ha="right", fontsize=8)
    for bx in BOSS_X:
        ax.text(bx, -19.5, f"boss\nx={bx:.0f}", ha="center", fontsize=7)
    ax.text(-19, 4, "走线口", fontsize=7, rotation=90, va="center")
    for xv, lab in ((XA, "0.60L=48"), (XB, "0.75L=60"), (L, "L=80")):
        ax.text(xv, 26.5, lab, ha="center", fontsize=7, color="gray")
        ax.plot([xv, xv], [24, 25.8], color="gray", lw=0.8)
    ax.set_xlim(-20, 100); ax.set_ylim(-22, 30)
    ax.set_aspect("equal"); ax.set_title(title, fontsize=11)
    ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)")


def draw_screws_and_driver(ax):
    for yh in (PC * math.cos(math.pi / 4), -PC * math.cos(math.pi / 4)):
        ax.add_patch(patches.Rectangle((L - WALL - 2.5, yh - HEAD_R), 2.5, 2 * HEAD_R,
                                       fc="dimgray", ec="k", lw=0.5))
        ax.add_patch(patches.Rectangle((L - WALL, yh - 0.6), 6.0, 1.2, fc="dimgray", ec="k", lw=0.5))
        ang = math.radians(20)
        x0, y0 = L - WALL - 2.5, yh
        run = (y0 + 20) / math.tan(ang)
        ax.plot([x0, x0 - run], [y0, y0 - run * math.tan(ang)], color="#6a1b9a", lw=2.2)
        ax.add_patch(patches.Circle((x0 - 0.4, y0), 0.9, color="#6a1b9a"))
    ax.text(-19, -21, "壳体已拆下\n(淡色=原位置)", fontsize=7, color="#b07040")
    ax.annotate("球头内六角 ~20°，经套筒内孔 r=13 → 从底部敞口伸出\n驱动杆在 z=±5.7 平面，boss 在 z=0(半径2.5)，不干涉",
                xy=(58, -0.6), xytext=(14, 18.5),
                color="#6a1b9a", fontsize=8,
                arrowprops=dict(arrowstyle="->", color="#6a1b9a"))
    ax.annotate("4×螺丝(投影)\n拧入电机2底座", xy=(76, -5.6), xytext=(50, -20.5), fontsize=8,
                arrowprops=dict(arrowstyle="->"))
    ax.annotate("槽底壁 2mm", xy=(79, -9), xytext=(84, -20.5), fontsize=8,
                arrowprops=dict(arrowstyle="->"))


def draw_end_view(ax):
    ax.add_patch(patches.Circle((0, 0), R, fc=UPPER, ec="k"))
    ax.add_patch(patches.Circle((0, 0), R - WALL, fc="#d9d9d9", ec="k", ls="--"))
    for k in range(4):
        a = math.radians(45 + 90 * k)
        cz, cy = PC * math.cos(a), PC * math.sin(a)
        ax.add_patch(patches.Circle((cz, cy), 1.35, fc="white", ec="k"))
        ax.add_patch(patches.Circle((cz, cy), HEAD_R, fill=False, ec="dimgray", ls=":"))
    ax.add_patch(patches.Circle((0, 0), PC, fill=False, ec="gray", ls="-.", lw=0.7))
    ax.plot([-R - 2, R + 2], [BACK_Y, BACK_Y], color="crimson", ls="--", lw=1)
    ax.text(R + 2.3, BACK_Y, "y=7.5", color="crimson", va="center", fontsize=7)
    ax.text(0, -R - 3.5, "外壁 r=15 / 腔 r=13\n灰=槽底壁(2mm)  圆=4×φ2.7 @pc16, 45°",
            ha="center", va="top", fontsize=7.5)
    ax.text(0, 0, "头φ4.5\n外缘 10.25 < 13 OK", ha="center", va="center", fontsize=7)
    ax.set_xlim(-22, 22); ax.set_ylim(-25, 20); ax.set_aspect("equal")
    ax.set_xlabel("z (mm)"); ax.set_ylabel("y (mm)")
    ax.set_title("(c) 方案1 右槽底端视 x=78（自腔内看 +X）", fontsize=10)


def draw_option2(ax):
    ax.add_patch(patches.Rectangle((60, -R), X_END - 60, 2 * R, fc=UPPER, ec="k"))
    ax.add_patch(patches.Rectangle((L, -RP), X_END - L + 1, 2 * RP, fc="white", ec="none"))
    ax.add_patch(patches.Rectangle((L, -RP), 2.5, 2 * RP, fc="#ffe082", ec="k"))
    ax.text(L + 1.25, -RP - 2.3, "转接盘", ha="center", fontsize=8)
    for s in (-1, 1):  # 卡口耳 + L 槽
        ax.add_patch(patches.Rectangle((L + 0.4, s * RP - (0 if s > 0 else 1.2)), 1.8, 1.2,
                                       fc="#ffe082", ec="k"))
    ax.add_patch(patches.Rectangle((L + 2.5, -RP + 1), 14, 2 * RP - 2, fill=False, ls=":", ec="k"))
    ax.text(L + 9.5, 0, "电机2", ha="center", va="center", fontsize=8)
    for yy in (-5, 5):
        ax.plot([L - 0.5, L + 3.5], [yy, yy], color="dimgray", lw=2)
    ax.plot([L + 1.25, L + 1.25], [R + 1.5, RP], color="#6a1b9a", lw=2.5)
    ax.text(L + 2, R + 1.2, "防转径向螺丝", color="#6a1b9a", fontsize=7.5)
    ax.text(61, 23.5, "① 桌面上把电机拧到转接盘（完全可达）\n② 插入槽 → 旋 15° 锁进 L 形卡口\n③ 径向螺丝防反转",
            fontsize=7.5, va="top")
    ax.set_xlim(58, 100); ax.set_ylim(-20, 24); ax.set_aspect("equal")
    ax.set_xlabel("x (mm)")
    ax.set_title("(d) 方案2 转接盘+卡口（第3个零件）", fontsize=10)


def draw_option3(ax):
    ax.add_patch(patches.Wedge((0, 0), R, -80, 260, width=R - RP, fc=UPPER, ec="k"))
    for z0 in (1.0, -5.0):
        ax.add_patch(patches.Rectangle((z0, -R - 5), 4.0, 6.5, fc=UPPER, ec="k"))
    ax.plot([-7, 7], [-R - 2.2, -R - 2.2], color="dimgray", lw=3)
    ax.add_patch(patches.Circle((0, 0), RP - 0.3, fill=False, ls=":", ec="k"))
    ax.text(0, 0, "电机外壳\n(不转)", ha="center", va="center", fontsize=8)
    ax.text(0, -R - 7.5, "底部轴向开缝 + 切向 M3 夹紧\n外转子电机不适用（会夹住转动钟罩）\n夹紧耳凸出圆润外形",
            ha="center", va="top", fontsize=7.5)
    ax.set_xlim(-22, 22); ax.set_ylim(-32, 20); ax.set_aspect("equal")
    ax.set_xlabel("z (mm)")
    ax.set_title("(e) 方案3 开口夹紧套筒（端视）", fontsize=10)


def main():
    fig = plt.figure(figsize=(17, 9.6))
    gs = fig.add_gridspec(2, 6, height_ratios=[1.15, 1], hspace=0.18, wspace=0.5)
    ax_a = fig.add_subplot(gs[0, 0:3])
    ax_b = fig.add_subplot(gs[0, 3:6])
    draw_section(ax_a, 0, "(a) 当前方案 前视剖面 z=0：套筒实心，电机2 螺丝够不到")
    draw_section(ax_b, 1, "(b) 方案1（推荐）：内腔延伸到右槽底后，套筒变薄壁")
    draw_screws_and_driver(ax_b)
    ax_a.annotate("实心套筒 20mm\n槽底背面无通道", xy=(70, 0), xytext=(64, -20.5), fontsize=8,
                  arrowprops=dict(arrowstyle="->"))
    draw_end_view(fig.add_subplot(gs[1, 0:2]))
    draw_option2(fig.add_subplot(gs[1, 2:4]))
    draw_option3(fig.add_subplot(gs[1, 4:6]))
    handles = [patches.Patch(fc=UPPER, ec="k", label="上件"),
               patches.Patch(fc=SHELL, ec="k", label="壳体"),
               patches.Patch(fc="white", ec="k", label="空腔/槽"),
               plt.Line2D([], [], color="crimson", ls="--", label='"l" 剖分线'),
               plt.Line2D([], [], color="#2e7d32", lw=3, label="命名安装面")]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.06), ncol=5, fontsize=10, frameon=False)
    out = Path(__file__).with_name("concept_options.png")
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()

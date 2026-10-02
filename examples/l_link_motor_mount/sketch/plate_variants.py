"""电机2 转接板变体 + 安装面2 三叉凹槽示意（端视，横轴 z，纵轴 y；图形关于 z 镜像对称）。"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import patches

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

R_OUT, R_POCKET, PLATE_R = 15.0, 12.0, 11.9
PCD_R, HOLE_R, CSK_R = 8.0, 1.35, 2.55
KEY_W, GROOVE_W, KEY_R_OUT, CENTER_R = 2.5, 2.7, 11.2, 3.0
SPOKES = (0.0, 120.0, 240.0)          # 自 +Y 量向 +Z
UPPER, PLATE, KEY, GROOVE = "#9cc3e6", "#ffe082", "#e65100", "#37474f"


def polar(r, ang_deg):
    a = math.radians(ang_deg)
    return r * math.sin(a), r * math.cos(a)   # (z, y)


def spoke(ax, ang, r0, r1, width, color, **kw):
    a = math.radians(ang)
    rect = patches.Rectangle((-width / 2, r0), width, r1 - r0, fc=color, ec="k", lw=0.5, **kw)
    rect.set_transform(matplotlib.transforms.Affine2D().rotate(-a) + ax.transData)
    ax.add_patch(rect)


def holes(ax, n, phase):
    for k in range(n):
        z, y = polar(PCD_R, phase + k * 360.0 / n)
        ax.add_patch(patches.Circle((z, y), CSK_R, fc="white", ec="k", lw=0.8))
        ax.add_patch(patches.Circle((z, y), HOLE_R, fc="#bdbdbd", ec="k", lw=0.5))


def radial_screws(ax):
    for ang in SPOKES:
        z, y = polar(R_OUT + 1.2, ang)
        ax.annotate("", xy=polar(PLATE_R - 3.0, ang), xytext=(z, y),
                    arrowprops=dict(arrowstyle="-|>", color="#6a1b9a", lw=1.6))


def base(ax, title):
    ax.add_patch(patches.Circle((0, 0), R_OUT, fc=UPPER, ec="k"))
    ax.add_patch(patches.Circle((0, 0), R_POCKET, fc="white", ec="k"))
    ax.set_xlim(-18, 18); ax.set_ylim(-18, 19); ax.set_aspect("equal")
    ax.set_title(title, fontsize=10); ax.set_xticks([]); ax.set_yticks([])


def main():
    fig, axs = plt.subplots(1, 4, figsize=(17, 5.2))

    ax = axs[0]
    base(ax, "安装面2（上件槽底 x=75）\n一组完整三叉凹槽 宽2.7 深2.2")
    ax.add_patch(patches.Circle((0, 0), R_POCKET, fc="#dfe9f3", ec="k"))
    for a in SPOKES:
        spoke(ax, a, 0.0, KEY_R_OUT + 0.1, GROOVE_W, GROOVE)
    radial_screws(ax)
    ax.text(0, -17.3, "紫箭头 = 3×M2 径向沉头孔 @ x=77.5（与臂同相）", ha="center", fontsize=8, color="#6a1b9a")

    cases = [
        ("star3：3 孔 120°\n完整三叉（孔在两臂之间）", 3, 60.0, [(CENTER_R + 0.5, KEY_R_OUT)], True, "OK 臂到孔心 6.93 ≥ 4.1"),
        ("center4：4 孔 90°\n中心短三叉 r≤4.2，需无中心孔", 4, 45.0, [(0.0, 4.2)], False, "OK 前提：电机底面中心平整"),
        ("outer4：4 孔 90°\n外缘短块 r≥11.27", 4, 45.0, [(11.27, PLATE_R - 0.3)], True, "NG 外块仅 0.33 mm，无效"),
    ]
    for ax, (title, n, phase, segs, center_hole, verdict) in zip(axs[1:], cases):
        base(ax, "转接板背面 " + title)
        ax.add_patch(patches.Circle((0, 0), PLATE_R, fc=PLATE, ec="k"))
        if center_hole:
            ax.add_patch(patches.Circle((0, 0), CENTER_R, fc="white", ec="k"))
        holes(ax, n, phase)
        for a in SPOKES:
            for r0, r1 in segs:
                spoke(ax, a, r0, r1, KEY_W, KEY)
        radial_screws(ax)
        ax.text(0, -17.3, verdict, ha="center", fontsize=9,
                color="#2e7d32" if verdict.startswith("OK") else "crimson")

    handles = [patches.Patch(fc=UPPER, ec="k", label="上件套筒"),
               patches.Patch(fc=GROOVE, ec="k", label="凹槽 (上件)"),
               patches.Patch(fc=PLATE, ec="k", label="转接板 φ23.8 厚5"),
               patches.Patch(fc=KEY, ec="k", label="凸起 高2 宽2.5"),
               patches.Patch(fc="white", ec="k", label="沉头口 φ5.1 / 过孔 φ2.7 (M2.5 PCD16)")]
    fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=9, frameon=False)
    fig.suptitle("端视（横 z，纵 y，一臂朝 +Y）", fontsize=11)
    out = Path(__file__).with_name("plate_variants.png")
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()

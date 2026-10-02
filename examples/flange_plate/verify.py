"""八孔法兰盘外置验证（几何验证不进建模 notebook）。

run_notebook 取产品 + 回读 export.py 写出的 .scadpkg，逐条断言验证契约（见 README）。
先跑 ``python export.py``，再跑本脚本。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
TOL = 0.05  # mm 级窗口

run = run_notebook(HERE / "flange_plate.py")
body = run.product.body
# 解析期望值直接取 notebook 参数，改参后验证跟着走
v = {name: float(value) for name, value in run.values.items()
     if name.isupper() and isinstance(value, (int, float, scad.Var))}
OD, T, HUB_OD, HUB_TOP = v["FLANGE_OD"], v["FLANGE_T"], v["BOSS_OD"], v["BOSS_TOP_Z"]
BORE_D, PCD, BOLT_D = v["BORE_D"], v["BOLT_PCD"], v["BOLT_D"]
ROOT_R, RIM_R = v["BOSS_FILLET_R"], v["EDGE_FILLET_R"]
BOLT_N = int(v["BOLT_COUNT"])

failures: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        failures.append(name)

# 1) 单实体 + 体积（解析值扣孔，圆角体积为小量，带宽 1%）
volume = body.get_volume()
expected = (math.pi * (OD / 2.0) ** 2 * T
            + math.pi * (HUB_OD / 2.0) ** 2 * (HUB_TOP - T)
            - math.pi * (BORE_D / 2.0) ** 2 * HUB_TOP
            - BOLT_N * math.pi * (BOLT_D / 2.0) ** 2 * T)
check("volume", abs(volume - expected) / expected < 0.01,
      f"v={volume:.1f} analytic={expected:.1f} rel={abs(volume - expected) / expected:.4f}")

# 2) 极值 = Ø100 x Ø100 x 高30：外圆柱壁（R50，rim 圆角后净高 6）、
#    hub 顶环面 z=30、底环面 z=0，三张面按面积唯一化
outer_wall = math.pi * OD * (T - 2.0 * RIM_R)
wall_face = (
    ql.faces()
    .where(ql.prop("geom.type", "==", "CYLINDER"))
    .where(ql.prop("geom.area", ">=", outer_wall * 0.99))
    .where(ql.prop("geom.area", "<=", outer_wall * 1.01))
    .where(ql.prop("geom.center.z", ">=", T / 2.0 - 1.0))
    .where(ql.prop("geom.center.z", "<=", T / 2.0 + 1.0))
).resolve(body)
check("outer-wall", len(wall_face) == 1, f"n={len(wall_face)} area~{outer_wall:.1f}")

hub_top_face = math.pi * ((HUB_OD / 2.0) ** 2 - (BORE_D / 2.0) ** 2)
top_face = (
    ql.faces()
    .where(ql.prop("geom.type", "==", "PLANE"))
    .where(ql.prop("geom.normal.z", ">=", 0.999))
    .where(ql.prop("geom.center.z", ">=", HUB_TOP - TOL))
    .where(ql.prop("geom.center.z", "<=", HUB_TOP + TOL))
    .where(ql.prop("geom.area", ">=", hub_top_face * 0.99))
    .where(ql.prop("geom.area", "<=", hub_top_face * 1.01))
).resolve(body)
check("hub-top", len(top_face) == 1, f"n={len(top_face)} z~{HUB_TOP} area~{hub_top_face:.1f}")

bottom_face = math.pi * ((OD / 2.0 - RIM_R) ** 2 - (BORE_D / 2.0) ** 2) \
    - BOLT_N * math.pi * (BOLT_D / 2.0) ** 2
bot_face = (
    ql.faces()
    .where(ql.prop("geom.type", "==", "PLANE"))
    .where(ql.prop("geom.normal.z", "<=", -0.999))
    .where(ql.prop("geom.center.z", ">=", -TOL))
    .where(ql.prop("geom.center.z", "<=", TOL))
    .where(ql.prop("geom.area", ">=", bottom_face * 0.99))
    .where(ql.prop("geom.area", "<=", bottom_face * 1.01))
).resolve(body)
check("bottom-face", len(bot_face) == 1, f"n={len(bot_face)} area~{bottom_face:.1f}")

# 3) N x Ø11 螺栓孔：上下圆缘共 2N 条 CIRCLE，孔心距轴 = PCD/2
bolt_circle = 2.0 * math.pi * BOLT_D / 2.0
bolt_rims = (
    ql.edges()
    .where(ql.prop("geom.type", "==", "CIRCLE"))
    .where(ql.prop("geom.length", ">=", bolt_circle * 0.99))
    .where(ql.prop("geom.length", "<=", bolt_circle * 1.01))
).resolve(body)
radii = [math.hypot(e.get_center().x, e.get_center().y) for e in bolt_rims]
check("bolt-rim-count", len(bolt_rims) == 2 * BOLT_N, f"n={len(bolt_rims)} (expect {2 * BOLT_N})")
check("bolt-pcd", all(abs(r - PCD / 2.0) <= TOL for r in radii),
      f"axis-dist={[round(r, 3) for r in sorted(set(round(r, 3) for r in radii))]}")

# 4) 螺栓孔壁：N 张 Ø11 圆柱面（面积 = 2πr·t）
wall_area = math.pi * BOLT_D * T
bolt_walls = (
    ql.faces()
    .where(ql.prop("geom.type", "==", "CYLINDER"))
    .where(ql.prop("geom.area", ">=", wall_area * 0.99))
    .where(ql.prop("geom.area", "<=", wall_area * 1.01))
).resolve(body)
check("bolt-wall-count", len(bolt_walls) == BOLT_N, f"n={len(bolt_walls)} (expect {BOLT_N})")

# 5) 中心孔 Ø30：上下圆缘各 1 条
bore_circle = 2.0 * math.pi * BORE_D / 2.0
bore_rims = (
    ql.edges()
    .where(ql.prop("geom.type", "==", "CIRCLE"))
    .where(ql.prop("geom.length", ">=", bore_circle * 0.99))
    .where(ql.prop("geom.length", "<=", bore_circle * 1.01))
    .where(ql.prop("geom.center.x", ">=", -TOL))
    .where(ql.prop("geom.center.x", "<=", TOL))
    .where(ql.prop("geom.center.y", ">=", -TOL))
    .where(ql.prop("geom.center.y", "<=", TOL))
).resolve(body)
check("bore-rims", len(bore_rims) == 2, f"n={len(bore_rims)} z={[round(e.get_center().z, 2) for e in bore_rims]}")

# 6) 圆角面：TORUS 恰 3 张（根部 R3 + 外缘 R2 x2）
tori = ql.faces().where(ql.prop("geom.type", "==", "TORUS")).resolve(body)
check("fillet-tori", len(tori) == 3, f"n={len(tori)}")

# 7) 包回读 + step 非空
package_path = OUT_DIR / "flange_plate.scadpkg"
package = scad.read_product_package(package_path)
root = package.root_definition
check("package-reopen", root.definition_id == "flange-plate" and root.revision == "1.0.0"
      and root.content_hash == run.definition.content_hash,
      f"id={root.definition_id} rev={root.revision} hash==notebook:"
      f"{root.content_hash == run.definition.content_hash}")
step_path = OUT_DIR / "flange_plate.step"
check("step-nonempty", step_path.exists() and step_path.stat().st_size > 0,
      f"{step_path} size={step_path.stat().st_size if step_path.exists() else 0}")

print()
if failures:
    print(f"VERIFY FAILED: {failures}")
    sys.exit(1)
print("VERIFY OK: all checks passed")

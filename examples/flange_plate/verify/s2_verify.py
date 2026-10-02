"""Final geometry acceptance: bolt pattern + double fillet on the 8-hole flange.

    uv run python examples/flange_plate/verify/s2_verify.py

Criteria (BUILD_PLAN S2 contract; values read from the notebook's parameters):
  D1 single Solid + final volume in Pappus bracket +-1.5%
  D2 bolt_count hole walls: CYLINDER area pi*bolt_d*flange_t, axis-distance = PCD/2
  D3 phase: first hole at 0 deg; adjacent spacing = 360/n (>=2 units measured)
  D4 tori: root TORUS n=1 (area Pappus arc-centroid formula, z > flange_t);
           edge TORUS n=2 (same-radius formula, z <= flange_t)
  D5 S1 regression: bbox unchanged (x/y in +-od/2, z in [0, top]); boss top
     annulus and bore wall cards still resolve exactly 1
"""
import math
import sys
from pathlib import Path

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from simplecadapi import ql
from simplecadapi.runtime import run_notebook

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        failures.append(name)


run = run_notebook(Path(__file__).resolve().parents[1] / "flange_plate.py")
body = run.product.body
p = {name: float(run.values[name]) for name in (
    "FLANGE_OD", "FLANGE_T", "BOSS_OD", "BOSS_TOP_Z", "BORE_D",
    "BOLT_D", "BOLT_PCD", "BOLT_COUNT", "BOSS_FILLET_R", "EDGE_FILLET_R")}
od, t = p["FLANGE_OD"], p["FLANGE_T"]
boss_od, top, bore = p["BOSS_OD"], p["BOSS_TOP_Z"], p["BORE_D"]
bolt_d, pcd, n = p["BOLT_D"], p["BOLT_PCD"], int(p["BOLT_COUNT"])
r_root, r_edge = p["BOSS_FILLET_R"], p["EDGE_FILLET_R"]

# D1 volume bracket
v_base = math.pi / 4 * (od * od * t + boss_od * boss_od * (top - t) - bore * bore * top)
v_bolts = n * math.pi / 4 * bolt_d * bolt_d * t
# root fillet adds corner-fill ring (Pappus, centroid r = Rmaj - 2R/pi - fill offset)
a_fill = r_root * r_root - math.pi * r_root ** 2 / 4
v_root_add = 2 * math.pi * (boss_od / 2 + r_root - 2 * r_root / math.pi - 2 * 0.06) * a_fill
a_cut = r_edge * r_edge - math.pi * r_edge ** 2 / 4
v_edge_cut = 2 * 2 * math.pi * (od / 2 - r_edge) * a_cut
v_bracket = v_base - v_bolts + v_root_add - v_edge_cut
v = body.get_volume()
check("D1 volume in bracket", type(body).__name__ == "Solid" and v > 0
      and abs(v - v_bracket) / v_bracket < 0.015,
      f"volume={v:.3f} bracket={v_bracket:.3f} rel={abs(v - v_bracket) / v_bracket:.5f}")

# D2 bolt hole walls
a_hole = math.pi * bolt_d * t
walls = ql.faces().where(ql.and_(
    ql.prop("geom.type", "==", "CYLINDER"),
    ql.prop("geom.area", ">=", a_hole - 1.0), ql.prop("geom.area", "<=", a_hole + 1.0),
)).resolve(body)
radii = [math.hypot(f.get_center().x, f.get_center().y) for f in walls]
check("D2 bolt hole walls", len(walls) == n and all(abs(r - pcd / 2) < 0.05 for r in radii),
      f"n={len(walls)} want={n} radii={sorted(set(round(r, 3) for r in radii))} want_r={pcd / 2:.3f}")

# D3 phase + spacing (measure at least two units)
angles = sorted(round(math.degrees(math.atan2(f.get_center().y, f.get_center().x)) % 360.0, 2) for f in walls)
gaps = [round(b - a, 2) for a, b in zip(angles, angles[1:])]
check("D3 phase 0deg + equal spacing", angles and angles[0] < 0.01
      and len(set(gaps)) == 1 and abs(gaps[0] - 360.0 / n) < 0.01,
      f"phases={angles} gaps={gaps} want_gap={360.0 / n:.2f}")

# D4 torus cards
tori = ql.faces().where(ql.prop("geom.type", "==", "TORUS")).resolve(body)
a_root = 2 * math.pi * (boss_od / 2 + r_root - 2 * r_root / math.pi) * (math.pi * r_root / 2)
a_edge = 2 * math.pi * (od / 2 - r_edge + 2 * r_edge / math.pi) * (math.pi * r_edge / 2)
root_tori = [f for f in tori if f.get_center().z > t]
edge_tori = [f for f in tori if f.get_center().z <= t]
check("D4a root torus", len(root_tori) == 1 and abs(root_tori[0].get_area() - a_root) / a_root < 0.02,
      f"n={len(root_tori)} area={root_tori[0].get_area():.3f} want={a_root:.3f}")
check("D4b edge tori", len(edge_tori) == 2
      and all(abs(f.get_area() - a_edge) / a_edge < 0.02 for f in edge_tori),
      f"n={len(edge_tori)} areas={[f'{f.get_area():.3f}' for f in edge_tori]} want={a_edge:.3f}")

# D5 S1 regression
box = Bnd_Box()
box.SetGap(0.0)
BRepBndLib.AddOptimal_s(body.wrapped, box, useTriangulation=False)
xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
a_top = math.pi * ((boss_od / 2) ** 2 - (bore / 2) ** 2)
boss_top = ql.faces().where(ql.and_(
    ql.prop("geom.type", "==", "PLANE"),
    ql.prop("geom.center.z", ">=", top - 0.1), ql.prop("geom.center.z", "<=", top + 0.1),
    ql.prop("geom.area", ">=", a_top - 1.0), ql.prop("geom.area", "<=", a_top + 1.0),
)).resolve(body)
a_bore = math.pi * bore * top
bore_wall = ql.faces().where(ql.and_(
    ql.prop("geom.type", "==", "CYLINDER"),
    ql.prop("geom.area", ">=", a_bore - 1.0), ql.prop("geom.area", "<=", a_bore + 1.0),
)).resolve(body)
wants = ((xmin, -od / 2), (xmax, od / 2), (ymin, -od / 2), (ymax, od / 2), (zmin, 0.0), (zmax, top))
check("D5 S1 regression (bbox+boss top+bore wall cards)",
      all(abs(g - w) < 0.05 for g, w in wants) and len(boss_top) == 1 and len(bore_wall) == 1,
      f"bbox x[{xmin:.2f},{xmax:.2f}] y[{ymin:.2f},{ymax:.2f}] z[{zmin:.2f},{zmax:.2f}] "
      f"boss_top n={len(boss_top)} bore_wall n={len(bore_wall)}")

print(f"S2 verifier: {'ALL PASS' if not failures else 'FAILED ' + str(failures)}")
sys.exit(1 if failures else 0)

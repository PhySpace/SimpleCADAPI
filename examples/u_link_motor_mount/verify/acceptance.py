"""Acceptance checks for the U-link body, the shell and their assembly.

    uv run python examples/u_link_motor_mount/verify/acceptance.py

Loads the three notebooks with ``run_notebook`` (cell-cached) and checks the
build-plan contracts of every stage on the cell values: the sweep (S1), the
split plane (S2), the motor pockets (S3), the finished body (S4, S13), the
shell (S11, S12), the assembly (S10) and the parameter guard chain (S6).
Point classification stands in for face bookkeeping wherever the kernel's
face split is not stable (boss rings, overlapping arcs).
"""

import math
import sys
from pathlib import Path

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN, TopAbs_ON

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from dimensions import (  # noqa: E402
    DIMS,
    TAG_BACK,
    TAG_MOUNT_LEFT,
    TAG_MOUNT_RIGHT,
    TAG_SHELL_RIM,
    ULinkDimensions,
)

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        failures.append(name)


def bbox_of(solid: scad.Solid) -> tuple[float, ...]:
    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(solid.wrapped, box, useTriangulation=False)
    return box.Get()


def classifier(solid: scad.Solid):
    """Point → is it material (in or on) of *solid*."""
    cls = BRepClass3d_SolidClassifier(solid.wrapped)

    def inside(x: float, y: float, z: float) -> bool:
        cls.Perform(gp_Pnt(x, y, z), 1e-7)
        return cls.State() in (TopAbs_IN, TopAbs_ON)

    return inside


def faces(solid: scad.Solid, *predicates) -> list:
    return ql.faces().where(ql.and_(*predicates)).resolve(solid)


def between(key: str, lo: float, hi: float) -> list:
    return [ql.prop(key, ">=", lo), ql.prop(key, "<=", hi)]


body_run = run_notebook(HERE / "u_link.py")
shell_run = run_notebook(HERE / "shell.py")
assembly_run = run_notebook(HERE / "u_link_motor_mount.py")
V, S = body_run.values, shell_run.values

L, D, R_C = DIMS.L, DIMS.D, DIMS.r_corner
r, rp, fr = DIMS.r, DIMS.pocket_r, DIMS.fillet_r
BY, FY = DIMS.back_y, DIMS.floor_y
FB, FT = DIMS.shell_bottom_y, DIMS.boss_tip_y  # shell floor band [bottom, top]
HYP = (DIMS.rib_len ** 2 + DIMS.boss_h ** 2) ** 0.5  # gusset hypotenuse
CHAMFER_FACE = HYP * DIMS.gusset_chamfer * 2 ** 0.5

rod, split, pockets = V["u_rod"], V["split_plane"], V["motor_pockets"]
body_part, shell_part, assembly = body_run.product, shell_run.product, assembly_run.product
assert isinstance(body_part, scad.Part) and isinstance(shell_part, scad.Part)
assert isinstance(assembly, scad.Assembly)
body, shell = body_part.body, shell_part.body
in_body, in_shell = classifier(body), classifier(shell)

# ---- S1: U-rod sweep ----
centerline = 2.0 * (D - R_C) + (L - 2.0 * R_C) + math.pi * R_C
pappus = math.pi * r * r * centerline
check("S1 volume = Pappus", abs(rod.get_volume() - pappus) / pappus < 0.005,
      f"volume={rod.get_volume():.3f} pappus={pappus:.3f}")
caps = sorted(faces(rod, ql.prop("geom.type", "==", "PLANE"), *between("geom.center.y", D - 0.1, D + 0.1)),
              key=lambda f: f.get_center().x)
check("S1 end caps", len(caps) == 2
      and all(abs(f.get_area() - math.pi * r * r) < 1.0 for f in caps)
      and all(abs(f.get_center().x - s * L / 2.0) < 0.05 for f, s in zip(caps, (-1, 1))),
      f"n={len(caps)}")
b = bbox_of(rod)
want = (-(L / 2 + r), -r, -r, L / 2 + r, D, r)
check("S1 bbox", all(abs(g - w) < 0.05 for g, w in zip(b, want)), [round(v, 2) for v in b])

# ---- S2: split plane at back_y ----
a_below = math.pi * r * r - (r * r * math.acos(BY / r) - BY * math.sqrt(r * r - BY * BY))
lo = (L - 2.0 * R_C) * a_below
hi = lo + 2.0 * (math.pi * R_C / 2.0) * a_below
removed = rod.get_volume() - split.get_volume()
check("S2 removed volume", lo < removed < hi, f"removed={removed:.3f} in ({lo:.3f},{hi:.3f})")
backs = faces(split, ql.prop("geom.type", "==", "PLANE"), ql.prop("geom.normal.y", "<=", -0.999),
              *between("geom.center.y", BY - 0.05, BY + 0.05))
chord_w = 2.0 * math.sqrt(r * r - BY * BY)
check("S2 back face", len(backs) == 1 and backs[0].get_area() >= 0.9 * (L - 2.0 * R_C) * chord_w,
      f"n={len(backs)}")
b = bbox_of(split)
check("S2 bbox y = [back_y, D]", abs(b[1] - BY) < 0.05 and abs(b[4] - D) < 0.05, (b[1], b[4]))

# ---- S3: motor pockets ----
depth = D - FY
expect = split.get_volume() - 2.0 * math.pi * rp * rp * depth
check("S3 pocket volume", abs(pockets.get_volume() - expect) / expect < 0.001,
      f"{pockets.get_volume():.3f} expect {expect:.3f}")
up_plane = [ql.prop("geom.type", "==", "PLANE"), ql.prop("geom.normal.y", ">=", 0.999)]
floors = sorted(faces(pockets, *up_plane, *between("geom.center.y", FY - 0.1, FY + 0.1)),
                key=lambda f: f.get_center().x)
check("S3 floors", len(floors) == 2
      and all(abs(f.get_area() - math.pi * rp * rp) < 0.5 for f in floors)
      and all(abs(f.get_center().x - s * L / 2.0) < 0.05 for f, s in zip(floors, (-1, 1))),
      f"n={len(floors)}")
rims = faces(pockets, *up_plane, *between("geom.center.y", D - 0.1, D + 0.1))
wall_area = 2.0 * math.pi * rp * depth
walls = faces(pockets, ql.prop("geom.type", "==", "CYLINDER"),
              *between("geom.area", wall_area * 0.98, wall_area * 1.02))
check("S3 rims + walls", len(rims) == 2 and len(walls) == 2
      and all(abs(f.get_area() - math.pi * (r * r - rp * rp)) < 0.5 for f in rims),
      f"rims={len(rims)} walls={len(walls)}")

# ---- S4: finished body ----
br, hr = DIMS.boss_d / 2.0, DIMS.boss_hole_d / 2.0
boss_net = 2 * (math.pi * br ** 2 * DIMS.boss_h - math.pi * hr ** 2 * DIMS.boss_hole_depth)
gusset_v = 8 * 0.5 * DIMS.rib_len * DIMS.boss_h * DIMS.rib_t
# S14 实测系数 1.046（弧壁外表面 > 内表面）
window_v = 8 * DIMS.cable_w_w * DIMS.cable_w_h * (DIMS.thickness / 2.0) * 1.046
base_v = pockets.get_volume() + boss_net + gusset_v - window_v
check("S4 volume band", base_v - 180.0 < body.get_volume() < base_v + 180.0,
      f"{body.get_volume():.3f} band=({base_v - 180:.1f},{base_v + 180:.1f})")
b3, b4 = bbox_of(pockets), bbox_of(body)
check("S4 bbox (boss hang-down)", all(abs(b3[i] - b4[i]) < 0.05 for i in (0, 2, 3, 4, 5))
      and abs(b4[1] - FT) < 0.05, [round(v, 2) for v in b4])
for tag, want_x in ((TAG_MOUNT_LEFT, -L / 2.0), (TAG_MOUNT_RIGHT, L / 2.0)):
    hit = faces(body, ql.tag(tag))
    check(f"S4 {tag}", len(hit) == 1 and abs(hit[0].get_center().x - want_x) < 0.05
          and abs(hit[0].get_center().y - FY) < 0.05, f"n={len(hit)}")
floors = faces(body, *up_plane, *between("geom.center.y", FY - 0.1, FY + 0.1))
area_lo, area_hi = math.pi * (rp - 2.0 * fr) ** 2, math.pi * rp * rp
check("S4 floors planar", len(floors) == 2 and all(area_lo < f.get_area() < area_hi for f in floors),
      [round(f.get_area(), 2) for f in floors])
torus = faces(body, ql.prop("geom.type", "==", "TORUS"))
chamfers = faces(body, ql.prop("geom.type", "==", "PLANE"),
                 *between("geom.area", 0.9 * CHAMFER_FACE, 1.3 * CHAMFER_FACE))
check("S4 fillet + chamfer landed", len(torus) >= 2 and len(chamfers) >= 14,
      f"torus={len(torus)} chamfer_faces={len(chamfers)}")
back = faces(body, ql.tag(TAG_BACK))
check("S4 back face tagged", len(back) == 1 and abs(back[0].get_center().y - BY) < 0.05,
      f"n={len(back)}")
hole_area = 2 * math.pi * hr * DIMS.boss_hole_depth
hole_walls = faces(body, ql.prop("geom.type", "==", "CYLINDER"),
                   *between("geom.area", hole_area * 0.95, hole_area * 1.05))
ring_ok = True
for sx in (-1, 1):
    for deg in (20, 70, 110, 160, 200, 250, 290, 340):  # 避开 4 筋方向
        a = math.radians(deg)
        x0 = sx * DIMS.boss_x
        ring_ok = ring_ok and in_body(x0 + (br - 0.25) * math.cos(a), BY - 0.5, (br - 0.25) * math.sin(a))
        ring_ok = ring_ok and not in_body(x0 + (br + 0.8) * math.cos(a), BY - 0.5, (br + 0.8) * math.sin(a))
check("S4 boss rings + blind holes", ring_ok and len(hole_walls) == 2,
      f"ring={ring_ok} hole_walls={len(hole_walls)}")

# ---- S13: cable windows ----
in_pockets = classifier(pockets)


def open_towards(phase_deg: float) -> bool:
    """A ray from both pocket axes leaves the wall by r=16 and stays in air."""
    a = math.radians(phase_deg)
    for y in (13.0, 15.0, 17.0):
        for xc in (-L / 2, L / 2):
            ray = [in_pockets(xc + d * math.cos(a), y, d * math.sin(a))
                   for d in (12.3 + 0.25 * i for i in range(46))]
            last = max((i for i, m in enumerate(ray) if m), default=-1)
            if 12.3 + 0.25 * last > 16.0 or any(ray[last + 1:]):
                return False
    return True


phases = [DIMS.cable_w_phase + 90.0 * k for k in range(4)]
check("S13 window phases face open air", all(open_towards(p) for p in phases)
      and not (open_towards(0.0) and open_towards(180.0)), phases)
y_mid, mid_r = FY + DIMS.cable_w_off + DIMS.cable_w_h / 2.0, 13.5
ray = lambda xc, deg, y: (xc + mid_r * math.cos(math.radians(deg)), y,  # noqa: E731
                          mid_r * math.sin(math.radians(deg)))
opens = [not in_body(*ray(xc, p, y_mid)) for xc in (-L / 2, L / 2) for p in phases]
walls_ok = [in_body(*ray(xc, p - 45.0, y_mid)) for xc in (-L / 2, L / 2) for p in phases]
y_lo = FY + DIMS.cable_w_off
sill = [in_body(*ray(xc, phases[0], y_lo - 0.3)) and not in_body(*ray(xc, phases[0], y_lo + 0.3))
        for xc in (-L / 2, L / 2)]
check("S13 windows open (8)", all(opens), opens)
check("S13 inter-window walls", all(walls_ok), walls_ok)
check("S13 window sill at floor + cable_w_off", all(sill), sill)

# ---- S11/S12: shell ----
bottoms = faces(shell, ql.prop("geom.type", "==", "PLANE"), ql.prop("geom.normal.y", "<=", -0.999),
                *between("geom.center.y", FB - 0.1, FB + 0.1), ql.prop("geom.area", ">=", 500.0))
no_below = all(not in_shell(x, FB - 0.8, z) for x in (0.0, 30.0, 48.0) for z in (0.0, 8.0))
check("S11 flat bottom", len(bottoms) == 1 and bottoms[0].get_area() > 1000.0
      and abs(bbox_of(shell)[1] - FB) < 0.05 and no_below, f"n={len(bottoms)}")
slab = in_shell(0.0, (FB + FT) / 2.0, 8.0) and in_shell(-20.0, (FB + FT) / 2.0, 0.0)
cavity = not in_shell(0.0, FT + 1.5, 8.0) and not in_shell(20.0, (FT + BY) / 2.0, 0.0)
check("S11 floor slab + cavity", slab and cavity, f"slab={slab} cavity={cavity}")
cones = faces(shell, ql.prop("geom.type", "==", "CONE"),
              *between("geom.center.y", FB - 0.1, FB + S["CSINK_DEPTH"] + 0.1))
through = [f for f in faces(shell, ql.prop("geom.type", "==", "CYLINDER"), *between(
    "geom.area", 2 * math.pi * hr * (DIMS.wall_t - S["CSINK_DEPTH"]) * 0.7,
    2 * math.pi * hr * DIMS.wall_t * 1.1))
    if abs(abs(f.get_center().x) - DIMS.boss_x) < 0.3 and abs(f.get_center().z) < 0.3]
check("S11 countersinks + through holes", len(cones) == 2 and len(through) == 2,
      f"cones={len(cones)} holes={len(through)}")
notch_xc = L / 2.0 - R_C + 1.45 * r
notch_mid = FT + (BY - FT) / 2.0
open_ok = all(not in_shell(sx * notch_xc, notch_mid, 0.0) for sx in (-1, 1))
side_ok = all(in_shell(sx * 49.5, notch_mid, S["NOTCH_W"] / 2 + 3.5) for sx in (-1, 1))
check("S11 cable notches", open_ok and side_ok, f"open={open_ok} side={side_ok}")
check("S11 slot floor to back face = wall_t", abs(FY - BY - DIMS.wall_t) < 1e-9, FY - BY)
check("S11 rim tagged", len(faces(shell, ql.tag(TAG_SHELL_RIM))) >= 1)

blends = faces(shell, ql.prop("geom.type", "==", "TORUS"))
rim_cyl = faces(shell, ql.prop("geom.type", "==", "CYLINDER"),
                *between("geom.center.y", FB - 0.05, FB + S["SAFE_FILLET_R"] + 0.1),
                ql.prop("geom.area", ">=", 10.0))
check("S12 bottom rim fillet", len(blends) >= 4 and len(rim_cyl) >= 2,
      f"torus={len(blends)} rim_cyl={len(rim_cyl)}")
notch_torus = [f for f in blends if abs(abs(f.get_center().x) - 37.3) < 6.0
               and f.get_center().y > FT + 0.5]
notch_cyl = faces(shell, ql.prop("geom.type", "==", "CYLINDER"), ql.prop("geom.area", ">=", 100.0),
                  *between("geom.center.y", FT + 0.5, BY + 0.1))
check("S12 notch mouth fillets", len(notch_torus) >= 2 and len(notch_cyl) >= 2,
      f"torus={len(notch_torus)} cyl={len(notch_cyl)}")


def band_x(y: float) -> float | None:
    """First material x beyond the notch centre (the wall moves out with height)."""
    for x in range(int(notch_xc) + 2, int(notch_xc) + 12):
        if in_shell(float(x), y, 0.0):
            return float(x)
    return None


sills = band_x(FT + 0.15) is not None and band_x(BY - 0.15) is not None
mouth = not in_shell(float(int(notch_xc) + 9), (FT + BY) / 2.0, 0.0)
check("S12 sills intact, mouth open", sills and mouth, f"sills={sills} mouth={mouth}")

# ---- S10: assembly ----
mid_band = BY - DIMS.boss_h / 2.0
leaks = [(x, z) for x in (-30.0, -18.0, -8.0, 0.0, 8.0, 18.0, 30.0) for z in (0.0, 5.0, 10.0, -10.0)
         if all((x - sx * DIMS.boss_x) ** 2 + z ** 2 > (br + DIMS.rib_len + 1.0) ** 2 for sx in (-1, 1))
         and in_body(x, mid_band, z)]
contour = in_shell(0.0, mid_band, r - DIMS.wall_t / 2.0) \
    and not in_shell(0.0, mid_band, r - DIMS.wall_t - 2.0)
check("S10 band open under the split + shell contour wall", not leaks and contour,
      f"leaks={leaks} contour={contour}")
bad = [(x, y, z) for x in range(-52, 53, 4) for z in (0.5 * k for k in range(-29, 30, 3))
       for y in (FB - 0.4, FT + 0.4, BY - 0.4, 4.0)
       if in_shell(x, y, z) and in_body(x, y, z)]
check("S10 body and shell do not interfere", not bad, f"n={len(bad)} {bad[:3]}")
report = scad.inspect_assembly_constraints_rconstraintreport(assembly=assembly)
check("S10 assembly solved", assembly.component_ids() == ("body", "shell") and report.solved
      and all(x.within_tolerance for x in report.residuals), assembly.component_ids())

# ---- S6: parameter guard chain ----
BAD_PARAMETERS = (
    {"d_motor": 40.0}, {"r_corner": 15.0}, {"r_corner": 20.0}, {"fillet_r": 1.5}, {"L": 34.0},
    {"back_cut_frac": 1.0}, {"back_cut_frac": 0.4}, {"d_motor": 15.0}, {"d_motor": 17.0},
    {"boss_h": 5.5}, {"rib_len": 8.0}, {"boss_hole_depth": 4.7}, {"wall_t": 5.1},
    {"boss_x": 17.0}, {"cable_w_off": 2.9}, {"cable_w_off": 5.1},
    {"cable_w_off": 5.0, "cable_w_h": 5.0}, {"cable_w_w": 19.5},
)
unguarded = []
for changes in BAD_PARAMETERS:
    try:
        ULinkDimensions(**changes).check()
    except AssertionError:
        continue
    unguarded.append(changes)
DIMS.check()
check("S6 guard chain rejects every bad set", not unguarded, unguarded)

print(f"acceptance: {'ALL PASS' if not failures else 'FAILED ' + str(failures)}")
sys.exit(1 if failures else 0)

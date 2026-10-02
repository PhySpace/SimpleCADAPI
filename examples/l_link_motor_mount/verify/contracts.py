"""Stage contracts of the l_link parts (S1 .. S9), checked on notebook cell values.

``acceptance.py`` runs the notebooks and hands each ``check_sN`` the cell values that end stage N
(``acceptance.STAGES``) together with the parameter dict.  Expectations are derived from the parameters
and the requirement geometry written here, never from the solid or from the notebooks' tool builders.
Faces are named once, by the last cell of each part, so a stage before that is checked without tags
(``tags=None``).  Diagnostic only: nothing here is used inside the model.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.inspect import brep
from simplecadapi.product.connector import resolve_item_connector_placement
from simplecadapi.product.placement import inverse_placement

EXAMPLE_DIR = Path(__file__).resolve().parents[1]
if str(EXAMPLE_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_DIR))

import dimensions as dm  # noqa: E402
from dimensions import PlatePreset  # noqa: E402

# The guard chain each part notebook runs (body; shell = body + shell; plate = all three).
BODY = SimpleNamespace(params=dm.params, assert_params=dm.check_body)
SHELL = SimpleNamespace(params=dm.params, assert_params=dm.check_shell)
PLATE = SimpleNamespace(params=dm.params, assert_params=dm.check_plate)


def tight_bbox(solid) -> tuple:
    """Exact bbox (AddOptimal, no gap). brep.bounding_box carries a ~0.12 tolerance
    gap (s1_hypothesis H4) and cannot discriminate 0.05 mm errors."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(solid.wrapped, box, useTriangulation=False)
    return box.Get()


def precise_volume(solid, eps: float = 1e-9) -> float:
    """GProp volume with an explicit tolerance. Solid.get_volume() (default GProp) is off by ~0.1 mm^3
    per cylinder-cylinder BSpline trim (s8 finding: radial pilot through a disk rim)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid.wrapped, props, eps)
    return props.Mass()


def point_classifier(solid, strict: bool = False):
    """inside(x,y,z) -> bool (IN or ON; strict=True: IN only). Sampling classifier (U-link
    lesson: sample interference/emptiness instead of intersect_rsolid, which can fail on
    touching faces)."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON

    cls = BRepClass3d_SolidClassifier(solid.wrapped)
    states = (TopAbs_IN,) if strict else (TopAbs_IN, TopAbs_ON)

    def inside(x: float, y: float, z: float) -> bool:
        cls.Perform(gp_Pnt(x, y, z), 1e-7)
        return cls.State() in states
    return inside


def grid(lo: tuple, hi: tuple, step: float, offset: float = 0.3):
    """Regular sample grid; offset keeps samples off datum planes (e.g. y=7.5)."""
    axes = [[a + offset + k * step for k in range(int((b - a - offset) / step) + 1)]
            for a, b in zip(lo, hi)]
    return [(x, y, z) for x in axes[0] for y in axes[1] for z in axes[2]]


def ring(axis: str, center: tuple, radius: float, n: int = 12):
    """n points on a circle of `radius` around an axis through `center` (axis in 'x'|'y')."""
    import math

    cx, cy, cz = center
    pts = []
    for k in range(n):
        a = 2.0 * math.pi * k / n
        u, v = radius * math.cos(a), radius * math.sin(a)
        pts.append((cx, cy + u, cz + v) if axis == "x" else (cx + u, cy, cz + v))
    return pts


class Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def __call__(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
        if not ok:
            self.failures.append(name)
        return ok

    def skip(self, name: str, why: str) -> None:
        print(f"SKIP {name} ({why})")


# ====================================================================================================
# S1 verifier: L-rod sweep against the REQUIREMENTS/BUILD_PLAN S1 contract.
#
# Criteria (expectations derived from p, never from the solid):
#   C1 single valid Solid, volume == pi r^2 * centerline (Pappus) within 0.5%
#   C2 exactly 1 cap PLANE +Y @ (0, D, 0) and exactly 1 cap PLANE +X @ (x_end, 0, 0),
#      each area pi r^2; exactly 2 planar faces in total (no stray flats)
#   C3 tight bbox == [-r, x_end] x [-r, D] x [+-r] within 0.05
#   C4 assert_params rejects r_corner<=r, r_corner>=D, d_motor/2>=D (and accepts defaults)
# ====================================================================================================

def expected_x_end(p: dict) -> float:
    return p["L"] + (p["D"] - p["d_motor"] / 2.0)


def check_s1(rod, p: dict) -> list[str]:
    check = Checks()
    r = p["rod_d"] / 2.0
    x_end = expected_x_end(p)
    area = math.pi * r * r

    info = brep.inspect_shape_rbrepinspection(shape=rod.wrapped)
    vol = rod.get_volume()
    centerline = (p["D"] - p["r_corner"]) + math.pi * p["r_corner"] / 2.0 + (x_end - p["r_corner"])
    pappus = area * centerline
    check("C1 solid+valid+Pappus",
          type(rod).__name__ == "Solid" and info.valid and abs(vol - pappus) / pappus < 0.005,
          f"valid={info.valid} volume={vol:.3f} pappus={pappus:.3f}")

    arm = _plane("y", p["D"]).resolve(rod)
    run = _plane("x", x_end).resolve(rod)
    planes = ql.faces().where(ql.prop("geom.type", "==", "PLANE")).resolve(rod)
    ok = len(arm) == 1 and len(run) == 1 and len(planes) == 2
    if ok:
        ca, cr = arm[0].get_center(), run[0].get_center()
        ok = (abs(ca.x) < 0.05 and abs(ca.z) < 0.05 and abs(cr.y) < 0.05 and abs(cr.z) < 0.05
              and abs(arm[0].get_area() - area) < 0.5 and abs(run[0].get_area() - area) < 0.5)
    check("C2 end caps", ok, f"arm={len(arm)} run={len(run)} planes={len(planes)}")

    bb = tight_bbox(rod)
    want = (-r, -r, -r, x_end, p["D"], r)
    check("C3 bbox", all(abs(g - w) < 0.05 for g, w in zip(bb, want)),
          f"got={[round(v, 3) for v in bb]} want={[round(v, 3) for v in want]}")
    return check.failures


def check_s1_guards(l_link=BODY) -> list[str]:
    check = Checks()
    p0 = l_link.params()
    r = p0["rod_d"] / 2.0

    def rejects(**over) -> bool:
        try:
            l_link.assert_params({**p0, **over})
        except AssertionError:
            return True
        return False

    try:
        l_link.assert_params(p0)
        accepts = True
    except AssertionError as exc:
        accepts = False
        print(f"  defaults rejected: {exc}")
    check("C4 guards", accepts and rejects(r_corner=r) and rejects(r_corner=p0["D"])
          and rejects(d_motor=2.0 * p0["D"]),
          f"accepts_defaults={accepts} r_corner=r:{rejects(r_corner=r)} "
          f"r_corner=D:{rejects(r_corner=p0['D'])} d_motor=2D:{rejects(d_motor=2.0 * p0['D'])}")
    return check.failures


# ====================================================================================================
# S2 verifier: two motor pockets + named mount faces (upper-part body before split).
#
# Criteria (expectations from p; rp = (rod_d-thickness)/2, fy = d_motor/2, fx = L-plate_t):
#   C1 single valid Solid; volume == V_S1 - pi rp^2 * ((D-fy) + (x_end-fx)) within 0.5 mm^3
#   C2 left floor: exactly 1 PLANE +Y @ (0, fy, 0), area pi rp^2;
#      right floor: exactly 1 PLANE +X @ (fx, 0, 0), area pi rp^2; normals orthogonal (|dot| < 1e-6)
#   C3 depths: axis samples empty from floor+e to cap-e, solid at floor-e (left 10.5, right 15.5);
#      pocket radius: ring rp-e empty / rp+e solid at two depths per pocket
#   C4 walls: cap annulus areas pi (r^2 - rp^2) (wall = thickness/2 at both caps);
#      right wall ring r-e solid over the whole pocket (straight tube);
#      left pocket minimum radial wall >= wall_t (torus thinning, s2_hypothesis H4 = 2.13)
#   C5 tags: TAG_MOUNT_LEFT / TAG_MOUNT_RIGHT each exactly 1 face and coincide with the C2 faces
# ====================================================================================================

E = 0.05
WALL_T_MIN = 2.0  # wall_t (REQUIREMENTS: standard wall); left-pocket torus thinning floor


def _plane(axis: str, value: float, sign: float = 1.0, extra: tuple = ()):
    return ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop(f"geom.normal.{axis}", ">=" if sign > 0 else "<=", 0.999 * sign),
        ql.prop(f"geom.center.{axis}", ">=", value - 0.05),
        ql.prop(f"geom.center.{axis}", "<=", value + 0.05), *extra))


def geom(p: dict) -> dict:
    r = p["rod_d"] / 2.0
    rp = (p["rod_d"] - p["thickness"]) / 2.0
    return {"r": r, "rp": rp, "fy": p["d_motor"] / 2.0, "fx": p["L"] - p["plate_t"],
            "xe": p["L"] + (p["D"] - p["d_motor"] / 2.0)}


def left_min_wall(inside, g: dict, D: float) -> float:
    rp, fy = g["rp"], g["fy"]
    best = 99.0
    for k in range(8):
        y = fy + E + k * (D - fy - 2 * E) / 7
        for j in range(24):
            a = 2 * math.pi * j / 24
            t = rp + E
            while inside(t * math.cos(a), y, t * math.sin(a)) and t < rp + 20:
                t += 0.01
            best = min(best, t - rp)
    return best


def check_s2(body, p: dict, v_s1: float, tag_left: str | None, tag_right: str | None) -> list[str]:
    check = Checks()
    g = geom(p)
    r, rp, fy, fx, xe = g["r"], g["rp"], g["fy"], g["fx"], g["xe"]
    disc = math.pi * rp * rp

    info = brep.inspect_shape_rbrepinspection(shape=body.wrapped)
    vol = body.get_volume()
    want = v_s1 - disc * ((p["D"] - fy) + (xe - fx))
    check("C1 solid+valid+volume", type(body).__name__ == "Solid" and info.valid
          and abs(vol - want) < 0.5, f"valid={info.valid} volume={vol:.3f} want={want:.3f}")

    fl, fr = _plane("y", fy).resolve(body), _plane("x", fx).resolve(body)
    ok = len(fl) == 1 and len(fr) == 1
    detail = f"left={len(fl)} right={len(fr)}"
    if ok:
        cl, cr = fl[0].get_center(), fr[0].get_center()
        nl, nr = fl[0].get_normal_at(), fr[0].get_normal_at()
        dot = nl.x * nr.x + nl.y * nr.y + nl.z * nr.z
        ok = (abs(cl.x) < E and abs(cl.z) < E and abs(cr.y) < E and abs(cr.z) < E
              and abs(fl[0].get_area() - disc) < 0.5 and abs(fr[0].get_area() - disc) < 0.5
              and abs(dot) < 1e-6)
        detail += (f" areas=({fl[0].get_area():.3f},{fr[0].get_area():.3f}) want={disc:.3f} "
                   f"dot={dot:.2e}")
    check("C2 mount floors", ok, detail)

    inside = point_classifier(body)
    left_axis = (not any(inside(0.0, y, 0.0) for y in (fy + E, (fy + p["D"]) / 2, p["D"] - E))
                 and inside(0.0, fy - E, 0.0))
    right_axis = (not any(inside(x, 0.0, 0.0) for x in (fx + E, (fx + xe) / 2, xe - E))
                  and inside(fx - E, 0.0, 0.0))
    radius_ok = all(
        all(not inside(*q) for q in ring(ax, c, rp - E)) and all(inside(*q) for q in ring(ax, c, rp + E))
        for ax, c in (("y", (0.0, fy + 1, 0.0)), ("y", (0.0, p["D"] - 1, 0.0)),
                      ("x", (fx + 1, 0.0, 0.0)), ("x", (xe - 1, 0.0, 0.0))))
    check("C3 depths+radius", left_axis and right_axis and radius_ok,
          f"left_axis={left_axis} right_axis={right_axis} radius={radius_ok} "
          f"depth_left={p['D'] - fy:.2f} depth_right={xe - fx:.2f}")

    annulus = math.pi * (r * r - rp * rp)
    cap_l, cap_r = _plane("y", p["D"]).resolve(body), _plane("x", xe).resolve(body)
    caps_ok = (len(cap_l) == 1 and len(cap_r) == 1
               and abs(cap_l[0].get_area() - annulus) < 0.5 and abs(cap_r[0].get_area() - annulus) < 0.5)
    right_wall = all(all(inside(*q) for q in ring("x", (x, 0.0, 0.0), r - E, n=24))
                     for x in (fx + E, (fx + xe) / 2, xe - E))
    min_wall = left_min_wall(inside, g, p["D"])
    check("C4 walls", caps_ok and right_wall and min_wall >= WALL_T_MIN,
          f"caps={len(cap_l)},{len(cap_r)} annulus_want={annulus:.3f} right_wall={right_wall} "
          f"left_min_wall={min_wall:.2f}")

    if tag_left is None or tag_right is None:
        check.skip("C5 tags", "stage not named")
    else:
        tl = ql.faces().where(ql.tag(tag_left)).resolve(body)
        tr = ql.faces().where(ql.tag(tag_right)).resolve(body)
        ok = len(tl) == 1 and len(tr) == 1 and len(fl) == 1 and len(fr) == 1
        if ok:
            ctl, ctr = tl[0].get_center(), tr[0].get_center()
            ok = (abs(ctl.y - fy) < E and abs(ctl.x) < E and abs(ctr.x - fx) < E and abs(ctr.y) < E)
        check("C5 tags", ok, f"{tag_left}={len(tl)} {tag_right}={len(tr)}")
    return check.failures


# ====================================================================================================
# S3 verifier: "l" split of the pocketed rod into upper blank + shell blank.
#
# Criteria (by = r(2 back_cut_frac - 1), x_a = split_arc_frac L, x_b = split_end_frac L, Rs = x_b - x_a,
# arc center (x_a, by - Rs)):
#   C1 upper & shell single valid Solids; V_up + V_sh == V_S2 within 0.5
#   C2 interface: upper has exactly 1 PLANE -Y @ y=by (center.x < x_a), 1 CYLINDER in the arc window,
#      1 PLANE -X @ x=x_b; shell has the mirrored +Y / CYLINDER / +X faces, exactly 1 each
#   C3 arc: samples at Rs-e from the arc center (angles 15/45/75 deg, z in {0, +-8}) are shell,
#      at Rs+e are upper (bend toward -Y, tangent at both ends)
#   C4 shell extent: tight bbox y_max = by, x_max = x_b, y_min = -r (round bottom kept), z = +-r;
#      upper tight bbox == S2 bbox
#   C5 upper collar intact for x >= x_b: rings (r-e, rp+e, axis point before mount face) all upper;
#      both mount tags exactly 1 on upper
#   C6 partition on a 2 mm grid: no sample strictly IN both; every S2 sample in upper or shell
#   C7 guards: rejects x_b >= L-plate_t-wall_t, x_a >= x_b, x_a <= r_corner+2, Rs > by+r, arc bottom < -(r-wall_t)+1,
#      back_cut_frac 1.0, left floor < by+wall_t; accepts defaults
# ====================================================================================================

def split_geom(p: dict) -> dict:
    r = p["rod_d"] / 2.0
    by = r * (2.0 * p["back_cut_frac"] - 1.0)
    xa, xb = p["split_arc_frac"] * p["L"], p["split_end_frac"] * p["L"]
    return {"r": r, "rp": (p["rod_d"] - p["thickness"]) / 2.0, "by": by, "xa": xa, "xb": xb,
            "rs": xb - xa, "cx": xa, "cy": by - (xb - xa), "fx": p["L"] - p["plate_t"],
            "xe": p["L"] + (p["D"] - p["d_motor"] / 2.0)}


def _bend(g):
    # the bend is the only Z-axis cylinder whose mid normal points diagonally in XY (±(1,1,0)/√2 at 45°);
    # rod skin / right pocket (X axis, n.x = 0) and left pocket (Y axis, n.y = 0) can land in the center window
    return ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "CYLINDER"),
        ql.prop("geom.normal.z", ">=", -0.05), ql.prop("geom.normal.z", "<=", 0.05),
        ql.or_(ql.prop("geom.normal.x", ">=", 0.3), ql.prop("geom.normal.x", "<=", -0.3)),
        ql.or_(ql.prop("geom.normal.y", ">=", 0.3), ql.prop("geom.normal.y", "<=", -0.3)),
        ql.prop("geom.center.x", ">=", g["xa"] - 0.5), ql.prop("geom.center.x", "<=", g["xb"] + 0.5),
        ql.prop("geom.center.y", ">=", g["cy"] - 0.5), ql.prop("geom.center.y", "<=", g["by"] + 0.5)))


def check_s3(upper, shell, s2, p: dict, tags: tuple | None) -> list[str]:
    check = Checks()
    g = split_geom(p)
    r, by, xa, xb = g["r"], g["by"], g["xa"], g["xb"]

    iu = brep.inspect_shape_rbrepinspection(shape=upper.wrapped)
    ish = brep.inspect_shape_rbrepinspection(shape=shell.wrapped)
    vu, vs, v2 = upper.get_volume(), shell.get_volume(), s2.get_volume()
    check("C1 solids+volume sum", type(upper).__name__ == "Solid" and type(shell).__name__ == "Solid"
          and iu.valid and ish.valid and abs(vu + vs - v2) < 0.5,
          f"valid={iu.valid},{ish.valid} upper={vu:.3f} shell={vs:.3f} sum={vu + vs:.3f} s2={v2:.3f}")

    left_of_xa = (ql.prop("geom.center.x", "<", xa),)
    counts = {
        "up_flat": len(_plane("y", by, -1, left_of_xa).resolve(upper)),
        "up_bend": len(_bend(g).resolve(upper)),
        "up_drop": len(_plane("x", xb, -1).resolve(upper)),
        "sh_flat": len(_plane("y", by, 1, left_of_xa).resolve(shell)),
        "sh_bend": len(_bend(g).resolve(shell)),
        "sh_drop": len(_plane("x", xb, 1).resolve(shell)),
    }
    check("C2 interface faces", all(n == 1 for n in counts.values()), str(counts))

    in_u, in_s = point_classifier(upper), point_classifier(shell)
    arc_ok = True
    for deg in (15.0, 45.0, 75.0):
        a = math.radians(deg)
        for z in (0.0, 8.0, -8.0):
            lo = (g["cx"] + (g["rs"] - E) * math.cos(a), g["cy"] + (g["rs"] - E) * math.sin(a), z)
            hi = (g["cx"] + (g["rs"] + E) * math.cos(a), g["cy"] + (g["rs"] + E) * math.sin(a), z)
            arc_ok &= in_s(*lo) and not in_u(*lo) and in_u(*hi) and not in_s(*hi)
    check("C3 arc sides", arc_ok)

    bs, bu, b2 = tight_bbox(shell), tight_bbox(upper), tight_bbox(s2)
    shell_ok = (abs(bs[4] - by) < E and abs(bs[3] - xb) < E and abs(bs[1] + r) < E
                and abs(bs[2] + r) < E and abs(bs[5] - r) < E)
    upper_ok = all(abs(a - b) < E for a, b in zip(bu, b2))
    check("C4 extents", shell_ok and upper_ok,
          f"shell={[round(v, 3) for v in bs]} upper={[round(v, 3) for v in bu]}")

    collar = all(
        all(in_u(*q) for q in ring("x", (x, 0.0, 0.0), rad, n=24))
        for x in (xb + E, (xb + g["xe"]) / 2.0, g["xe"] - E) for rad in (r - E, g["rp"] + E))
    collar &= all(in_u(x, 0.0, 0.0) for x in (xb + E, (xb + g["fx"]) / 2.0, g["fx"] - E))
    tag_ok = tags is None or all(len(ql.faces().where(ql.tag(t)).resolve(upper)) == 1 for t in tags)
    check("C5 collar+tags", collar and tag_ok, f"collar={collar} tags={'skipped' if tags is None else tag_ok}")

    su, ss, s2c = point_classifier(upper, strict=True), point_classifier(shell, strict=True), \
        point_classifier(s2, strict=True)
    both = missing = total = 0
    for q in grid((-r, -r, -r), (g["xe"], p["D"], r), 2.0):
        if not s2c(*q):
            continue
        total += 1
        u, s = su(*q), ss(*q)
        both += u and s
        missing += not (in_u(*q) or in_s(*q))
    check("C6 sampled partition", total > 0 and both == 0 and missing == 0,
          f"s2_samples={total} both={both} missing={missing}")
    return check.failures


def check_s3_guards(l_link=BODY) -> list[str]:
    check = Checks()
    p0 = l_link.params()
    g = split_geom(p0)

    def rejects(**over) -> bool:
        try:
            l_link.assert_params({**p0, **over})
        except AssertionError:
            return True
        return False

    try:
        l_link.assert_params(p0)
        accepts = True
    except AssertionError:
        accepts = False
    xb_bad = (g["fx"] - p0["wall_t"] + 0.01) / p0["L"]
    cases = {
        "x_b>=fx-wall_t": rejects(split_end_frac=xb_bad),
        "x_a>=x_b": rejects(split_arc_frac=p0["split_end_frac"]),
        "x_a<=r_corner+2": rejects(split_arc_frac=(p0["r_corner"] + 2.0) / p0["L"]),
        "Rs>by+r": rejects(split_arc_frac=0.30),
        "arc bottom<cavity floor+1": rejects(split_arc_frac=p0["split_end_frac"]
                                            - (g["by"] + g["r"] - p0["wall_t"] - 1.0 + 0.05) / p0["L"]),
        "back_cut_frac=1": rejects(back_cut_frac=1.0),
        "left floor<by+wall_t": rejects(d_motor=2.0 * (g["by"] + p0["wall_t"]) - 0.02),
    }
    check("C7 guards", accepts and all(cases.values()), f"accepts={accepts} {cases}")
    return check.failures


# ====================================================================================================
# S4 verifier: shell contour cavity (uniform wall_t, arc end wall, open at split plane) + cable notch.
#
# Criteria (e = 0.1; rc = r_corner; Rs, arc center (x_a, cy) from S3):
#   C1 single valid Solid; 0 < V < V_S3shell; tight bbox == S3 shell bbox (round bottom, x_min kept)
#   C2 tube wall: at x in {20,35,45} and around the corner arc (phi 200/230/260 deg), tube radius
#      r-e and r-wall_t+e solid, r-wall_t-e empty (lower half, away from notch)
#   C3 end wall: arc band radius Rs-e / Rs-wall_t+e solid, Rs-wall_t-e empty (10/45/80 deg,
#      z in {0,+-6}); drop band x_b-e / x_b-wall_t+e solid, x_b-wall_t-e empty (y at 0.3 / 0.7 of the inner
#      drop cy .. -(r-wall_t); guard keeps it >= 1)
#   C4 cavity open at split plane ((x, by-e, 0) empty for x in {0,15,30,45}); interface faces
#      +Y@by (x<x_a) exactly 1, +X@x_b exactly 1, bend-window CYLINDERs exactly 2 (outer interface arc
#      + inner end-wall arc); rim tag exactly 1 on the +Y@by face
#   C5 notch: mid-wall samples inside the rounded rect empty (center, +-3, rounded-corner interiors);
#      sill (y = by - sill/2), below (y=-0.5) and beside (|z|=w/2+0.7) solid
#   C6 guards: rejects 2 notch_rr >= min(w,h), notch_sill=0, notch not piercing the wall (notch_h=17),
#      Rs - wall_t < 1; accepts defaults
# ====================================================================================================

E_WIDE = 0.1


def wall_x(p: dict, y: float, z: float, rho: float) -> float:
    """x on the corner torus (outer/left side) at tube radius rho."""
    rc = p["r_corner"]
    d = rc + math.sqrt(rho * rho - z * z)
    return rc - math.sqrt(d * d - (rc - y) ** 2)


def _in_notch_zone(p: dict, g: dict, q: tuple) -> bool:
    top = g["by"] - p["notch_sill"]
    return q[0] < 0.0 and top - p["notch_h"] - 0.3 < q[1] < top + 0.3 and abs(q[2]) < p["notch_w"] / 2 + 0.3


def check_s4(shell, shell_s3, p: dict, rim_tag: str | None) -> list[str]:
    check = Checks()
    g = split_geom(p)
    r, wt, rc, by, xa, xb, rs, cy = (g["r"], p["wall_t"], p["r_corner"], g["by"], g["xa"], g["xb"],
                                     g["rs"], g["cy"])
    ins = point_classifier(shell)

    info = brep.inspect_shape_rbrepinspection(shape=shell.wrapped)
    v, v3 = shell.get_volume(), shell_s3.get_volume()
    bb, b3 = tight_bbox(shell), tight_bbox(shell_s3)
    check("C1 solid+volume+bbox", type(shell).__name__ == "Solid" and info.valid and 0 < v < v3
          and all(abs(a - b) < 0.05 for a, b in zip(bb, b3)),
          f"valid={info.valid} V={v:.3f} V_S3={v3:.3f} bbox={[round(x, 3) for x in bb]}")

    tube_bad = []
    stations = [((x, 0.0, 0.0), (0.0, 1.0, 0.0)) for x in (20.0, 35.0, 45.0)]
    for phi in (200.0, 230.0, 260.0):
        a = math.radians(phi)
        stations.append(((rc + rc * math.cos(a), rc + rc * math.sin(a), 0.0), (math.cos(a), math.sin(a), 0.0)))
    for (px, py, _), (nx, ny, _) in stations:
        for deg in (0.0, 40.0, 90.0, 140.0, 180.0, 220.0, 270.0, 320.0):
            t = math.radians(deg)
            for rho in (r - E_WIDE, r - wt + E_WIDE, r - wt - E_WIDE):
                q = (px + rho * math.cos(t) * nx, py + rho * math.cos(t) * ny, rho * math.sin(t))
                if q[1] > by - 0.3 or _in_notch_zone(p, g, q):
                    continue
                if ins(*q) != (rho > r - wt):
                    tube_bad.append(tuple(round(c, 2) for c in q))
    check("C2 tube wall", not tube_bad, f"bad={tube_bad[:6]}")

    end_bad = []
    for deg in (10.0, 45.0, 80.0):
        a = math.radians(deg)
        for z in (0.0, 6.0, -6.0):
            for rad, want in ((rs - E_WIDE, True), (rs - wt + E_WIDE, True), (rs - wt - E_WIDE, False)):
                q = (xa + rad * math.cos(a), cy + rad * math.sin(a), z)
                if ins(*q) != want:
                    end_bad.append(tuple(round(c, 2) for c in q))
    for y in (cy - f * (cy + r - wt) for f in (0.3, 0.7)):  # inside the inner drop (S10: was -6/-9, off-band at L 130)
        for x, want in ((xb - E_WIDE, True), (xb - wt + E_WIDE, True), (xb - wt - E_WIDE, False)):
            if ins(x, y, 0.0) != want:
                end_bad.append((x, round(y, 2), 0.0))
    check("C3 end wall", not end_bad, f"bad={end_bad[:6]}")

    open_ok = all(not ins(x, by - E_WIDE, 0.0) for x in (0.0, 15.0, 30.0, 45.0))
    left_of_xa = (ql.prop("geom.center.x", "<", xa),)
    counts = {"rim": len(_plane("y", by, 1, left_of_xa).resolve(shell)),
              "bend": len(_bend(g).resolve(shell)), "drop": len(_plane("x", xb, 1).resolve(shell))}
    tagged = ql.faces().where(ql.tag(rim_tag)).resolve(shell) if rim_tag else []
    tag_ok = rim_tag is None or (len(tagged) == 1 and abs(tagged[0].get_center().y - by) < 0.05)
    # bend window holds the outer interface arc (R=Rs) + the inner end-wall arc (R=Rs-wall_t)
    expect = {"rim": 1, "bend": 2, "drop": 1}
    check("C4 open+interface+rim tag", open_ok and counts == expect and tag_ok,
          f"open={open_ok} {counts} tag={tag_ok}")

    mid, w, h, sill = r - wt / 2, p["notch_w"], p["notch_h"], p["notch_sill"]
    top = by - sill
    yc, bot = top - h / 2, top - h
    corner = p["notch_rr"] * (1 - 1 / math.sqrt(2)) + 0.3  # inside the rounded corner arc
    empty = [(yc, 0.0), (yc, 3.0), (yc, -3.0), (bot + corner, w / 2 - corner), (top - corner, -(w / 2 - corner))]
    solid = [(by - sill / 2, 0.0), (bot - 0.5, 0.0), (yc, w / 2 + 0.7), (yc, -(w / 2 + 0.7))]
    ne = [not ins(wall_x(p, y, z, mid), y, z) for y, z in empty]
    ns = [ins(wall_x(p, y, z, mid), y, z) for y, z in solid]
    check("C5 notch", all(ne) and all(ns), f"empty={ne} solid={ns}")
    return check.failures


def check_s4_guards(shell_mod=SHELL) -> list[str]:
    check = Checks()
    p0 = shell_mod.params()
    g = split_geom(p0)

    def rejects(**over) -> bool:
        try:
            shell_mod.assert_params({**p0, **over})
        except AssertionError:
            return True
        return False

    try:
        shell_mod.assert_params(p0)
        accepts = True
    except AssertionError:
        accepts = False
    cases = {
        "2rr>=min(w,h)": rejects(notch_rr=min(p0["notch_w"], p0["notch_h"]) / 2.0),
        "sill=0": rejects(notch_sill=0.0),
        "notch not piercing": rejects(notch_h=17.0),
        "Rs-wall_t<1": rejects(split_end_frac=(g["xa"] + p0["wall_t"] + 0.99) / p0["L"]),
    }
    check("C6 guards", accepts and all(cases.values()), f"accepts={accepts} {cases}")
    return check.failures


# ====================================================================================================
# S5 verifier: long bosses + cross-rib gussets (upper), pads + spot faces + 90 deg countersunk
# through holes (shell), and the boss/pad seat between them.
#
# Geometry (r = rod_d/2, br = boss_d/2, hr = boss_hole_d/2 = shell_hole_d/2, pad_top = -(r-wall_t-pad_t),
# ys = -r + spot_depth (spot plane), cone 90 deg: radius cr = csink_d/2 at ys -> hr at ys + (cr-hr)):
#   C1 upper: single valid Solid; V > V_S3upper; tight bbox == S3 upper bbox; both mount tags exactly 1
#   C2 bosses at (bx, z=0), bx in {boss_x1, boss_x2}: annulus mid-radius solid from pad_top+e to by-e;
#      radius br+e empty below the gussets; nothing below pad_top; blind hole axis empty for
#      y < pad_top+depth-e, solid at pad_top+depth+e; exactly 2 PLANE -Y @ pad_top, each at bx with
#      area pi(br^2-hr^2)
#   C3 gussets (4 per boss, directions +-x / +-z): root/tip solid, thickness rt (w = rt/2 -+ e),
#      hypotenuse inside/outside, gone below by-gh; chamfer: corner point (0.08, 0.08) inside the
#      hyp/face edge empty, (0.25, 0.25) solid; exactly 16 oblique chamfer PLANEs (all |n_i| < 0.8)
#   C4 shell: single valid Solid; tight bbox == S4 shell bbox; rim tag exactly 1; exactly 2 PLANE +Y
#      @ pad_top (area pi(pd^2/4-hr^2)), 2 PLANE -Y @ ys (area pi(sd^2/4-cr^2)), 2 CONE; samples: pad
#      solid inside pd/2, cavity outside; axis empty through; spot recess empty, spot ring solid;
#      cone empty at hr+e just above ys; remaining hole wall (hr+e) solid from ys+(cr-hr)+e to pad_top-e
#      and that length >= 1.0
#   C5 seat: strict-IN sampled interference upper x shell = 0 near both bosses (0.5 grid); annulus ring
#      at pad_top ON/IN both; coaxial: ring min(hr_boss, hr_shell)-e empty in both (shell y=pad_top-0.5,
#      boss y=pad_top+3), ring own-radius+e solid in each
#   C6 guards: rejects boss too close to corner / to split arc, bosses whose ribs meet, ribs outside
#      the cavity opening, hole deeper than boss-0.5, rib_t < 2 chamfer+0.3, pad not flat-topped,
#      pad not covering the boss, spot not a full flat, spot wall < 0.1 (sliver), no spot ring,
#      remaining wall < 1.0; accepts defaults
# ====================================================================================================

def boss_geom(p: dict) -> dict:
    g = split_geom(p)
    r, wt, br, rt = g["r"], p["wall_t"], p["boss_d"] / 2.0, p["rib_t"]
    ys, cr, hr = -r + p["spot_depth"], p["csink_d"] / 2.0, p["shell_hole_d"] / 2.0
    return dict(g, br=br, hr=p["boss_hole_d"] / 2.0, sh_hr=hr, pad_top=-(r - wt - p["pad_t"]),
                xi=math.sqrt(br * br - (rt / 2.0) ** 2), a=br + p["rib_len"], gh=p["gusset_h"], rt=rt,
                ys=ys, cr=cr, cone_top=ys + (cr - hr), bxs=(p["boss_x1"], p["boss_x2"]))


def _same_bbox(a, b) -> bool:
    return all(abs(u - v) < 0.05 for u, v in zip(tight_bbox(a), tight_bbox(b)))


def _uvw(bx: float, by: float, d: tuple):
    """Gusset frame: u along the rib (d), w across its thickness; returns (u, y, w) -> xyz."""
    ux, uz = d
    return lambda u, y, w: (bx + u * ux - w * uz, by + y, u * uz + w * ux)


def check_s5(upper, upper_s3, shell, shell_s4, p: dict, tags: tuple | None) -> list[str]:
    check = Checks()
    g = boss_geom(p)
    by, br, hr, pt, bxs = g["by"], g["br"], g["hr"], g["pad_top"], g["bxs"]
    iu = point_classifier(upper)

    info = brep.inspect_shape_rbrepinspection(shape=upper.wrapped)
    tag_n = [len(ql.faces().where(ql.tag(t)).resolve(upper)) for t in tags[:2]] if tags else [1, 1]
    check("C1 upper solid+bbox+tags", type(upper).__name__ == "Solid" and info.valid
          and upper.get_volume() > upper_s3.get_volume() and _same_bbox(upper, upper_s3) and tag_n == [1, 1],
          f"valid={info.valid} V={upper.get_volume():.3f} V_S3={upper_s3.get_volume():.3f} tags={tag_n}")

    boss_bad = []
    mid = (br + hr) / 2.0
    for bx in bxs:
        for y in (pt + E_WIDE, pt + 6.0, (pt + by) / 2.0, by - E_WIDE):
            boss_bad += [("annulus", q) for q in ring("y", (bx, y, 0.0), mid, 8) if not iu(*q)]
        boss_bad += [("outside", q) for q in ring("y", (bx, by - g["gh"] - 1.0, 0.0), br + E_WIDE, 8) if iu(*q)]
        boss_bad += [("below", q) for q in ring("y", (bx, pt - E_WIDE, 0.0), mid, 8) if iu(*q)]
        depth = p["boss_hole_depth"]
        boss_bad += [("hole", (bx, y, 0.0)) for y in (pt + E_WIDE, pt + depth / 2.0, pt + depth - E_WIDE) if iu(bx, y, 0.0)]
        if not iu(bx, pt + depth + E_WIDE, 0.0):
            boss_bad.append(("hole top", (bx, pt + depth + E_WIDE, 0.0)))
    bottoms = _plane("y", pt, -1).resolve(upper)
    area = math.pi * (br * br - hr * hr)
    bot_ok = len(bottoms) == 2 and all(
        any(abs(f.get_center().x - bx) < 0.05 for f in bottoms) for bx in bxs) and all(
        abs(f.get_area() - area) < 0.05 and abs(f.get_center().z) < 0.05 for f in bottoms)
    check("C2 bosses", not boss_bad and bot_ok,
          f"bad={boss_bad[:4]} bottoms={[(round(f.get_center().x, 2), round(f.get_area(), 3)) for f in bottoms]}")

    a, xi, gh, rt = g["a"], g["xi"], g["gh"], g["rt"]
    hyp = math.hypot(a - xi, gh)
    nu, ny = gh / hyp, -(a - xi) / hyp  # outward hyp normal in (u, y)
    um, yl = (a + xi) / 2.0, -gh / 2.0
    y_hyp = lambda u: -gh * (a - u) / (a - xi)  # noqa: E731
    rib_bad = []
    for bx in bxs:
        for d in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
            at = _uvw(bx, by, d)
            want = {
                "tip": (at(a - E_WIDE, -E_WIDE, 0.0), True),
                "root": (at(br + 0.3, y_hyp(br + 0.3) + 0.3, 0.0), True),
                "thick in": (at(br + 1.0, -0.3, rt / 2.0 - E_WIDE), True),
                "thick out": (at(br + 1.0, -0.3, rt / 2.0 + E_WIDE), False),
                "hyp in": (at(um - E_WIDE * nu, yl - E_WIDE * ny, 0.0), True),
                "hyp out": (at(um + E_WIDE * nu, yl + E_WIDE * ny, 0.0), False),
                "below": (at(br + 0.4, -gh - 0.4, 0.0), False),
                "chamfered": (at(um - 0.08 * nu, yl - 0.08 * ny, rt / 2.0 - 0.08), False),
                "chamfer rest": (at(um - 0.25 * nu, yl - 0.25 * ny, rt / 2.0 - 0.25), True),
            }
            rib_bad += [(k, bx, d) for k, (q, w) in want.items() if iu(*q) != w]
    oblique = ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop("geom.center.y", ">=", by - gh - 0.5), ql.prop("geom.center.y", "<=", by + 0.5))).resolve(upper)
    n_ch = sum(max(abs(c) for c in (n.x, n.y, n.z)) < 0.8 for n in (f.get_normal_at() for f in oblique))
    check("C3 gussets+chamfer", not rib_bad and n_ch == 16, f"bad={rib_bad[:6]} chamfer_planes={n_ch}")

    isu = point_classifier(shell)
    info = brep.inspect_shape_rbrepinspection(shape=shell.wrapped)
    rim_n = len(ql.faces().where(ql.tag(tags[2])).resolve(shell)) if tags else 1
    sr, cr, ys, ct, shr = p["spot_d"] / 2.0, g["cr"], g["ys"], g["cone_top"], g["sh_hr"]
    pads = _plane("y", pt, 1).resolve(shell)
    spots = _plane("y", ys, -1).resolve(shell)
    cones = ql.faces().where(ql.prop("geom.type", "==", "CONE")).resolve(shell)
    pad_a, spot_a = math.pi * (p["pad_d"] ** 2 / 4.0 - shr * shr), math.pi * (sr * sr - cr * cr)
    faces_ok = (len(pads) == 2 and len(spots) == 2 and len(cones) == 2
                and all(abs(f.get_area() - pad_a) < 0.05 for f in pads)
                and all(abs(f.get_area() - spot_a) < 0.05 for f in spots)
                and sorted(round(f.get_center().x, 1) for f in cones) == sorted(round(b, 1) for b in bxs))
    sh_bad = []
    for bx in bxs:
        want = [((bx + p["pad_d"] / 2.0 - E_WIDE, pt - E_WIDE, 0.0), True), ((bx + p["pad_d"] / 2.0 + 0.3, pt - E_WIDE, 0.0), False),
                ((bx, pt - E_WIDE, p["pad_d"] / 2.0 - E_WIDE), True)]
        want += [((bx, y, 0.0), False) for y in (-g["r"] - 0.5, ys + E_WIDE, (ct + pt) / 2.0, pt - E_WIDE)]
        want += [(q, False) for q in ring("y", (bx, ys - 0.05, 0.0), (cr + sr) / 2.0, 8)]
        want += [(q, True) for q in ring("y", (bx, ys + 0.03, 0.0), (cr + sr) / 2.0, 8)]
        want += [(q, False) for q in ring("y", (bx, ys + 0.2, 0.0), shr + E_WIDE, 8)]
        for y in (ct + E_WIDE, (ct + pt) / 2.0, pt - E_WIDE):
            want += [(q, True) for q in ring("y", (bx, y, 0.0), shr + E_WIDE, 8)]
        sh_bad += [tuple(round(c, 2) for c in q) for q, w in want if isu(*q) != w]
    wall = pt - ct
    check("C4 shell pads+spot+csink", type(shell).__name__ == "Solid" and info.valid and _same_bbox(shell, shell_s4)
          and rim_n == 1 and faces_ok and not sh_bad and wall >= 1.0 - 1e-9,
          f"valid={info.valid} rim={rim_n} pads={[round(f.get_area(), 3) for f in pads]} "
          f"spots={[round(f.get_area(), 3) for f in spots]} cones={len(cones)} wall={wall:.3f} bad={sh_bad[:6]}")

    ius, iss = point_classifier(upper, strict=True), point_classifier(shell, strict=True)
    both = 0
    for bx in bxs:
        for i in range(21):
            for j in range(47):
                for k in range(25):
                    q = (bx - 5.0 + 0.5 * i + 0.13, -15.0 + 0.5 * j + 0.07, -6.0 + 0.5 * k + 0.11)
                    both += ius(*q) and iss(*q)
    touch = all(iu(*q) and isu(*q) for bx in bxs for q in ring("y", (bx, pt, 0.0), mid, 8))
    coax_bad = []
    for bx in bxs:
        coax_bad += [("shell hole", q) for q in ring("y", (bx, pt - 0.5, 0.0), min(hr, shr) - E_WIDE, 8) if isu(*q)]
        coax_bad += [("shell wall", q) for q in ring("y", (bx, pt - 0.5, 0.0), shr + E_WIDE, 8) if not isu(*q)]
        coax_bad += [("boss hole", q) for q in ring("y", (bx, pt + 3.0, 0.0), min(hr, shr) - E_WIDE, 8) if iu(*q)]
        coax_bad += [("boss wall", q) for q in ring("y", (bx, pt + 3.0, 0.0), hr + E_WIDE, 8) if not iu(*q)]
    check("C5 seat+coaxial", both == 0 and touch and not coax_bad,
          f"both={both} touch={touch} bad={coax_bad[:4]}")
    return check.failures


def check_s5_guards(upper_mod=BODY, shell_mod=SHELL) -> list[str]:
    check = Checks()

    def accepts(mod) -> bool:
        try:
            mod.assert_params(mod.params())
        except AssertionError:
            return False
        return True

    def rejects(mod, **over) -> bool:
        try:
            mod.assert_params({**mod.params(), **over})
        except AssertionError:
            return True
        return False

    pu, ps = upper_mod.params(), shell_mod.params()
    g = boss_geom(ps)
    reach = g["br"] + pu["rib_len"]
    sag = lambda sd: g["r"] - math.sqrt(g["r"] ** 2 - (sd / 2.0) ** 2)  # noqa: E731
    cases = {
        "boss_x1 into corner": rejects(upper_mod, boss_x1=pu["r_corner"] + 2.0 + reach - 0.1),
        "boss_x2 into arc": rejects(upper_mod, boss_x2=g["xa"] - 2.0 - reach + 0.1),
        "ribs meet": rejects(upper_mod, boss_x2=pu["boss_x1"] + 2.0 * reach + 0.9),
        "ribs outside opening": rejects(upper_mod, back_cut_frac=0.887, d_motor=28.0),
        "hole > boss-0.5": rejects(upper_mod, boss_hole_depth=g["by"] - g["pad_top"] - 0.4),
        "rib_t < 2ch+0.3": rejects(upper_mod, rib_t=2.0 * pu["gusset_chamfer"] + 0.2),
        "pad not flat-topped": rejects(shell_mod, pad_d=2.0 * math.sqrt((g["r"] - ps["wall_t"]) ** 2
                                                                      - g["pad_top"] ** 2) + 0.2),
        "pad < boss": rejects(shell_mod, pad_d=ps["boss_d"] + 0.5),
        "spot not full flat": rejects(shell_mod, spot_d=2.0 * math.sqrt(g["r"] ** 2 - g["ys"] ** 2) + 0.1),
        "no spot ring": rejects(shell_mod, spot_d=ps["csink_d"]),
        "spot wall < 0.1 (sliver)": rejects(shell_mod, spot_depth=sag(ps["spot_d"]) + 0.09),
        "wall under cone < 1": rejects(shell_mod, spot_depth=0.7),
    }
    ok = accepts(upper_mod) and accepts(shell_mod)
    check("C6 guards", ok and all(cases.values()) and ps["spot_depth"] - sag(ps["spot_d"]) >= 0.1 - 1e-9,
          f"accepts={ok} {cases}")
    return check.failures


# ====================================================================================================
# S6 verifier: coax cable hole in the shell bottom + fillets (upper R fillet_r on the 4 end-cap rims,
# shell R safe_fillet_r on the outer loops of both cable openings) + re-tag.
#
# Geometry (r = rod_d/2, rp = pocket radius, R = fillet_r, Rs = safe_fillet_r, e = 0.05 / 0.45 corner offsets):
#   C1 upper: single valid Solid; tight bbox == S5 upper; V_S5 - V = Pappus of the 4 rim fillet sections
#      (outer rim ring r, inner rim ring rp; section area R^2(1-pi/4), centroid R(10-3pi)/(12-3pi) from
#      the corner) +-0.5%; faces = S5 + 4; mount tags exactly 1 each, area pi rp^2 (floors untouched)
#   C2 upper edges: rims rounded (corner points 0.05/0.05 empty, 0.45/0.45 solid; outer + inner rim, both
#      caps, 8 angles); kept sharp: pocket floor/wall corners (y=d_motor/2, x=L-plate_t: void-side point
#      0.1/0.1 stays empty), split interface faces keep their S5 areas (-Y@by, bend CYL, -X@xb)
#   C3 shell: single valid Solid; tight bbox == S5 shell; rim tag exactly 1 with S5 rim area; +Y@by /
#      bend CYL x2 / +X@xb areas == S5; pads 2 / spot rings 2 / CONE 2 unchanged; faces = S5 + 8 + 16;
#      V_S5 - V_hole(numeric: rounded rect x wall height t(z)) - V in (0, 20] (fillet material)
#   C4 coax hole at cx = ((boss_x2+boss_d/2+rib_len) + (x_b-wall_t))/2, x-length notch_h, z-width notch_w,
#      corner notch_rr: wall mid-surface points inside the rounded rect empty, points 0.3 outside solid,
#      rounded corners solid at the rect corner; end wall (x_b-wall_t/2, inside the drop band) and spot ring of boss 2 intact
#   C5 shell edges: notch outer loop rounded at the top/bottom edges (z=0: 0.05 off both faces empty,
#      0.45 solid), notch inner loop sharp at the top edge (0.05 solid); coax outer loop rounded at the
#      x-edges (z=0), inner loop sharp
#   C6 guards: rejects fillet_r >= thickness/4, >= D-d_motor/2, >= rp; safe_fillet_r >= notch_rr;
#      safe_fillet_r + 0.5 > wall_t; notch blend top > back_y-0.05; coax window < notch_h+2; coax outer
#      loop not separable by y; accepts defaults
# ====================================================================================================

def coax_geom(p: dict) -> dict:
    g = split_geom(p)
    lb = p["boss_x2"] + p["boss_d"] / 2.0 + p["rib_len"]
    cx = (lb + (g["xb"] - p["wall_t"])) / 2.0
    return dict(g, cx=cx, hx0=cx - p["notch_h"] / 2.0, hx1=cx + p["notch_h"] / 2.0, hz=p["notch_w"] / 2.0,
                rr=p["notch_rr"], yt=g["by"] - p["notch_sill"], yb=g["by"] - p["notch_sill"] - p["notch_h"])


def rim_fillet_volume(p: dict) -> float:
    """Pappus: 2 caps x (outer rim at r + inner rim at rp) of a 90 deg convex fillet R."""
    g, rf = split_geom(p), p["fillet_r"]
    a, k = rf * rf * (1.0 - math.pi / 4.0), rf * (10.0 - 3.0 * math.pi) / (12.0 - 3.0 * math.pi)
    return 2.0 * a * 2.0 * math.pi * ((g["r"] - k) + (g["rp"] + k))


def coax_hole_volume(p: dict, n: int = 400) -> float:
    """Rounded rect (x: notch_h, z: notch_w, rr) x vertical wall height t(z) of the run tube."""
    c, r, wt = coax_geom(p), p["rod_d"] / 2.0, p["wall_t"]
    hz, rr, hx = c["hz"], c["rr"], p["notch_h"] / 2.0
    vol, dz = 0.0, 2.0 * hz / n
    for i in range(n):
        z = -hz + (i + 0.5) * dz
        cut = max(0.0, abs(z) - (hz - rr))
        width = 2.0 * (hx - rr + math.sqrt(max(rr * rr - cut * cut, 0.0)))
        vol += width * (math.sqrt(r * r - z * z) - math.sqrt((r - wt) ** 2 - z * z)) * dz
    return vol


def _n_faces(s) -> int:
    return len(ql.faces().resolve(s))


def _areas(sel, s) -> list:
    return sorted(round(f.get_area(), 3) for f in sel.resolve(s))


def _interface(g):
    """Upper-side split interface (normals -Y / -X) and shell-side (+Y / +X) plane selectors + bend CYL."""
    xa = ql.prop("geom.center.x", "<", g["xa"])
    return {"flat_up": _plane("y", g["by"], -1, (xa,)), "flat_sh": _plane("y", g["by"], 1, (xa,)),
            "drop_up": _plane("x", g["xb"], -1), "drop_sh": _plane("x", g["xb"], 1), "bend": _bend(g)}


def _rim_points(p: dict, off: float) -> list:
    """Corner points `off` inside both faces of the 4 cap rims (arm cap y=D about Y, end cap x=x_end about X)."""
    g = split_geom(p)
    pts = []
    for k in range(8):
        a = 2.0 * math.pi * (k + 0.5) / 8.0
        for rad in (g["r"] - off, g["rp"] + off):
            u, v = rad * math.cos(a), rad * math.sin(a)
            pts.append((u, p["D"] - off, v))
            pts.append((g["xe"] - off, u, v))
    return pts


def check_s6(upper, upper_s5, shell, shell_s5, p: dict, tags: tuple | None) -> list[str]:
    check = Checks()
    g, c = split_geom(p), coax_geom(p)
    r, rp, by, wt = g["r"], g["rp"], g["by"], p["wall_t"]
    iu = point_classifier(upper)

    info = brep.inspect_shape_rbrepinspection(shape=upper.wrapped)
    dv, dv_want = upper_s5.get_volume() - upper.get_volume(), rim_fillet_volume(p)
    names = tags[:2] if tags and None not in tags[:2] else None
    floors = [ql.faces().where(ql.tag(t)).resolve(upper) for t in names] if names else []
    floor_ok = all(len(f) == 1 and abs(f[0].get_area() - math.pi * rp * rp) < 0.05 for f in floors)
    check("C1 upper solid+volume+tags", type(upper).__name__ == "Solid" and info.valid
          and _same_bbox(upper, upper_s5) and abs(dv - dv_want) <= 0.005 * dv_want
          and _n_faces(upper) == _n_faces(upper_s5) + 4 and floor_ok,
          f"valid={info.valid} dV={dv:.3f} want={dv_want:.3f} faces={_n_faces(upper_s5)}->{_n_faces(upper)} "
          f"floors={[[round(f.get_area(), 3) for f in fs] for fs in floors]}")

    bad = [("rim not rounded", q) for q in _rim_points(p, 0.05) if iu(*q)]
    bad += [("rim over-cut", q) for q in _rim_points(p, 0.45) if not iu(*q)]
    fy, fx = p["d_motor"] / 2.0, g["fx"]
    for k in range(8):
        a = 2.0 * math.pi * (k + 0.5) / 8.0
        u, v = (rp - 0.1) * math.cos(a), (rp - 0.1) * math.sin(a)
        bad += [("left floor edge filleted", q) for q in [(u, fy + 0.1, v)] if iu(*q)]
        bad += [("right floor edge filleted", q) for q in [(fx + 0.1, u, v)] if iu(*q)]
    sel = _interface(g)
    iface = {k: (_areas(sel[k], upper_s5), _areas(sel[k], upper)) for k in ("flat_up", "drop_up", "bend")}
    iface_ok = all(a == b and a for a, b in iface.values())
    check("C2 upper rims round / floors+interface sharp", not bad and iface_ok, f"bad={bad[:4]} iface={iface}")

    ish = point_classifier(shell)
    info = brep.inspect_shape_rbrepinspection(shape=shell.wrapped)
    rim_tag = tags[2] if tags else None
    rim = ql.faces().where(ql.tag(rim_tag)).resolve(shell) if rim_tag else sel["flat_sh"].resolve(shell)
    rim_ok = len(rim) == 1 and abs(rim[0].get_area() - sel["flat_sh"].resolve(shell_s5)[0].get_area()) < 1e-3
    ys = -r + p["spot_depth"]
    kept = {"flat_sh": sel["flat_sh"], "drop_sh": sel["drop_sh"], "bend": sel["bend"],
            "pads": _plane("y", -(r - wt - p["pad_t"]), 1), "spots": _plane("y", ys, -1),
            "cones": ql.faces().where(ql.prop("geom.type", "==", "CONE"))}
    kept = {k: (_areas(s, shell_s5), _areas(s, shell)) for k, s in kept.items()}
    kept_ok = all(a == b and a for a, b in kept.values())
    fillet_v = shell_s5.get_volume() - coax_hole_volume(p) - shell.get_volume()
    check("C3 shell solid+kept faces+tag", type(shell).__name__ == "Solid" and info.valid
          and _same_bbox(shell, shell_s5) and rim_ok and kept_ok
          and _n_faces(shell) == _n_faces(shell_s5) + 24 and 0.0 < fillet_v <= 20.0,
          f"valid={info.valid} rim={[round(f.get_area(), 3) for f in rim]} faces={_n_faces(shell_s5)}->"
          f"{_n_faces(shell)} fillet_V={fillet_v:.3f} changed={[k for k, (a, b) in kept.items() if a != b or not a]}")

    cx, hx0, hx1, hz, rr = c["cx"], c["hx0"], c["hx1"], c["hz"], c["rr"]
    mid = lambda z: -math.sqrt((r - wt / 2.0) ** 2 - z * z)  # noqa: E731  wall mid-surface y
    arc_in = (rr - 0.3) / math.sqrt(2.0)  # just inside each corner arc, on its bisector
    inner = [(cx, 0.0), (hx0 + 0.3, 0.0), (hx1 - 0.3, 0.0), (cx, hz - 0.3), (cx, -(hz - 0.3))]
    inner += [(x0 + sx * (rr - arc_in), sz * (hz - rr + arc_in)) for x0, sx in ((hx0, 1.0), (hx1, -1.0))
              for sz in (1.0, -1.0)]
    want = [((x, mid(z), z), False) for x, z in inner]
    want += [((x, mid(0.0), 0.0), True) for x in (hx0 - 0.3, hx1 + 0.3)]
    want += [((cx, mid(z), z), True) for z in (hz + 0.3, -(hz + 0.3))]
    want += [((x, mid(z), z), True) for x in (hx0 + 0.15, hx1 - 0.15) for z in (hz - 0.15, -(hz - 0.15))]
    cy = g["by"] - (g["xb"] - g["xa"])  # arc bottom: end wall is the vertical drop below it (S10: was y -4/-10)
    want += [((g["xb"] - wt / 2.0, cy - f * (cy + r - wt), 0.0), True) for f in (0.3, 0.7)]
    br = (p["csink_d"] + p["spot_d"]) / 4.0
    want += [((p["boss_x2"] + br, ys + 0.03, 0.0), True)]
    hole_bad = [tuple(round(v, 2) for v in q) for q, w in want if ish(*q) != w]
    check("C4 coax hole", not hole_bad, f"cx={cx} x=[{hx0},{hx1}] bad={hole_bad}")

    rc, ro, ri = p["r_corner"], p["r_corner"] + r, p["r_corner"] + r - wt

    def torus_pt(y: float, rho: float) -> tuple:
        return (rc - math.sqrt(rho * rho - (rc - y) ** 2), y, 0.0)

    yt, yb = c["yt"], c["yb"]
    want = [(torus_pt(yt + 0.05, ro - 0.05), False), (torus_pt(yt + 0.45, ro - 0.45), True),
            (torus_pt(yb - 0.05, ro - 0.05), False), (torus_pt(yb - 0.45, ro - 0.45), True),
            (torus_pt(yt + 0.05, ri + 0.05), True)]
    for x, s in ((hx0, -1.0), (hx1, 1.0)):
        want += [((x + s * 0.05, -r + 0.05, 0.0), False), ((x + s * 0.45, -r + 0.45, 0.0), True),
                 ((x + s * 0.05, -(r - wt) - 0.05, 0.0), True)]
    edge_bad = [tuple(round(v, 3) for v in q) for q, w in want if ish(*q) != w]
    check("C5 shell outer loops round / inner sharp", not edge_bad, f"bad={edge_bad}")
    return check.failures


def notch_blend_rise(p: dict) -> float:
    """Rise of the R safe_fillet_r blend above the notch top edge up the torus skin (z=0 section)."""
    c = coax_geom(p)
    rho = p["r_corner"] + p["rod_d"] / 2.0
    tilt = math.asin((p["r_corner"] - c["yt"]) / rho)
    return p["safe_fillet_r"] / math.tan((math.pi / 2.0 + tilt) / 2.0) * math.cos(tilt)


def check_s6_guards(upper_mod=BODY, shell_mod=SHELL) -> list[str]:
    check = Checks()

    def accepts(mod) -> bool:
        try:
            mod.assert_params(mod.params())
        except AssertionError:
            return False
        return True

    def rejects(mod, **over) -> bool:
        try:
            mod.assert_params({**mod.params(), **over})
        except AssertionError:
            return True
        return False

    pu, ps = upper_mod.params(), shell_mod.params()
    g = split_geom(ps)
    r, wt = g["r"], ps["wall_t"]
    lb = ps["boss_x2"] + ps["boss_d"] / 2.0 + ps["rib_len"]
    cases = {
        "fillet_r = thickness/4": rejects(upper_mod, fillet_r=pu["thickness"] / 4.0),
        "fillet_r = D-d_motor/2": rejects(upper_mod, d_motor=2.0 * (pu["D"] - pu["fillet_r"])),
        "fillet_r = rp": rejects(upper_mod, thickness=pu["rod_d"] - 2.0 * pu["fillet_r"]),
        "safe_fillet_r = notch_rr": rejects(shell_mod, safe_fillet_r=1.5, notch_rr=1.5, notch_sill=2.0, notch_h=5.0),
        "safe_fillet_r + 0.5 > wall_t": rejects(shell_mod, safe_fillet_r=1.6, notch_rr=2.0, notch_sill=2.0,
                                                notch_h=5.0),
        "notch blend top > by-0.05": rejects(shell_mod, notch_sill=0.45),
        "coax window < notch_h+2": rejects(shell_mod, split_end_frac=(lb + ps["notch_h"] + 2.0 + wt - 0.1) / ps["L"]),
        "coax loop not separable": rejects(shell_mod, notch_w=2.0 * math.sqrt(r * r - (r - wt / 2.0) ** 2) + 0.05),
    }
    ok = accepts(upper_mod) and accepts(shell_mod)
    rise = notch_blend_rise(ps)
    check("C6 guards", ok and all(cases.values()) and rise <= ps["notch_sill"] - 0.05 + 1e-9
          and rejects(shell_mod, notch_sill=0.45) and notch_blend_rise(dict(ps, notch_sill=0.45)) > 0.40,
          f"accepts={ok} rise={rise:.4f} {cases}")
    return check.failures


# ====================================================================================================
# S7 verifier: post-fillet cuts on the upper — 8 cable windows + 3-arm key groove + 3 radial countersinks.
#
# Geometry (r = rod_d/2, rp = pocket radius, fx = L - plate_t, e = 0.1; angles of the groove / radial holes
# in the YZ plane from +Y toward +Z, direction (0, cos t, sin t)):
#   C1 single valid Solid; tight bbox == S6; faces = S6 + 64 + 10 + 12 (4 per radial hole); mount tags exactly 1
#      each: left area pi rp^2, right area pi rp^2 - A_star (star = union of 3 half-strips width
#      key_w + 2 key_gap, length key_r_out + key_gap, analytic 9-vertex polygon); V_S6 - V ==
#      sum V(S6 & harness tool) over windows / groove / radial (tools built here from boxes + cylinders +
#      cones, independent of the source sketches) +-0.2%; groove part == A_star * groove_d and right
#      windows == numeric rounded-rect x tube-wall integral (+-0.5%)
#   C2 windows (4 per pocket at cable_w_phase + k*90, right-hand about the pocket axis from +Z): at s = rp+1 inside the
#      rounded rect (centre, axial +-(h/2-0.3), tangential +-(w/2-0.3)) empty; axial +-(h/2+0.3) and
#      tangential +-(w/2+0.3) solid (so the bottom edge sits at seat + cable_w_off +-0.3, seat = y=d_motor/2 /
#      x=L); rect corner (h/2-0.15, w/2-0.15) solid (rounded); window ray empty rp+0.1 .. 16.5; inter-window
#      walls (phase + 45 + k*90) solid
#   C3 groove: exactly 1 PLANE +X @ fx - groove_d, area A_star; at x = fx - groove_d/2 each arm (key_phase
#      + k*120) empty at radius 0.5 / 6 / L_arm - e and laterally +-(w_g/2 - e), solid at L_arm + e and
#      laterally +-(w_g/2 + e); between arms (+60) and opposite (+180) solid at radius 6; floor
#      fx - groove_d + 0.05 empty, - 0.05 solid
#   C4 radial countersinks @ x = L - plate_t/2, angles key_phase + k*360/rad_screw_n: axis empty rp+0.2 ..
#      r-0.05; clearance wall (radius 13, lateral hr -+ e along X) empty / solid; cone below the spot floor
#      (radius r - spot_depth - 0.1: lateral cr - 0.3 empty, cr + 0.05 solid); spot recess (radius
#      r - spot_depth/2: lateral sr - 0.05 empty, sr + 0.1 solid); off-phase (+60, +180) axis solid;
#      CONE faces == rad_screw_n (overshoot inside the spot: no cone band on the spot wall) all at x = xs +- cr
#   C5 S6 kept: cap rim fillets (s6 rim points), pocket floor edges sharp, split interface areas == S6
#   C6 guards: rejects cable_w_off 2.9 / 5.1, window top > mouth - 2, 2 rr >= min(w,h), w > 1.6 rp,
#      rad_csink_d <= rad_clear_d, rad_spot_d < csink + 0.2, spot wall < 0.1, wall below csink < 1, radial
#      x-range not inside the plate, key arm > rp - 0.5, groove floor behind < x_b + wall_t; accepts defaults
# ====================================================================================================

S7_FACES_ADDED = 64 + 10 + 12  # windows / star groove (s7_hypothesis H1 / H2b) / radial 4 per hole: spot wall,
# spot floor, cone, clearance bore (was 27 = 9 per hole while the cone overshoot banded the spot wall — S10)


def s7_geom(p: dict) -> dict:
    g = split_geom(p)
    return dict(g, yl=p["d_motor"] / 2.0 + p["cable_w_off"] + p["cable_w_h"] / 2.0,
                xr=p["L"] + p["cable_w_off"] + p["cable_w_h"] / 2.0,
                wg=p["key_w"] + 2.0 * p["key_gap"], lg=p["key_r_out"] + p["key_gap"],
                xs=p["L"] - p["plate_t"] / 2.0)


def star_area(w: float, length: float) -> float:
    """Union of 3 half-strips (width w, length from the centre) at 120 deg: 9-vertex polygon."""
    hw, c = w / 2.0, w / 2.0 / math.sin(math.radians(60.0))
    pts = []
    for k in range(3):
        th = math.radians(120.0 * k)
        u, n = (math.cos(th), math.sin(th)), (-math.sin(th), math.cos(th))
        pts += [(length * u[0] - hw * n[0], length * u[1] - hw * n[1]),
                (length * u[0] + hw * n[0], length * u[1] + hw * n[1])]
        pts.append((c * math.cos(th + math.radians(60.0)), c * math.sin(th + math.radians(60.0))))
    return 0.5 * abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])))


def window_volume_straight(p: dict, n: int = 400) -> float:
    """One window through a straight tube wall rp..r: tangential width w (axial h, corners rr)."""
    r, rp = p["rod_d"] / 2.0, (p["rod_d"] - p["thickness"]) / 2.0
    hw, hh, rr = p["cable_w_w"] / 2.0, p["cable_w_h"] / 2.0, p["cable_w_rr"]
    vol, dt = 0.0, 2.0 * hw / n
    for i in range(n):
        t = -hw + (i + 0.5) * dt
        cut = max(0.0, abs(t) - (hw - rr))
        axial = 2.0 * (hh - rr + math.sqrt(max(rr * rr - cut * cut, 0.0)))
        vol += axial * (math.sqrt(r * r - t * t) - math.sqrt(rp * rp - t * t)) * dt
    return vol


# ---- harness tools (boxes / cylinders / cones only) ----
def _rounded_prism(a: float, b: float, rr: float, half_len: float, rr_on: bool = True, one_side: bool = False):
    """Prism along Z over [-half_len, half_len] (one_side: [0, half_len]); section x = a, y = b, corner rr."""
    z0, ln = (0.0, half_len) if one_side else (-half_len, 2.0 * half_len)
    if not rr_on or rr <= 0.0:
        return scad.make_box_rsolid(width=a, height=b, depth=ln, bottom_face_center=(0.0, 0.0, z0))
    parts = [scad.make_box_rsolid(width=a - 2.0 * rr, height=b, depth=ln, bottom_face_center=(0.0, 0.0, z0)),
             scad.make_box_rsolid(width=a, height=b - 2.0 * rr, depth=ln, bottom_face_center=(0.0, 0.0, z0))]
    parts += [scad.make_cylinder_rsolid(radius=rr, height=ln, bottom_face_center=(sx * (a / 2.0 - rr), sy * (b / 2.0 - rr), z0),
                                        axis=(0.0, 0.0, 1.0)) for sx in (1.0, -1.0) for sy in (1.0, -1.0)]
    return scad.union_rsolid(*parts)


def harness_windows(p: dict, phase=None, off=None, half_len=None, rr_on=True, sides=("left", "right"),
                    one_side=False) -> list:
    """Through prisms at phase / phase+90 (2 windows each); one_side: 4 half prisms per pocket, one window each
    (for volume: intersect_rsolid keeps only one piece of a disconnected overlap — s7 finding)."""
    phase = p["cable_w_phase"] if phase is None else phase
    off = p["cable_w_off"] if off is None else off
    half_len = p["rod_d"] if half_len is None else half_len
    w, h, rr = p["cable_w_w"], p["cable_w_h"], p["cable_w_rr"]
    out = []
    for rot in [phase + 90.0 * k for k in range(4 if one_side else 2)]:
        if "left" in sides:  # section x tangential w, y axial h; about Y
            t = scad.rotate_shape(shape=_rounded_prism(w, h, rr, half_len, rr_on, one_side), angle=rot, axis=(0.0, 1.0, 0.0))
            out.append(scad.translate_shape(shape=t, vector=(0.0, p["d_motor"] / 2.0 + off + h / 2.0, 0.0)))
        if "right" in sides:  # section x axial h, y tangential w; about X
            t = scad.rotate_shape(shape=_rounded_prism(h, w, rr, half_len, rr_on, one_side), angle=rot, axis=(1.0, 0.0, 0.0))
            out.append(scad.translate_shape(shape=t, vector=(p["L"] + off + h / 2.0, 0.0, 0.0)))
    return out


def harness_groove(p: dict, phase=None, depth=None, length=None, boxes=False) -> list:
    """Star groove as ONE 3D polyline face in the YZ plane at x = fx - depth, extruded +X (no sketch, no rotate);
    boxes: 3 rotated box arms (same volume, floor split into 6 faces — hypothesis H2)."""
    g = s7_geom(p)
    phase = p["key_phase"] if phase is None else phase
    depth = p["groove_d"] if depth is None else depth
    length = g["lg"] if length is None else length
    fx, ovs, hw = g["fx"], 1.0, g["wg"] / 2.0
    if boxes:
        arm = scad.make_box_rsolid(width=depth + ovs, height=length, depth=g["wg"],
                                   bottom_face_center=(fx - depth + (depth + ovs) / 2.0, length / 2.0, -hw))
        return [scad.rotate_shape(shape=arm, angle=phase + 120.0 * k, axis=(1.0, 0.0, 0.0)) for k in range(3)]
    pts, x0 = [], fx - depth
    for k in range(3):
        th = math.radians(phase + 120.0 * k)
        cy, cz = math.cos(th), math.sin(th)
        pts += [(x0, length * cy + hw * cz, length * cz - hw * cy), (x0, length * cy - hw * cz, length * cz + hw * cy)]
        # concave corner: intersection of this arm's +lateral edge with the next arm's -lateral edge
        tb, rc = th + math.radians(60.0), hw / math.sin(math.radians(60.0))
        pts.append((x0, rc * math.cos(tb), rc * math.sin(tb)))
    face = scad.make_face_from_wire_rface(scad.make_polyline_rwire(pts, closed=True), normal=(1.0, 0.0, 0.0))
    return [scad.extrude_rsolid(profile=face, direction=(1.0, 0.0, 0.0), distance=depth + ovs)]


def harness_radial(p: dict, phase=None, spot=True, csink=True) -> list:
    g = s7_geom(p)
    phase = p["key_phase"] if phase is None else phase
    r, rp, xs = g["r"], g["rp"], g["xs"]
    hr, cr, sr, sdp = p["rad_clear_d"] / 2.0, p["rad_csink_d"] / 2.0, p["rad_spot_d"] / 2.0, p["rad_spot_depth"]
    ys, o2 = (r - sdp) if spot else r, min(0.2, (sr - cr) / 2.0)  # countersink overshoot stays inside the spot
    one = [scad.make_cylinder_rsolid(radius=hr, height=r - rp + 2.0, bottom_face_center=(xs, rp - 1.0, 0.0),
                                     axis=(0.0, 1.0, 0.0))]
    if spot:
        one.append(scad.make_cylinder_rsolid(radius=sr, height=2.0 + sdp, bottom_face_center=(xs, ys, 0.0),
                                             axis=(0.0, 1.0, 0.0)))
    if csink:
        one.append(scad.make_cone_rsolid(bottom_radius=hr, top_radius=cr + o2, height=(cr - hr) + o2,
                                         bottom_face_center=(xs, ys - (cr - hr), 0.0), axis=(0.0, 1.0, 0.0)))
    n = int(p["rad_screw_n"])
    return [scad.rotate_shape(shape=t, angle=phase + 360.0 / n * k, axis=(1.0, 0.0, 0.0)) for k in range(n) for t in one]


def _vol_in(solid, tools: list, group: int = 1) -> float:
    """Sum of V(solid & connected tool group); groups of `group` consecutive tools are unioned first
    (window prisms only overlap in pocket air -> group 1; groove arms 3; each radial spot+cone+hole 3)."""
    chunks = [tools[i:i + group] for i in range(0, len(tools), group)]
    return sum(scad.intersect_rsolid(solid, c[0] if len(c) == 1 else scad.union_rsolid(*c)).get_volume() for c in chunks)


def check_s7(upper, upper_s6, p: dict, tags: tuple | None) -> list[str]:
    check = Checks()
    g = s7_geom(p)
    r, rp, fx, xs = g["r"], g["rp"], g["fx"], g["xs"]
    iu = point_classifier(upper)
    a_star = star_area(g["wg"], g["lg"])

    info = brep.inspect_shape_rbrepinspection(shape=upper.wrapped)
    floors = [ql.faces().where(ql.tag(t)).resolve(upper) for t in tags[:2]] if tags else [[], []]
    floor_ok = (all(len(f) == 1 for f in floors) and abs(floors[0][0].get_area() - math.pi * rp * rp) < 0.05
                and abs(floors[1][0].get_area() - (math.pi * rp * rp - a_star)) < 0.05)
    v_win = _vol_in(upper_s6, harness_windows(p, one_side=True))
    v_win_r = _vol_in(upper_s6, harness_windows(p, sides=("right",), one_side=True))
    v_groove = _vol_in(upper_s6, harness_groove(p))
    v_rad = _vol_in(upper_s6, harness_radial(p), 3)
    dv, dv_want = upper_s6.get_volume() - upper.get_volume(), v_win + v_groove + v_rad
    split_ok = (abs(v_groove - a_star * p["groove_d"]) <= 0.005 * a_star * p["groove_d"]
                and abs(v_win_r - 4.0 * window_volume_straight(p)) <= 0.005 * v_win_r)
    check("C1 solid+volume+faces+tags", type(upper).__name__ == "Solid" and info.valid
          and _same_bbox(upper, upper_s6) and abs(dv - dv_want) <= 0.002 * dv_want and split_ok
          and _n_faces(upper) == _n_faces(upper_s6) + S7_FACES_ADDED and floor_ok,
          f"valid={info.valid} dV={dv:.3f} want={dv_want:.3f} (win {v_win:.3f} [right {v_win_r:.3f} vs "
          f"{4.0 * window_volume_straight(p):.3f}] groove {v_groove:.3f} vs {a_star * p['groove_d']:.3f} rad {v_rad:.3f}) "
          f"faces={_n_faces(upper_s6)}->{_n_faces(upper)} floors={[[round(f.get_area(), 3) for f in fs] for fs in floors]}")

    hw, hh, s = p["cable_w_w"] / 2.0, p["cable_w_h"] / 2.0, rp + 1.0
    bad = []
    for side in ("left", "right"):
        def pt(ang: float, rad: float, t: float, a: float) -> tuple:
            """rad along the window direction, t tangential, a axial offset from the window centre."""
            c, sn = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            if side == "left":  # right-hand about +Y from +Z: direction (sin, 0, cos), tangent (cos, 0, -sin)
                return (rad * sn + t * c, g["yl"] + a, rad * c - t * sn)
            # right-hand about +X from +Z: direction (0, -sin, cos), tangent (0, -cos, -sin)
            # (at the 45° default the window set is mirror-symmetric, so a +sin probe hid this — S10 phase30)
            return (g["xr"] + a, -(rad * sn + t * c), rad * c - t * sn)

        for k in range(4):
            ang = p["cable_w_phase"] + 90.0 * k
            empty = [(0.0, 0.0), (0.0, hh - 0.3), (0.0, -(hh - 0.3)), (hw - 0.3, 0.0), (-(hw - 0.3), 0.0)]
            solid = [(0.0, hh + 0.3), (0.0, -(hh + 0.3)), (hw + 0.3, 0.0), (-(hw + 0.3), 0.0),
                     (hw - 0.15, hh - 0.15), (-(hw - 0.15), -(hh - 0.15))]
            bad += [(side, ang, "open", t, a) for t, a in empty if iu(*pt(ang, s, t, a))]
            bad += [(side, ang, "wall", t, a) for t, a in solid if not iu(*pt(ang, s, t, a))]
            bad += [(side, ang, "ray", round(q, 2)) for q in [rp + 0.1 + 0.2 * i for i in range(23)] if iu(*pt(ang, q, 0.0, 0.0))]
            bad += [(side, ang + 45.0, "between")] if not iu(*pt(ang + 45.0, s, 0.0, 0.0)) else []
    check("C2 cable windows", not bad, f"bad={bad[:6]} (n={len(bad)})")

    fl = ql.faces().where(ql.and_(ql.prop("geom.type", "==", "PLANE"), ql.prop("geom.normal.x", ">=", 0.999),
                                  ql.prop("geom.center.x", ">=", fx - p["groove_d"] - 0.05),
                                  ql.prop("geom.center.x", "<=", fx - p["groove_d"] + 0.05))).resolve(upper)
    xm, e, hwg, lg = fx - p["groove_d"] / 2.0, 0.1, g["wg"] / 2.0, g["lg"]

    def gp(x: float, ang: float, rad: float, lat: float = 0.0) -> tuple:
        c, sn = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        return (x, rad * c - lat * sn, rad * sn + lat * c)

    bad = []
    for k in range(3):
        ang = p["key_phase"] + 120.0 * k
        bad += [("arm", ang, q) for q in (0.5, 6.0, lg - e) if iu(*gp(xm, ang, q))]
        bad += [("arm lateral", ang, lat) for lat in (hwg - e, -(hwg - e)) if iu(*gp(xm, ang, 6.0, lat))]
        bad += [("beyond arm", ang)] if not iu(*gp(xm, ang, lg + e)) else []
        bad += [("outside lateral", ang, lat) for lat in (hwg + e, -(hwg + e)) if not iu(*gp(xm, ang, 6.0, lat))]
        bad += [("between arms", ang + d) for d in (60.0, 180.0) if not iu(*gp(xm, ang + d, 6.0))]
        bad += [("floor", ang)] if iu(*gp(fx - p["groove_d"] + 0.05, ang, 6.0)) else []
        bad += [("below floor", ang)] if not iu(*gp(fx - p["groove_d"] - 0.05, ang, 6.0)) else []
    floor_ok = len(fl) == 1 and abs(fl[0].get_area() - a_star) < 0.01
    check("C3 key groove", not bad and floor_ok,
          f"floor={[round(f.get_area(), 4) for f in fl]} want={a_star:.4f} bad={bad[:6]}")

    hr, cr, sr, sdp = p["rad_clear_d"] / 2.0, p["rad_csink_d"] / 2.0, p["rad_spot_d"] / 2.0, p["rad_spot_depth"]
    n = int(p["rad_screw_n"])
    bad = []
    for k in range(n):
        ang = p["key_phase"] + 360.0 / n * k
        d = (math.cos(math.radians(ang)), math.sin(math.radians(ang)))
        rp_ = lambda rad, dx=0.0: (xs + dx, rad * d[0], rad * d[1])  # noqa: E731
        bad += [("axis", ang, q) for q in (rp + 0.2, 13.5, r - sdp - 0.5, r - 0.05) if iu(*rp_(q))]
        bad += [("clear", ang, dx) for dx in (hr - 0.1, -(hr - 0.1)) if iu(*rp_(13.0, dx))]
        bad += [("clear wall", ang, dx) for dx in (hr + 0.1, -(hr + 0.1)) if not iu(*rp_(13.0, dx))]
        rc = r - sdp - 0.1  # just below the spot floor: cone radius cr - 0.1
        bad += [("cone", ang)] if iu(*rp_(rc, cr - 0.3)) else []
        bad += [("cone wall", ang)] if not iu(*rp_(rc, cr + 0.05)) else []
        bad += [("spot", ang)] if iu(*rp_(r - sdp / 2.0, sr - 0.05)) else []
        bad += [("spot wall", ang)] if not iu(*rp_(r - sdp / 2.0, sr + 0.1)) else []
        dd = [(math.cos(math.radians(ang + o)), math.sin(math.radians(ang + o))) for o in (60.0, 180.0)]
        bad += [("off-phase solid", ang, i) for i, q in enumerate(dd) if not iu(xs, 13.5 * q[0], 13.5 * q[1])]
    cones = ql.faces().where(ql.prop("geom.type", "==", "CONE")).resolve(upper)
    cone_ok = len(cones) == n and all(abs(c.get_center().x - xs) <= cr for c in cones)
    check("C4 radial countersinks", not bad and cone_ok, f"cones={len(cones)} bad={bad[:6]}")

    bad = [("rim not rounded", q) for q in _rim_points(p, 0.05) if iu(*q)]
    bad += [("rim over-cut", q) for q in _rim_points(p, 0.45) if not iu(*q)]
    fy = p["d_motor"] / 2.0
    for k in range(8):
        a = 2.0 * math.pi * (k + 0.5) / 8.0
        u, v = (rp - 0.1) * math.cos(a), (rp - 0.1) * math.sin(a)
        bad += [("left floor edge", q) for q in [(u, fy + 0.1, v)] if iu(*q)]
    sel = _interface(g)
    iface = {k: (_areas(sel[k], upper_s6), _areas(sel[k], upper)) for k in ("flat_up", "drop_up", "bend")}
    iface_ok = all(a == b and a for a, b in iface.values())
    check("C5 S6 features kept", not bad and iface_ok, f"bad={bad[:4]} iface={iface}")
    return check.failures


def check_s7_guards(upper_mod=BODY) -> list[str]:
    check = Checks()

    def accepts() -> bool:
        try:
            upper_mod.assert_params(upper_mod.params())
        except AssertionError:
            return False
        return True

    def rejects(**over) -> bool:
        try:
            upper_mod.assert_params({**upper_mod.params(), **over})
        except AssertionError:
            return True
        return False

    p = upper_mod.params()
    rp = (p["rod_d"] - p["thickness"]) / 2.0
    cases = {
        "cable_w_off 2.9": rejects(cable_w_off=2.9),
        "cable_w_off 5.1": rejects(cable_w_off=5.1),
        "window top > mouth-2": rejects(cable_w_h=5.6),
        "2 rr >= min(w,h)": rejects(cable_w_rr=2.5),
        "w > 1.6 rp": rejects(cable_w_w=1.6 * rp + 0.1),
        "csink <= clear": rejects(rad_csink_d=p["rad_clear_d"]),
        "spot_d < csink+0.2": rejects(rad_spot_d=p["rad_csink_d"] + 0.1),
        "spot wall < 0.1": rejects(rad_spot_depth=0.24),
        "wall below csink < 1": rejects(rad_csink_d=5.8, rad_spot_d=6.0, rad_spot_depth=0.45, plate_t=7.0),
        "radial x not in plate": rejects(rad_spot_d=5.0, rad_spot_depth=0.35),
        "key arm > rp-0.5": rejects(key_r_out=rp - 0.5 - p["key_gap"] + 0.05),
        "groove floor behind < xb+wt": rejects(groove_d=13.1),
    }
    ok = accepts()
    check("C6 guards", ok and all(cases.values()), f"accepts={ok} {cases}")
    return check.failures


# ====================================================================================================
# S8 verifier: adapter plate l-link-adapter-<preset> (STAR3 / CENTER4) + fit against the S7 upper.
#
# Geometry (R = rp - plate_gap, T = plate_t, x0 = L - T = mount face 2, rf = safe_fillet_r, hr / cr = motor
# hole / csink radius, pr = rad_pilot_d/2, t0 = pilot inner radius, angles in YZ from +Y toward +Z):
#   C1 single valid Solid; tight bbox == [x0 - key_h, -R, -R, L, R, R]; V (precise_volume, eps 1e-9) ==
#      pi R^2 T - 2 Pappus(R, rf) + A_key key_h - n (pi hr^2 T + cone extra) - bore - 3 * pilot integral
#      (+-0.01; Solid.get_volume() is ~0.1 off per pilot BSpline trim, s8 finding); faces 39 / 29
#      (hypothesis H5); A_key: STAR3 3 hub-relieved strips (r0..r1), CENTER4 9-vertex star (r1 = key_r_in)
#   C2 tags + metadata: seat (x=L) 1 face pi (R-rf)^2 - n pi hr^2 - bore; back (x=x0) 1 face pi (R-rf)^2
#      - n pi cr^2 - A_key - pi r0^2 (STAR3 relief floor is separate; bore inside it); key tops key_faces
#      faces summing to A_key @ x0 - key_h; CONE faces n, area n * lateral; metadata plate_preset == preset
#   C3 sampling: motor hole axis empty / wall solid at hole angles, solid half-way between holes; csink
#      cone radius at depth d (cr - d) -+0.1; key arm solid (mid, lateral hw - 0.1, end r1 - 0.1) / empty
#      (lateral hw + 0.1, end r1 + 0.1, between arms, above top); STAR3 hub r0 -+0.1, bore bd/2 -+0.1 /
#      CENTER4 centre solid; pilots empty t0 + 0.1 .. R - 0.05, solid t0 - 0.1, x wall +-(pr + 0.1), off-phase
#      solid; both rims rounded (corner bisector 0.05 empty, 0.4 solid)
#   C4 fit vs S7 upper: V(upper & plate) (OCP common) within 0.01;
#      back face contact (x0 +-0.05); key top gap groove_d - key_h, side gap key_gap, STAR3 end gap key_gap,
#      radial gap plate_gap (points in neither); pilot coaxial with the sleeve clearance hole
#   C5 radial screw pick: STAR3 M2x6, CENTER4 M2x5 (pilot truncation); head recess >= 0.1
#   C6 guards (assertion message matched): plate_gap 0, key_h >= groove_d, head recess < 0.1, csink to rim,
#      key_r_in 0 / > key_r_out, arm corner past fillet / land < 0.3, arm to csink (CENTER4), csink to bore (STAR3), pilot
#      x-band vs back, pilot >= clear, pilot depth < 2, no screw length; accepts defaults
# ====================================================================================================

S8_FACES = {"star3": 39, "center4": 29}  # s8_hypothesis H5
S8_SCREW = {"star3": 6.0, "center4": 5.0}


def pappus_edge(radius: float, rf: float) -> float:
    """Volume removed by a rf fillet on a circular 90 deg rim of radius `radius`."""
    k = (10.0 - 3.0 * math.pi) / (12.0 - 3.0 * math.pi)
    return 2.0 * math.pi * (radius - k * rf) * rf * rf * (1.0 - math.pi / 4.0)


def hub_strip_area(hw: float, r0: float, r1: float) -> float:
    """Strip |s| <= hw from the circle r0 out to the line t = r1."""
    return 2.0 * hw * r1 - (hw * math.sqrt(r0 * r0 - hw * hw) + r0 * r0 * math.asin(hw / r0))


def pilot_volume(radius: float, pr: float, t0: float, n: int = 2000) -> float:
    """Radial blind cylinder (radius pr, flat end at t0) inside a disk of radius `radius`."""
    ds, vol = 2.0 * pr / n, 0.0
    for i in range(n):
        s = -pr + (i + 0.5) * ds
        vol += 2.0 * math.sqrt(pr * pr - s * s) * (math.sqrt(radius * radius - s * s) - t0) * ds
    return vol


def s8_geom(p: dict, preset) -> dict:
    lay = dm.plate_layout(p, preset)
    hw = p["key_w"] / 2.0
    a_key = (3.0 * hub_strip_area(hw, lay["key_r0"], lay["key_r1"]) if lay["key_r0"] > 0.0
             else star_area(p["key_w"], lay["key_r1"]))
    return dict(lay, R=dm.plate_r(p), T=p["plate_t"], x0=dm.mount_x(p), rf=p["safe_fillet_r"], hw=hw,
                hr=p["m2_hole_d"] / 2.0, cr=p["m2_csink_d"] / 2.0, rc=p["m2_pcd"] / 2.0, pr=p["rad_pilot_d"] / 2.0,
                xs=dm.radial_x(p), t0=dm.pilot_inner_r(p, preset), a_key=a_key,
                holes=dm.hole_angles(p, preset), arms=[p["key_phase"] + 120.0 * k for k in range(3)],
                radial=dm.radial_angles(p))


def _yz(radius: float, ang: float, lat: float = 0.0) -> tuple:
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    return radius * c - lat * s, radius * s + lat * c


def analytic_volume(g: dict, key_h: float) -> float:
    hr, cr, T = g["hr"], g["cr"], g["T"]
    h = cr - hr
    cone_extra = math.pi * h / 3.0 * (cr * cr + cr * hr + hr * hr) - math.pi * hr * hr * h
    return (math.pi * g["R"] ** 2 * T - 2.0 * pappus_edge(g["R"], g["rf"]) + g["a_key"] * key_h
            - g["hole_n"] * (math.pi * hr * hr * T + cone_extra) - math.pi * (g["bore_d"] / 2.0) ** 2 * T
            - len(g["radial"]) * pilot_volume(g["R"], g["pr"], g["t0"]))


def check_s8(plate, preset, p: dict) -> list[str]:
    check = Checks()
    g = s8_geom(p, preset)
    R, T, x0, rf, L, kh = g["R"], g["T"], g["x0"], g["rf"], p["L"], p["key_h"]
    ip = point_classifier(plate)
    name = preset.value

    info = brep.inspect_shape_rbrepinspection(shape=plate.wrapped)
    bb = tight_bbox(plate)
    bb_want = (x0 - kh, -R, -R, L, R, R)
    v, v_want = precise_volume(plate), analytic_volume(g, kh)
    n_faces = len(ql.faces().resolve(plate))
    check(f"C1 {name} solid+bbox+volume+faces", type(plate).__name__ == "Solid" and info.valid
          and all(abs(a - b) <= 1e-3 for a, b in zip(bb, bb_want)) and abs(v - v_want) <= 0.01
          and n_faces == S8_FACES[name],
          f"valid={info.valid} bbox={[round(a, 4) for a in bb]} V={v:.4f} want={v_want:.4f} faces={n_faces}")

    tags = {t: ql.faces().where(ql.tag(t)).resolve(plate) for t in (dm.TAG_SEAT, dm.TAG_BACK, dm.TAG_KEY_TOP)}
    flat, bore = math.pi * (R - rf) ** 2, math.pi * (g["bore_d"] / 2.0) ** 2
    seat_want = flat - g["hole_n"] * math.pi * g["hr"] ** 2 - bore
    back_want = flat - g["hole_n"] * math.pi * g["cr"] ** 2 - g["a_key"] - math.pi * g["key_r0"] ** 2
    seat, back, tops = tags[dm.TAG_SEAT], tags[dm.TAG_BACK], tags[dm.TAG_KEY_TOP]
    cones = ql.faces().where(ql.prop("geom.type", "==", "CONE")).resolve(plate)
    lat = math.pi * (g["cr"] + g["hr"]) * math.hypot(g["cr"] - g["hr"], g["cr"] - g["hr"])
    tag_ok = (len(seat) == 1 and abs(seat[0].get_area() - seat_want) < 0.01 and abs(seat[0].get_center().x - L) < 1e-6
              and len(back) == 1 and abs(back[0].get_area() - back_want) < 0.01
              and abs(back[0].get_center().x - x0) < 1e-6 and len(tops) == g["key_faces"]
              and abs(sum(f.get_area() for f in tops) - g["a_key"]) < 0.01
              and all(abs(f.get_center().x - (x0 - kh)) < 1e-6 for f in tops))
    cone_ok = len(cones) == g["hole_n"] and abs(sum(c.get_area() for c in cones) - g["hole_n"] * lat) < 0.01 \
        and all(abs(c.get_center().x - x0) < g["cr"] - g["hr"] for c in cones)
    meta = plate.get_metadata("plate_preset")
    check(f"C2 {name} tags+cones+metadata", tag_ok and cone_ok and meta == name,
          f"seat={[round(f.get_area(), 4) for f in seat]}/{seat_want:.4f} back={[round(f.get_area(), 4) for f in back]}"
          f"/{back_want:.4f} tops={[round(f.get_area(), 4) for f in tops]}/{g['a_key']:.4f} "
          f"cones={len(cones)}:{sum(c.get_area() for c in cones):.4f}/{g['hole_n'] * lat:.4f} meta={meta}")

    bad = []
    xm, xk, hw, r0, r1 = x0 + T / 2.0, x0 - kh / 2.0, g["hw"], g["key_r0"], g["key_r1"]
    for a in g["holes"]:
        bad += [("hole axis", a, x) for x in (x0 + 0.1, xm, L - 0.1) if ip(x, *_yz(g["rc"], a))]
        bad += [("hole wall", a)] if not ip(L - 0.5, *_yz(g["rc"] + g["hr"] + 0.1, a)) else []
        d = 0.6  # cone radius cr - d at depth d from the back face
        bad += [("csink", a)] if ip(x0 + d, *_yz(g["rc"] + g["cr"] - d - 0.1, a)) else []
        bad += [("csink wall", a)] if not ip(x0 + d, *_yz(g["rc"] + g["cr"] - d + 0.1, a)) else []
        bad += [("seat side no csink", a)] if not ip(L - 0.3, *_yz(g["rc"] + g["hr"] + 0.2, a)) else []
        bad += [("between holes", a)] if not ip(L - 0.5, *_yz(g["rc"], a + 180.0 / g["hole_n"])) else []
    for a in g["arms"]:
        mid = (max(r0, 0.5) + r1) / 2.0
        bad += [("arm solid", a, q) for q in ((mid, 0.0), (mid, hw - 0.1), (mid, -(hw - 0.1)), (r1 - 0.1, 0.0))
                if not ip(xk, *_yz(q[0], a, q[1]))]
        bad += [("arm empty", a, q) for q in ((mid, hw + 0.1), (mid, -(hw + 0.1)), (r1 + 0.1, 0.0))
                if ip(xk, *_yz(q[0], a, q[1]))]
        bad += [("between arms", a)] if ip(xk, *_yz(6.0, a + 60.0)) else []
        bad += [("above key top", a)] if ip(x0 - kh - 0.05, *_yz(mid, a)) else []
        bad += [("key top", a)] if not ip(x0 - kh + 0.05, *_yz(mid, a)) else []
        if r0 > 0.0:
            bad += [("hub relief", a)] if ip(xk, *_yz(r0 - 0.1, a)) else []
            bad += [("hub arm root", a)] if not ip(xk, *_yz(r0 + 0.1, a)) else []
    if g["bore_d"] > 0.0:
        bad += [("bore", q) for q in ((0.0, 0.0), _yz(g["bore_d"] / 2.0 - 0.1, 30.0)) if ip(xm, *q)]
        bad += [("bore wall",)] if not ip(xm, *_yz(g["bore_d"] / 2.0 + 0.1, 30.0)) else []
    else:
        bad += [("centre solid", x) for x in (xk, xm) if not ip(x, 0.0, 0.0)]
    for a in g["radial"]:
        bad += [("pilot", a, t) for t in (g["t0"] + 0.1, (g["t0"] + R) / 2.0, R - 0.05) if ip(g["xs"], *_yz(t, a))]
        bad += [("pilot end", a)] if not ip(g["xs"], *_yz(g["t0"] - 0.1, a)) else []
        bad += [("pilot wall", a, dx) for dx in (g["pr"] + 0.1, -(g["pr"] + 0.1))
                if not ip(g["xs"] + dx, *_yz((g["t0"] + R) / 2.0, a))]
        bad += [("pilot off-phase", a)] if not ip(g["xs"], *_yz(R - 1.0, a + 60.0)) else []
    for a in (15.0, 135.0, 255.0):
        for xc, sx in ((x0, 1.0), (L, -1.0)):
            bad += [("rim not rounded", a, xc)] if ip(xc + sx * 0.05, *_yz(R - 0.05, a)) else []
            bad += [("rim over-cut", a, xc)] if not ip(xc + sx * 0.4, *_yz(R - 0.4, a)) else []
    check(f"C3 {name} sampling", not bad, f"bad={bad[:6]} (n={len(bad)})")
    return check.failures


def check_s8_fit(plate, upper, preset, p: dict) -> list[str]:
    """plate and the S7 upper, both modeled in install position; overlap = OCP common (diagnostic only)."""
    check = Checks()
    g = s8_geom(p, preset)
    R, x0, kh, hw, name = g["R"], g["x0"], p["key_h"], g["hw"], preset.value
    ip, iu = point_classifier(plate), point_classifier(upper)
    ov = common_volume(upper.wrapped, plate.wrapped)

    bad = []
    rp = R + p["plate_gap"]
    for a in g["arms"]:
        mid = (max(g["key_r0"], 0.5) + g["key_r1"]) / 2.0
        between = a + 30.0  # clear of both presets' csinks (>= 3.7 from any hole centre at r 10.8)
        bad += [("back contact plate", a)] if not ip(x0 + 0.05, *_yz(10.8, between)) else []
        bad += [("back contact upper", a)] if not iu(x0 - 0.05, *_yz(10.8, between)) else []
        gap_pts = [(x0 - kh - 0.05, mid, 0.0), (x0 - p["groove_d"] + 0.05, mid, 0.0),
                   (x0 - kh / 2.0, mid, hw + p["key_gap"] / 2.0), (x0 - kh / 2.0, mid, -(hw + p["key_gap"] / 2.0))]
        if g["key_r1"] >= p["key_r_out"]:
            gap_pts.append((x0 - kh / 2.0, g["key_r1"] + p["key_gap"] / 2.0, 0.0))
        for x, t, lat in gap_pts:
            q = (x, *_yz(t, a, lat))
            if ip(*q) or iu(*q):
                bad.append(("key gap", a, round(x, 2), round(t, 2), round(lat, 2)))
    for a in (g["arms"][0] + 30.0, g["arms"][1] + 30.0):
        q = (g["xs"] + 1.2, *_yz(R + p["plate_gap"] / 2.0, a))
        bad += [("radial gap", a)] if ip(*q) or iu(*q) else []
        bad += [("pocket wall", a)] if not iu(g["xs"] + 1.2, *_yz(rp + 0.05, a)) else []
    for a in g["radial"]:
        for t in (R - 0.3, R + p["plate_gap"] / 2.0, R + 0.5, 13.0):
            q = (g["xs"], *_yz(t, a))
            bad += [("pilot / clearance not coaxial", a, t)] if ip(*q) or iu(*q) else []
    check(f"C4 {name} fit vs S7 upper", abs(ov) <= 0.01 and not bad, f"overlap={ov:.6f} bad={bad[:6]}")
    return check.failures


def check_s8_screws(p: dict, expected: dict | None = None) -> list[str]:
    check = Checks()
    picks = {pr.value: dm.radial_screw_len(p, pr) for pr in PlatePreset}
    check("C5 radial screw pick + head recess", picks == (expected or S8_SCREW) and dm.head_recess(p) >= 0.1 - 1e-9,
          f"picks={picks} head_recess={dm.head_recess(p):.3f}")
    return check.failures


def check_s8_guards(plate_mod=PLATE) -> list[str]:
    check = Checks()

    def outcome(**over) -> str | None:
        try:
            plate_mod.assert_params({**plate_mod.params(), **over})
        except AssertionError as exc:
            return str(exc)
        return None

    def rejects(match: str, **over) -> bool:
        msg = outcome(**over)
        return msg is not None and match in msg

    p = plate_mod.params()
    cases = {
        "plate_gap 0": rejects("plate_gap", plate_gap=0.0),
        "key_h >= groove_d": rejects("groove_d 须 > key_h", key_h=p["groove_d"]),
        "head recess < 0.1": rejects("m2_head_dk", m2_head_dk=5.0),
        "csink to rim": rejects("板外圆圆角", m2_pcd=18.0),
        "key_r_in 0": rejects("key_r_in", key_r_in=0.0),
        "key_r_in > key_r_out": rejects("key_r_in", key_r_in=p["key_r_out"] + 0.1),
        "arm corner past fillet": rejects("臂端角", key_r_out=11.3),
        "arm corner land < 0.3": rejects("臂端角", key_r_out=11.08),  # hypot 11.15: inside the fillet, land 0.15
        "arm to csink (center4)": rejects("center4: 三叉凸起到电机沉头口", key_r_in=6.0),
        "csink to bore (star3)": rejects("star3: 电机沉头口到中心孔", m2_center_d=10.5),
        "pilot x-band vs back": rejects("径向导孔 x 带须距背面", rad_pilot_d=2.1),
        "pilot >= clear": rejects("rad_pilot_d 须∈(0, rad_clear_d)", rad_pilot_d=2.0, rad_clear_d=2.0),
        "pilot depth < 2": rejects("深度须 ≥ 2", rad_pilot_depth=1.9),
        "no screw length": rejects("无可用径向 M2 螺丝", rad_pilot_depth=2.0),
    }
    ok = outcome() is None
    check("C6 guards", ok and all(cases.values()), f"accepts={ok} {cases}")
    return check.failures


# ====================================================================================================
# S9 verifier: three-part assembly per PlatePreset (body grounded, shell + plate fixed).
#
# Expected frames are written from REQUIREMENTS (not from the source connector helpers).
# Interference = OCP BRepAlgoAPI_Common on the solved-placement-transformed bodies (diagnostic only),
# contacts = world probes +-0.05 that must belong to exactly one part.
# ====================================================================================================

TOL = 1e-9
PART_IDS = {"body": "l-link-body", "shell": "l-link-shell"}


def _close(a, b, tol=1e-6) -> bool:
    return all(abs(u - v) <= tol for u, v in zip(a, b))


def _dot(a, b) -> float:
    return sum(u * v for u, v in zip(a, b))


def expected_frames(p: dict) -> dict:
    """World frames (origin, z, x) straight from REQUIREMENTS §装配."""
    phi = math.radians(p["key_phase"])
    by = p["rod_d"] / 2.0 * (2.0 * p["back_cut_frac"] - 1.0)
    fx = p["L"] - p["plate_t"]
    key_x = (0.0, math.cos(phi), math.sin(phi))
    return {
        ("body", "split_datum"): ((0.0, by, 0.0), (0.0, -1.0, 0.0), (1.0, 0.0, 0.0)),
        ("shell", "shell_rim"): ((0.0, by, 0.0), (0.0, -1.0, 0.0), (1.0, 0.0, 0.0)),
        ("body", "mount2_datum"): ((fx, 0.0, 0.0), (1.0, 0.0, 0.0), key_x),
        ("plate", "plate_back"): ((fx, 0.0, 0.0), (1.0, 0.0, 0.0), key_x),
        ("body", "motor_left"): ((0.0, p["d_motor"] / 2.0, 0.0), (0.0, 1.0, 0.0), None),
        ("plate", "motor_right"): ((p["L"], 0.0, 0.0), (1.0, 0.0, 0.0), None),
    }


def _world_frame(solved, cid: str, connector_id: str):
    comp = solved.get_component(cid)
    return comp.placement.compose(comp.item.get_connector(connector_id).placement)


def _trsf(placement):
    from OCP.gp import gp_Trsf

    o, x, y, z = placement.origin, placement.x_axis, placement.y_axis, placement.z_axis
    t = gp_Trsf()
    t.SetValues(x[0], y[0], z[0], o[0], x[1], y[1], z[1], o[1], x[2], y[2], z[2], o[2])
    return t


def world_shape(solved, cid: str):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    comp = solved.get_component(cid)
    return BRepBuilderAPI_Transform(comp.item.body.wrapped, _trsf(comp.placement), True).Shape()


def _shape_volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1e-9)
    return props.Mass()


def common_volume(a, b) -> float:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    op = BRepAlgoAPI_Common(a, b)
    op.Build()
    if not op.IsDone():
        raise RuntimeError("BRepAlgoAPI_Common failed")
    return _shape_volume(op.Shape())


def _bbox(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(shape, box, useTriangulation=False)
    return box.Get()


def _bbox_disjoint(a, b) -> bool:
    return any(a[i + 3] < b[i] or b[i + 3] < a[i] for i in range(3))


def world_classifiers(solved) -> dict:
    """cid -> inside(world point): world point mapped back through the solved placement."""
    out = {}
    for cid in solved.component_ids():
        comp = solved.get_component(cid)
        inv = inverse_placement(comp.placement)
        local = point_classifier(comp.item.body, strict=True)
        out[cid] = (lambda inv_, local_: lambda pt: local_(*inv_.transform_point(pt)))(inv, local)
    return out


def _tag_plane(solved, cid: str, tag: str):
    """World (centroid, normal) of the single planar face carrying `tag` on component cid."""
    comp = solved.get_component(cid)
    faces = ql.faces().where(ql.tag(tag)).resolve(comp.item.body)
    if len(faces) != 1:
        return None
    face = faces[0]
    return comp.placement.transform_point(face.get_center().to_tuple()), comp.placement.transform_vector(face.get_normal_at().to_tuple())


def _split_plane_face(solved, p: dict):
    """Body's flat split face (normal -Y at y=back_y); not tagged in source -> geometric query."""
    comp = solved.get_component("body")
    by = dm.back_y(p)
    faces = ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "PLANE"), ql.prop("geom.normal.y", "<=", -0.999),
        ql.prop("geom.center.y", ">=", by - 0.05), ql.prop("geom.center.y", "<=", by + 0.05),
        ql.prop("geom.area", ">=", 100.0))).resolve(comp.item.body)
    if len(faces) != 1:
        return None
    return comp.placement.transform_point(faces[0].get_center().to_tuple()), comp.placement.transform_vector(faces[0].get_normal_at().to_tuple())


def contact_probes(p: dict, preset: PlatePreset) -> list:
    """(label, world point, expected owner set)."""
    fx, phi = p["L"] - p["plate_t"], p["key_phase"]
    probes = []
    # plate back <-> mount face 2 (annulus r=10.8 between key arms, clear of csinks / grooves)
    for k in range(6):
        y, z = _yz(10.8, phi + 30.0 + 60.0 * k)
        probes += [(f"mount2 body @{30 + 60 * k}", (fx - 0.05, y, z), {"body"}),
                   (f"mount2 plate @{30 + 60 * k}", (fx + 0.05, y, z), {"plate"})]
    # split plane (shell rim ring |z| in (r-wall_t .. r) at y=back_y, straight run)
    by, r = dm.back_y(p), p["rod_d"] / 2.0
    z_rim = (math.sqrt((r - p["wall_t"]) ** 2 - by ** 2) + math.sqrt(r ** 2 - by ** 2)) / 2.0
    for x in (20.0, 32.0, 45.0):
        for z in (z_rim, -z_rim):
            probes += [(f"split body x{x:g} z{z:+.1f}", (x, by + 0.05, z), {"body"}),
                       (f"split shell x{x:g} z{z:+.1f}", (x, by - 0.05, z), {"shell"})]
    # boss bottom <-> pad top (ring r=2 around each boss axis, outside the r=1.35 hole)
    pt = dm.pad_top(p)
    for bx in dm.boss_xs(p):
        for a in (0.0, 90.0, 180.0, 270.0):
            dx, dz = 2.0 * math.cos(math.radians(a)), 2.0 * math.sin(math.radians(a))
            probes += [(f"boss body x{bx:g}@{a:g}", (bx + dx, pt + 0.05, dz), {"body"}),
                       (f"boss pad x{bx:g}@{a:g}", (bx + dx, pt - 0.05, dz), {"shell"})]
    # key top (x=fx-key_h) / groove floor (x=fx-groove_d): 0.2 air gap along each arm
    x_top, x_floor = fx - p["key_h"], fx - p["groove_d"]
    radii = (5.0, 9.0) if preset is PlatePreset.STAR3 else (1.5, 3.0)
    for k in range(3):
        for rr in radii:
            y, z = _yz(rr, phi + 120.0 * k)
            probes += [(f"key gap arm{k} r{rr:g}", ((x_top + x_floor) / 2.0, y, z), set()),
                       (f"key top arm{k} r{rr:g}", (x_top + 0.05, y, z), {"plate"}),
                       (f"groove floor arm{k} r{rr:g}", (x_floor - 0.05, y, z), {"body"})]
    return probes


def check_s9(solved, preset: PlatePreset, p: dict, reference: dict) -> list[str]:
    """reference: {'body'|'shell'|'plate': the part notebook's final body} for C5."""
    ck = Checks()
    fx = p["L"] - p["plate_t"]

    # ---- C1 structure + residuals + identity placements ----
    ids = set(solved.component_ids())
    want_ids = dict(PART_IDS, plate=f"l-link-adapter-{preset.value}")
    part_ids = {cid: solved.get_component(cid).item.part_id for cid in ids}
    report = solved._get_runtime("constraint_report") or {}
    res = report.get("residuals", [])
    res_ok = (len(res) == 2 and all(r["within_tolerance"] and r["translation_error"] <= TOL
                                    and r["angular_error_degrees"] <= TOL for r in res))
    bad_pl = []
    for cid in ids:
        pl = solved.get_component(cid).placement
        if not (_close(pl.origin, (0, 0, 0), TOL) and _close(pl.x_axis, (1, 0, 0), TOL)
                and _close(pl.y_axis, (0, 1, 0), TOL)):
            bad_pl.append((cid, tuple(round(v, 4) for v in pl.origin), tuple(round(v, 4) for v in pl.z_axis)))
    ck("C1 structure+residuals+identity",
       solved.assembly_id == f"l-link-motor-mount-{preset.value}" and ids == set(want_ids)
       and part_ids == want_ids and tuple(solved.grounded_component_ids) == ("body",)
       and len(solved.constraint_ids()) == 2 and res_ok and not bad_pl,
       f"id={solved.assembly_id} parts={part_ids} grounded={solved.grounded_component_ids} "
       f"residuals={[(r['constraint_id'], r['translation_error'], r['angular_error_degrees']) for r in res]} "
       f"non_identity={bad_pl}")

    # ---- C2 connector frames (world) ----
    bad = []
    for (cid, conn), (o, z, x) in expected_frames(p).items():
        try:
            f = _world_frame(solved, cid, conn)
        except Exception as exc:  # noqa: BLE001
            bad.append((cid, conn, str(exc)))
            continue
        if not (_close(f.origin, o) and _close(f.z_axis, z) and (x is None or _close(f.x_axis, x))):
            bad.append((cid, conn, tuple(round(v, 4) for v in f.origin), tuple(round(v, 4) for v in f.z_axis),
                        tuple(round(v, 4) for v in f.x_axis)))
    frames = {}
    for public, cid in (("motor_left", "body"), ("motor_right", "plate")):
        try:
            frames[public] = resolve_item_connector_placement(solved, public)
        except Exception as exc:  # noqa: BLE001
            bad.append(("public", public, str(exc)))
            continue
        direct = _world_frame(solved, cid, public)
        if not (_close(frames[public].origin, direct.origin) and _close(frames[public].z_axis, direct.z_axis)):
            bad.append(("public", public, "differs from component connector"))
    for public, cid, tag in (("motor_left", "body", dm.TAG_MOUNT_LEFT), ("motor_right", "plate", dm.TAG_SEAT)):
        plane = _tag_plane(solved, cid, tag)
        f = frames.get(public)
        if plane is None or f is None or not (_close(plane[0], f.origin) and _close(plane[1], f.z_axis)):
            bad.append(("on-face", public, plane and tuple(round(v, 4) for v in plane[0])))
    perp = (abs(_dot(frames["motor_left"].z_axis, frames["motor_right"].z_axis))
            if len(frames) == 2 else float("nan"))
    ck("C2 connector frames", not bad and perp <= 1e-9, f"bad={bad} z_left.z_right={perp:.2e}")

    # ---- C3 pairwise interference (OCP common on world shapes) ----
    shapes = {cid: world_shape(solved, cid) for cid in ("body", "shell", "plate")}
    ov = {}
    for a, b in (("body", "shell"), ("body", "plate"), ("shell", "plate")):
        try:
            ov[f"{a}/{b}"] = common_volume(shapes[a], shapes[b])
        except Exception as exc:  # noqa: BLE001
            ov[f"{a}/{b}"] = float("inf")
            print(f"  common {a}/{b} error: {exc}")
    disjoint = _bbox_disjoint(_bbox(shapes["shell"]), _bbox(shapes["plate"]))
    ck("C3 pairwise interference", all(v <= 0.01 for v in ov.values()) and disjoint,
       f"overlap={ {k: round(v, 6) for k, v in ov.items()} } shell/plate bbox disjoint={disjoint}")

    # ---- C4 contacts ----
    inside = world_classifiers(solved)
    bad = []
    for label, pt, owners in contact_probes(p, preset):
        got = {cid for cid, f in inside.items() if f(pt)}
        if got != owners:
            bad.append((label, sorted(got)))
    planes = []
    for (ca, pa), (cb, pb), axis in (
            (("plate", _tag_plane(solved, "plate", dm.TAG_BACK)), ("body", _tag_plane(solved, "body", dm.TAG_MOUNT_RIGHT)), 0),
            (("shell", _tag_plane(solved, "shell", dm.TAG_SHELL_RIM)), ("body", _split_plane_face(solved, p)), 1)):
        ok = (pa is not None and pb is not None and abs(pa[0][axis] - pb[0][axis]) <= 1e-6
              and _dot(pa[1], pb[1]) <= -1.0 + 1e-9)
        planes.append((f"{ca}/{cb}", ok, pa and round(pa[0][axis], 6), pb and round(pb[0][axis], 6)))
    ck("C4 contacts", not bad and all(pl[1] for pl in planes),
       f"bad_probes={bad} planes={planes} (probes={len(contact_probes(p, preset))}, key gap "
       f"{p['groove_d'] - p['key_h']:.2f} @ x∈[{fx - p['groove_d']:g},{fx - p['key_h']:g}])")

    # ---- C5 part identity ----
    bad = []
    for cid, ref in reference.items():
        body = solved.get_component(cid).item.body
        dv = abs(precise_volume(body) - precise_volume(ref))
        nf, nr = len(ql.faces().resolve(body)), len(ql.faces().resolve(ref))
        if dv > 1e-6 or nf != nr:
            bad.append((cid, round(dv, 6), nf, nr))
    meta = solved.get_component("plate").item.body.get_metadata("plate_preset")
    ck("C5 part identity", not bad and meta == preset.value, f"bad={bad} plate_preset={meta}")
    return ck.failures

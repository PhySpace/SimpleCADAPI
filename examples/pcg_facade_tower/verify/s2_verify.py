"""S2 gate: panel family (every vision / solid / fin type used by RECT, CHAMFER and L_SHAPE), measured geometry.

  P1 body        Part id == type id; one solid; BRepCheck valid
  P2 envelope    panel bbox == [j/2, w - j/2] x [j/2, h - j/2] x [0, frame_d] (1e-6); V3 transport <= 1600 x 4200 x 600
  P3 frame       +Z planar area at z = frame_d and -Z planar area at z = 0 both == frame ring area
  P4 glass       vision: exactly one face tagged facade.vision_glass, planar +Z at frame_d - glass_recess,
                 area == layout._glass_area (the WWR numerator); solid: no tagged face
  P5 volume      == ring + recessed plates (analytic, 1e-6 relative)
  P6 fin (V5)    side-face normals measure the bin angle +/- 0.05 deg; side planes fin_t apart; root flush on z = 0
                 with width fin_t / cos(a); tip z <= fin_depth + 1 (building line: frame_d + fin_depth + 1);
                 y span [j/2, h - j/2]; volume fin_t * fin_depth * (h - j)
  P7 cache       rebuilding every type through the Part factory hits

    ../../../.venv/bin/python s2_verify.py
"""
from __future__ import annotations

import math
import sys

from _common import report, tight_bbox

import layout as L
import panels as P
from simplecadapi import ql

TOL = 1.0e-6
ENVELOPE = (1600.0, L.MAX_PANEL_H, 600.0)


def _faces(body, nz: float, z: float):
    return ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop("geom.normal.z", ">=", nz - 1.0e-9) if nz > 0 else ql.prop("geom.normal.z", "<=", nz + 1.0e-9),
        ql.prop("geom.center.z", ">=", z - 1.0e-6), ql.prop("geom.center.z", "<=", z + 1.0e-6),
    )).resolve(body)


def _area(faces) -> float:
    return sum(f.get_area() for f in faces)


def _valid(body) -> bool:
    from OCP.BRepCheck import BRepCheck_Analyzer
    return BRepCheck_Analyzer(body.wrapped).IsValid()


def _rect_area(r) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def check_panel(tid: str, spec: dict, body, p: L.FacadeParams) -> list[str]:
    bad = []
    w, h, j, fd = spec["w"], spec["h"], p.joint, p.frame_d
    spandrel = spec.get("spandrel", 0.0)
    ops = P.openings(w, h, spandrel if spec["family"] == "vision" else 0.0, p.frame_sight, j)

    x0, y0, z0, x1, y1, z1 = tight_bbox(body)
    want = (j / 2.0, j / 2.0, 0.0, w - j / 2.0, h - j / 2.0, fd)
    if max(abs(a - b) for a, b in zip((x0, y0, z0, x1, y1, z1), want)) > TOL:
        bad.append(f"P2 {tid}: bbox {tuple(round(v, 6) for v in (x0, y0, z0, x1, y1, z1))} != {want}")
    size = (x1 - x0, y1 - y0, z1 - z0)
    if any(s > e for s, e in zip(size, ENVELOPE)):
        bad.append(f"P2 {tid}: size {tuple(round(s) for s in size)} exceeds transport {ENVELOPE}")

    ring = (w - j) * (h - j) - sum(_rect_area(r) for r in ops.values())
    front, back = _area(_faces(body, 1.0, fd)), _area(_faces(body, -1.0, 0.0))
    if abs(front - ring) > TOL * ring or abs(back - ring) > TOL * ring:
        bad.append(f"P3 {tid}: frame face areas front {front:.3f} / back {back:.3f} != ring {ring:.3f}")

    tagged = ql.faces().where(ql.tag(P.GLASS_TAG)).resolve(body)
    if spec["family"] == "vision":
        design = L._glass_area(w, h, spandrel, p)
        if len(tagged) != 1:
            bad.append(f"P4 {tid}: {len(tagged)} tagged glass faces")
        else:
            g = tagged[0]
            n, c = g.get_normal_at(), g.get_center()
            if abs(n.z - 1.0) > 1.0e-9 or abs(c.z - (fd - p.glass_recess)) > TOL:
                bad.append(f"P4 {tid}: glass face normal {n.z:.9f} at z {c.z:.6f}")
            if abs(g.get_area() - design) > TOL * design or abs(_rect_area(ops["vision"]) - design) > TOL * design:
                bad.append(f"P4 {tid}: glass area {g.get_area():.3f} / opening {_rect_area(ops['vision']):.3f} "
                           f"!= design {design:.3f}")
    elif tagged:
        bad.append(f"P4 {tid}: solid panel carries {len(tagged)} glass tags")

    plates = 0.0
    if spec["family"] == "vision":
        plates += _rect_area(ops["vision"]) * p.glass_t
        if "spandrel" in ops:
            plates += _rect_area(ops["spandrel"]) * (p.glass_t + p.glass_recess / 2.0)
    else:
        plates += _rect_area(ops["vision"]) * (p.glass_t + p.glass_recess / 2.0)
    vol = ring * fd + plates
    if abs(body.get_volume() - vol) > TOL * vol:
        bad.append(f"P5 {tid}: volume {body.get_volume():.3f} != {vol:.3f}")
    return bad


def check_fin(tid: str, spec: dict, body, p: L.FacadeParams) -> list[str]:
    bad = []
    a, h, j = spec["angle"], spec["h"], p.joint
    th = math.radians(a)
    sides = ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "PLANE"),
        ql.prop("geom.normal.y", ">=", -1.0e-9), ql.prop("geom.normal.y", "<=", 1.0e-9),
        ql.prop("geom.normal.x", ">=", 1.0e-6),
    )).resolve(body)
    if len(sides) != 1:
        bad.append(f"P6 {tid}: {len(sides)} +x side faces")
    else:
        n = sides[0].get_normal_at()
        measured = math.degrees(math.atan2(-n.z, n.x))  # side along (sin a, cos a) -> outward normal (cos a, -sin a)
        if abs(measured - a) > 0.05:
            bad.append(f"P6 {tid}: side normal measures {measured:.4f} deg != bin {a}")
        c_r = sides[0].get_center()
        opp = ql.faces().where(ql.and_(ql.prop("geom.type", "==", "PLANE"),
                                       ql.prop("geom.normal.x", "<=", -1.0e-6))).resolve(body)
        if len(opp) == 1:
            c_l = opp[0].get_center()
            gap = (c_r.x - c_l.x) * n.x + (c_r.z - c_l.z) * n.z
            if abs(gap - p.fin_t) > TOL:
                bad.append(f"P6 {tid}: side planes {gap:.6f} apart != fin_t {p.fin_t}")
        else:
            bad.append(f"P6 {tid}: {len(opp)} -x side faces")
    root = _faces(body, -1.0, 0.0)
    want_root = p.fin_t / math.cos(th) * (h - j)
    if abs(_area(root) - want_root) > TOL * want_root:
        bad.append(f"P6 {tid}: root area {_area(root):.3f} != {want_root:.3f} (not flush on the frame face)")
    x0, y0, z0, x1, y1, z1 = tight_bbox(body)
    if abs(z0) > TOL or z1 > p.fin_depth + 1.0 or abs(y0 - j / 2.0) > TOL or abs(y1 - (h - j / 2.0)) > TOL:
        bad.append(f"P6 {tid}: bbox z [{z0:.6f}, {z1:.3f}] y [{y0:.6f}, {y1:.6f}]")
    if a != 0.0 and math.copysign(1.0, (x0 + x1) / 2.0) != math.copysign(1.0, a):
        bad.append(f"P6 {tid}: tip leans to x {(x0 + x1) / 2.0:.1f}, angle {a} (sign convention broken)")
    if any(s > e for s, e in zip((x1 - x0, y1 - y0, z1 - z0), ENVELOPE)):
        bad.append(f"P6 {tid}: fin exceeds transport {ENVELOPE}")
    vol = p.fin_t * p.fin_depth * (h - j)
    if abs(body.get_volume() - vol) > TOL * vol:
        bad.append(f"P6 {tid}: volume {body.get_volume():.3f} != {vol:.3f}")
    return bad


def all_types() -> dict:
    """Union of the vision / solid / fin types of the three default plans (identical ids must mean identical specs)."""
    out = {}
    for kind in L.PlanKind:
        for tid, spec in L.build_schedule(L.default_params(plan_kind=kind)).types.items():
            if spec["family"] == "corner":
                continue
            if out.setdefault(tid, spec) != spec:
                raise AssertionError(f"type id {tid} names two specs: {out[tid]} / {spec}")
    return out


def check_body(tid: str, spec: dict, part, p: L.FacadeParams) -> list[str]:
    bad = []
    if part.part_id != tid:
        bad.append(f"P1 {tid}: part id {part.part_id}")
    solids = ql.solids().resolve(part.body)
    if len(solids) != 1:
        return bad + [f"P1 {tid}: {len(solids)} solids"]
    if not _valid(part.body):
        bad.append(f"P1 {tid}: BRep invalid")
    return bad + (check_fin if spec["family"] == "fin" else check_panel)(tid, spec, part.body, p)


def main() -> int:
    p = L.default_params()
    types = all_types()
    failures, parts = [], {}
    for tid, spec in sorted(types.items()):
        result = P.make_panel_part(tid, spec, p)
        parts[tid] = result.value
        failures += check_body(tid, spec, result.value, p)
    fams = {}
    for spec in types.values():
        fams[spec["family"]] = fams.get(spec["family"], 0) + 1
    print(f"-- checked {len(types)} types {fams}")
    misses = [tid for tid, spec in types.items() if not P.make_panel_part(tid, spec, p).cache_report.hit]
    if misses:
        failures.append(f"P7 warm rebuild missed {misses}")
    return report("S2 panels", failures)


if __name__ == "__main__":
    sys.exit(main())

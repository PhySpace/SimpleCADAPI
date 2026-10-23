"""S3 gate: corner pieces, floor slabs and the entrance canopy, measured on the built solids.

Part checks (local frame):
  K1 corner     Part id == type id; one solid; BRepCheck valid; y span [j/2, h - j/2];
                volume == profile area x (h - j)
  K4 slab       one solid, valid; z span [0, slab_t]; one side face per tier edge, each parallel to it and
                slab_gap inside the building line; volume == |plan area| x slab_t
  K5 canopy     one solid, valid; bbox == layout canopy box; centred on the south edge; both ends on lobby
                module joints; z0 on the lobby row joint
Fit checks (placed in world through the layout frames, per plan, one band of each (tier, kind)):
  K2 corner     (V7) outer faces coplanar with both panel bands' outer planes (building line + frame_d),
                building-line faces on the building line, end faces at corner_c - joint/2 from the vertex
  K6 joint      min distance corner <-> last panel of the incoming edge and first panel of the outgoing edge == joint
                (+/- 5e-4: A7 rounds type widths to 0.001 mm, the joint absorbs it)
  K3 slab       floor slabs sit on a realized floor band level of their tier (ground at 0), roof slabs end at
                their tier's roof (parapet level); a tier's first floor stands on the roof below; min distance
                slab <-> same-level panels / corners == slab_gap (roof: the top floor's); terrace: roof k-1 <->
                tier k first-floor panels / corners / fins == joint/2 (the panels stand j/2 above it)
  K7 canopy     min distance canopy <-> south lobby panels == joint (the standoff)

    ../../../.venv/bin/python s3_verify.py
"""
from __future__ import annotations

import sys

from _common import min_distance, place_shape, report, tight_bbox

import corners as C
import layout as L
import panels as P
import simplecadapi as scad
import slabs as S
from simplecadapi import ql

TOL = 1.0e-6
# A7: panel types are built at the width rounded to 0.001 mm and placed at the exact layout start, so the joint
# after a closer absorbs up to 5e-4 mm.
JOINT_TOL = 0.5 * 10.0 ** -L.TYPE_ROUND_DIGITS + TOL


def _valid(body) -> bool:
    from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
    return BRepCheck_Analyzer(body.wrapped).IsValid()


def _one_valid_solid(tag: str, tid: str, part) -> list[str]:
    if part.part_id != tid:
        return [f"{tag} {tid}: part id {part.part_id}"]
    solids = ql.solids().resolve(part.body)
    if len(solids) != 1:
        return [f"{tag} {tid}: {len(solids)} solids"]
    return [] if _valid(part.body) else [f"{tag} {tid}: BRep invalid"]


def _side_planes(body) -> list[tuple]:
    """(unit plan normal, plan centre, area) of every vertical planar face."""
    out = []
    for f in ql.faces().where(ql.prop("geom.type", "==", "PLANE")).resolve(body):
        n, c = f.get_normal_at(), f.get_center()
        if abs(n.z) < 1.0e-9:
            out.append(((n.x, n.y), (c.x, c.y), f.get_area()))
    return out


def _has_plane(planes, normal, anchor, offset) -> bool:
    """A face with this outward plan normal whose plane lies `offset` along it from `anchor`."""
    return any(abs(n[0] - normal[0]) < 1.0e-9 and abs(n[1] - normal[1]) < 1.0e-9
               and abs(L._dot(normal, L._sub(c, anchor)) - offset) < TOL for n, c, _ in planes)


# ---------------------------------------------------------------- part checks


def check_corner(tid: str, spec: dict, part, p: L.FacadeParams) -> list[str]:
    bad = _one_valid_solid("K1", tid, part)
    if bad:
        return bad
    j, h = p.joint, spec["h"]
    _, y0, _, _, y1, _ = tight_bbox(part.body)
    if abs(y0 - j / 2.0) > TOL or abs(y1 - (h - j / 2.0)) > TOL:
        bad.append(f"K1 {tid}: y span [{y0:.6f}, {y1:.6f}] != [{j / 2.0}, {h - j / 2.0}]")
    area = abs(L.signed_area(C.corner_section(spec["turn"], p.corner_c, p.frame_d, j)))
    vol = area * (h - j)
    if abs(part.body.get_volume() - vol) > TOL * vol:
        bad.append(f"K1 {tid}: volume {part.body.get_volume():.3f} != profile x height {vol:.3f}")
    return bad


def check_slab(sched: L.FacadeSchedule, tier: int, part) -> list[str]:
    tid = S.slab_type_id(tier)
    bad = _one_valid_solid("K4", tid, part)
    if bad:
        return bad
    p = sched.params
    _, _, z0, _, _, z1 = tight_bbox(part.body)
    if abs(z0) > TOL or abs(z1 - p.slab_t) > TOL:
        bad.append(f"K4 {tid}: z span [{z0:.6f}, {z1:.6f}] != [0, {p.slab_t}]")
    planes = _side_planes(part.body)
    frames = L.edge_frames([tuple(v) for v in sched.tiers[tier]])
    if len(planes) != len(frames):
        bad.append(f"K4 {tid}: {len(planes)} side faces for {len(frames)} tier edges")
    for e, fr in enumerate(frames):
        if not _has_plane(planes, fr["n"], fr["v0"], -p.slab_gap):
            bad.append(f"K4 {tid}: no side face slab_gap {p.slab_gap} inside edge {e}")
    vol = abs(L.signed_area(L.slab_plans(sched)[tier])) * p.slab_t
    if abs(part.body.get_volume() - vol) > TOL * vol:
        bad.append(f"K4 {tid}: volume {part.body.get_volume():.1f} != {vol:.1f}")
    return bad


def check_canopy(sched: L.FacadeSchedule, part) -> list[str]:
    bad = _one_valid_solid("K5", S.CANOPY_ID, part)
    if bad:
        return bad
    box, lobby = L.canopy_box(sched), sched.band("lobby")
    want = (box["x0"], box["y0"], box["z0"], box["x1"], box["y1"], box["z1"])
    got = tight_bbox(part.body)
    if max(abs(a - b) for a, b in zip(got, want)) > TOL:
        bad.append(f"K5 canopy: bbox {tuple(round(v, 6) for v in got)} != {want}")
    fr = L.edge_frames([tuple(v) for v in sched.tiers[0]])[0]
    mid = fr["v0"][0] + fr["length"] / 2.0
    if abs((got[0] + got[3]) / 2.0 - mid) > TOL:
        bad.append(f"K5 canopy: centre x {(got[0] + got[3]) / 2.0:.6f} != south edge midpoint {mid:.6f}")
    south = [r for r in lobby["panels"] if r["edge"] == 0]
    starts = [fr["v0"][0] + r["s0"] for r in south]
    ends = [fr["v0"][0] + r["s0"] + r["w"] for r in south]
    if min(abs(got[0] - s) for s in starts) > TOL or min(abs(got[3] - e) for e in ends) > TOL:
        bad.append(f"K5 canopy: ends x [{got[0]:.6f}, {got[3]:.6f}] not on south lobby module joints")
    if lobby["rows"] > 1 and abs(got[2] - lobby["height"]) > TOL:
        bad.append(f"K5 canopy: z0 {got[2]:.6f} not on the lobby row joint {lobby['height']}")
    return bad


# ---------------------------------------------------------------- fit checks (world)


class Parts:
    """Part bodies by type id, memoized here to avoid rebuilding within one gate."""

    def __init__(self, sched: L.FacadeSchedule):
        self.sched, self.bodies = sched, {}

    def body(self, tid: str):
        if tid not in self.bodies:
            spec, p = self.sched.types[tid], self.sched.params
            make = C.make_corner_part if spec["family"] == "corner" else P.make_panel_part
            self.bodies[tid] = make(tid, spec, p).value.body
        return self.bodies[tid]

    def panel(self, band: dict, rec: dict, level: float):
        return place_shape(self.body(rec["type_id"]), L.panel_frame(self.sched, band, rec, level))

    def corner(self, band: dict, rec: dict, level: float):
        return place_shape(self.body(rec["type_id"]), L.corner_frame(self.sched, band, rec, level))


def fit_bands(sched: L.FacadeSchedule) -> list[dict]:
    """One band per (tier, kind): corners and closers repeat unchanged across a tier's phases."""
    seen, out = set(), []
    for b in sched.bands:
        if (b["tier"], b["band"]) not in seen:
            seen.add((b["tier"], b["band"]))
            out.append(b)
    return out


def _edge_panel(band: dict, edge: int, first: bool) -> dict:
    recs = [r for r in band["panels"] if r["edge"] == edge]
    return min(recs, key=lambda r: r["slot"]) if first else max(recs, key=lambda r: r["slot"])


def check_corner_fit(parts: Parts, band: dict, rec: dict) -> list[str]:
    sched, p = parts.sched, parts.sched.params
    level = L.band_levels(sched, band["band_id"])[0]
    poly = [tuple(v) for v in sched.tiers[band["tier"]]]
    frames = L.edge_frames(poly)
    i = rec["vertex"]
    fin, fout, v = frames[i - 1], frames[i], poly[i]
    body = parts.corner(band, rec, level)
    planes, c = _side_planes(body), p.corner_c - p.joint / 2.0
    where = f"{band['band_id']} v{i} ({rec['turn']:+.1f} deg)"
    bad = []
    for name, normal, offset in (("incoming outer", fin["n"], p.frame_d), ("outgoing outer", fout["n"], p.frame_d),
                                 ("incoming building line", L._mul(fin["n"], -1.0), 0.0),
                                 ("outgoing building line", L._mul(fout["n"], -1.0), 0.0),
                                 ("incoming end", L._mul(fin["t"], -1.0), c), ("outgoing end", fout["t"], c)):
        if not _has_plane(planes, normal, v, offset):
            bad.append(f"K2 {where}: no {name} face at {offset}")
    _, _, z0, _, _, z1 = tight_bbox(body)
    if abs(z0 - (level + p.joint / 2.0)) > TOL or abs(z1 - (level + band["height"] - p.joint / 2.0)) > TOL:
        bad.append(f"K2 {where}: z span [{z0:.6f}, {z1:.6f}] off the band")
    for side, prec in (("incoming", _edge_panel(band, (i - 1) % len(poly), first=False)),
                       ("outgoing", _edge_panel(band, i, first=True))):
        gap = min_distance(body, parts.panel(band, prec, level))
        if abs(gap - p.joint) > JOINT_TOL:
            bad.append(f"K6 {where}: {side} panel {prec['type_id']} gap {gap:.6f} != joint {p.joint}")
    return bad


def check_slab_fit(parts: Parts, slab_bodies: dict) -> list[str]:
    sched, p = parts.sched, parts.sched.params
    bad = []
    floor_levels = {0: {0.0}}
    for b in sched.bands:
        if b["band"] == L.Band.TOWER.value:
            floor_levels.setdefault(b["tier"], set()).update(round(z, 6) for z in L.band_levels(sched, b["band_id"]))
    insts = L.slab_instances(sched)
    for inst in insts:
        if inst["role"].startswith("roof"):
            roof = sched.levels[inst["role"]]
            if abs(inst["level"] + p.slab_t - roof) > TOL or abs(sched.band(f"parapet{inst['tier']}")["level"] - roof) > TOL:
                bad.append(f"K3 slab {inst['role']}: [{inst['level']}, +slab_t] does not end at the roof {roof}")
        elif round(inst["level"], 6) not in floor_levels[inst["tier"]]:
            bad.append(f"K3 slab {inst['role']}: level {inst['level']} is no floor level of tier {inst['tier']}")
    have = {round(i["level"], 6) for i in insts if not i["role"].startswith("roof")}
    for rec in sched.floors:
        if round(rec["level"], 6) not in have:
            below = sched.levels.get(f"roof{rec['tier'] - 1}")
            if below is None or abs(below - rec["level"]) > TOL:
                bad.append(f"K3 floor{rec['floor']}: no slab and not standing on a roof")

    def placed_slab(inst):
        return scad.translate_shape(shape=slab_bodies[inst["tier"]], vector=(0.0, 0.0, inst["level"]))

    def edge_ends(band, level):
        near = [parts.panel(band, _edge_panel(band, e, first=True), level) for e in {r["edge"] for r in band["panels"]}]
        return near + [parts.corner(band, rec, level) for rec in band["corners"]]

    for band in fit_bands(sched):  # floor slabs at their band level, behind the spandrel
        level = L.band_levels(sched, band["band_id"])[0]
        inst = next((i for i in insts if abs(i["level"] - level) < TOL and not i["role"].startswith("roof")), None)
        if inst is None:
            continue
        gap = min(min_distance(placed_slab(inst), shape) for shape in edge_ends(band, level))
        if abs(gap - p.slab_gap) > TOL:
            bad.append(f"K3 {band['band_id']}: slab clearance {gap:.6f} != slab_gap {p.slab_gap}")
    for inst in (i for i in insts if i["role"].startswith("roof")):
        k = inst["tier"]
        top = next(b for b in sched.bands if b["band"] == L.Band.TOWER.value and b["tier"] == k
                   and max(sched.floor_types[b["band_id"]]["floors"]) == max(
                       r["floor"] for r in sched.floors if r["tier"] == k))
        gap = min(min_distance(placed_slab(inst), shape) for shape in edge_ends(top, inst["level"] + p.slab_t - p.floor_h))
        if abs(gap - p.slab_gap) > TOL:
            bad.append(f"K3 roof{k}: clearance to the top floor {gap:.6f} != slab_gap {p.slab_gap}")
        if k + 1 >= len(sched.tiers):
            continue
        first = sched.band(f"tier{k + 1}-phase0")
        level = sched.levels[f"roof{k}"]
        near = [parts.panel(first, r, level) for r in first["panels"]] + edge_ends(first, level)
        near += [place_shape(parts.body(r["type_id"]), L.fin_frame(sched, first, r, level)) for r in first["fins"]]
        gap = min(min_distance(placed_slab(inst), shape) for shape in near)
        if abs(gap - p.joint / 2.0) > TOL:
            bad.append(f"K3 roof{k} terrace: clearance to tier {k + 1} first floor {gap:.6f} != joint/2 {p.joint / 2.0}")
    return bad


def check_canopy_fit(parts: Parts, canopy_body) -> list[str]:
    sched, p = parts.sched, parts.sched.params
    band = sched.band("lobby")
    south = [r for r in band["panels"] if r["edge"] == 0]
    gaps = [min_distance(canopy_body, parts.panel(band, r, level))
            for level in L.band_levels(sched, "lobby") for r in south]
    if abs(min(gaps) - p.joint) > TOL:
        return [f"K7 canopy: standoff {min(gaps):.6f} != joint {p.joint}"]
    return []


def corner_types() -> dict:
    out = {}
    for kind in L.PlanKind:
        for tid, spec in L.build_schedule(L.default_params(plan_kind=kind)).types.items():
            if spec["family"] == "corner" and out.setdefault(tid, spec) != spec:
                raise AssertionError(f"type id {tid} names two specs: {out[tid]} / {spec}")
    return out


def main() -> int:
    failures = []
    p0 = L.default_params()
    ctypes = corner_types()
    for tid, spec in sorted(ctypes.items()):
        failures += check_corner(tid, spec, C.make_corner_part(tid, spec, p0).value, p0)
    turns = sorted({s["turn"] for s in ctypes.values()})
    print(f"-- {len(ctypes)} corner types, turns {turns}")

    for kind in L.PlanKind:
        sched = L.build_schedule(L.default_params(plan_kind=kind))
        parts = Parts(sched)
        slab_bodies = {}
        for k in range(len(sched.tiers)):
            part = S.make_slab_part(sched, k).value
            failures += check_slab(sched, k, part)
            slab_bodies[k] = part.body
        n_fit = 0
        for band in fit_bands(sched):
            for rec in band["corners"]:
                failures += check_corner_fit(parts, band, rec)
                n_fit += 1
        failures += check_slab_fit(parts, slab_bodies)
        canopy = S.make_canopy_part(sched).value
        failures += check_canopy(sched, canopy) + check_canopy_fit(parts, canopy.body)
        print(f"-- {kind.value}: {len(sched.tiers)} slab types, {len(L.slab_instances(sched))} slab instances, "
              f"{n_fit} corner fits, canopy {L.canopy_box(sched)['modules']} modules")
    return report("S3 corners / slabs / canopy", failures)


if __name__ == "__main__":
    sys.exit(main())

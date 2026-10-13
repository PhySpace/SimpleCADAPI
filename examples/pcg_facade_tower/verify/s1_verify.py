"""S1 gate: layout engine (pure data).

  C1 closure       every band, every edge: corner_c + sum(widths) + corner_c == edge length (1e-9); slots contiguous
  C2 closers       both end slots equal, solid, in [closer_min, closer_min + w_std/2)
  C3 guards        each guard rejects just past its boundary and accepts just inside (fail loudly, never degrade)
  C4 WWR           design glass / gross per orientation within 0.03 of target
  C5 rationalized  one standard vision + one standard solid type; fin types <= K; floor types == tiers x P; ids valid
  C6 fins          quantization error <= 90 / (2 (K - 1)); north-facing edges carry no fins; every fin panel has
                   exactly one fin record at its right-jamb root with the same angle
  C10 transport    every band height <= MAX_PANEL_H; lobby rows x row height == lobby_h
  C7 corners       corner profiles for every turn in use: simple, CCW, area > 0; reflex corners fit
  C8 vertical      floor levels, tier assignment, roof levels, setback depth per tier
  C9 plans         RECT / CHAMFER / L_SHAPE all schedule; JSON round-trip

    ../../../.venv/bin/python s1_verify.py
"""
from __future__ import annotations

import json
import math
import re
import sys

from _common import report  # noqa: F401  (sys.path setup)

import layout as L

ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,255}$")
EPS = 1.0e-9


def check_s1(sched: L.FacadeSchedule) -> list[str]:
    p = sched.params
    bad: list[str] = []

    # C1 / C2
    for b in sched.bands:
        frames = L.edge_frames(sched.tiers[b["tier"]])
        for e, fr in enumerate(frames):
            recs = sorted((r for r in b["panels"] if r["edge"] == e), key=lambda r: r["slot"])
            if not recs:
                bad.append(f"C1 {b['band_id']} edge {e}: no panels")
                continue
            total = 2.0 * p.corner_c + sum(r["w"] for r in recs)
            if abs(total - fr["length"]) > EPS * max(1.0, fr["length"]):
                bad.append(f"C1 {b['band_id']} edge {e}: widths sum {total:.9f} != length {fr['length']:.9f}")
            s = p.corner_c
            for r in recs:
                if abs(r["s0"] - s) > EPS * max(1.0, fr["length"]):
                    bad.append(f"C1 {b['band_id']} edge {e} slot {r['slot']}: s0 {r['s0']:.6f} != {s:.6f}")
                s = r["s0"] + r["w"]
            first, last = recs[0], recs[-1]
            if abs(first["w"] - last["w"]) > EPS * max(1.0, fr["length"]):
                bad.append(f"C2 {b['band_id']} edge {e}: closers asymmetric {first['w']:.6f} / {last['w']:.6f}")
            for r in (first, last):
                if not (p.closer_min - EPS <= r["w"] < p.closer_min + p.w_std / 2.0):
                    bad.append(f"C2 {b['band_id']} edge {e}: closer {r['w']:.6f} outside "
                               f"[{p.closer_min}, {p.closer_min + p.w_std / 2.0})")
                if r["kind"] != "solid":
                    bad.append(f"C2 {b['band_id']} edge {e}: closer slot {r['slot']} is {r['kind']}")
            for r in recs[1:-1]:
                if abs(r["w"] - p.w_std) > EPS:
                    bad.append(f"C2 {b['band_id']} edge {e} slot {r['slot']}: inner width {r['w']} != w_std")

    # C4
    wwr = L.design_wwr(sched)
    for o, target in p.wwr_target:
        if o in wwr and abs(wwr[o] - target) > L.WWR_TOL:
            bad.append(f"C4 WWR {o}: design {wwr[o]:.4f} vs target {target}")

    # C5
    std = sched.stats["standard_panel_types"]
    if len(std) > 2:
        bad.append(f"C5 {len(std)} standard panel types > 2: {std}")
    if len(sched.stats["fin_types"]) > p.fin_bins:
        bad.append(f"C5 {len(sched.stats['fin_types'])} fin types > K = {p.fin_bins}")
    expected_ft = sum(1 for k in range(len(sched.tiers)) for ph in range(p.fin_period_floors)
                      if any((f - 1) // p.setback_every == k and (f - 1) % p.fin_period_floors == ph
                             for f in range(1, p.n_floors + 1)))
    if len(sched.floor_types) != expected_ft:
        bad.append(f"C5 floor types {len(sched.floor_types)} != tiers x phases {expected_ft}")
    used = {r["type_id"] for b in sched.bands for r in b["panels"] + b["corners"] + b["fins"]}
    if used != set(sched.types):
        bad.append(f"C5 type table mismatch: unused {sorted(set(sched.types) - used)}, "
                   f"unregistered {sorted(used - set(sched.types))}")
    for tid in list(sched.types) + list(sched.floor_types):
        if not ID_RE.match(tid):
            bad.append(f"C5 invalid identifier {tid!r}")

    # C6
    bins = L.fin_bin_angles(p.fin_bins)
    limit = 90.0 / (2.0 * (p.fin_bins - 1)) + EPS
    for b in sched.bands:
        frames = L.edge_frames(sched.tiers[b["tier"]])
        fins = {}
        for fr_ in b["fins"]:
            fins.setdefault((fr_["edge"], fr_["slot"]), []).append(fr_)
        fin_panels = {(r["edge"], r["slot"]) for r in b["panels"] if r.get("fin") is not None}
        if set(fins) != fin_panels:
            bad.append(f"C6 {b['band_id']}: fin records {len(fins)} do not match fin panels {len(fin_panels)}")
        for r in b["panels"]:
            fin = r.get("fin")
            if fin is None:
                continue
            recs = fins.get((r["edge"], r["slot"]), [])
            if len(recs) != 1 or recs[0]["angle"] != fin or abs(recs[0]["s"] - L.fin_root_s(r["s0"], r["w"], p)) > EPS:
                bad.append(f"C6 {b['band_id']} edge {r['edge']} slot {r['slot']}: fin record mismatch {recs}")
            if not L.edge_has_fins(frames[r["edge"]]["n"], p):
                bad.append(f"C6 {b['band_id']} edge {r['edge']}: fin on a non-sun edge")
            if min(abs(fin - a) for a in bins) > EPS:
                bad.append(f"C6 {b['band_id']}: fin {fin} not a bin angle")
            err = abs(max(-L.FIN_LIMIT, min(L.FIN_LIMIT, r["fin_raw"])) - fin)
            if err > limit:
                bad.append(f"C6 {b['band_id']} edge {r['edge']} slot {r['slot']}: quant error {err:.4f} > {limit:.4f}")

    # C7
    for turn in sorted({c["turn"] for b in sched.bands for c in b["corners"]}):
        try:
            prof = L.corner_profile_local(turn, p)
        except L.LayoutError as exc:
            bad.append(f"C7 corner turn {turn:.3f}: {exc}")
            continue
        if L.signed_area(prof) <= 0.0 or not L.is_simple(prof):
            bad.append(f"C7 corner turn {turn:.3f}: profile not simple / CCW")

    # C10
    for b in sched.bands:
        if b["height"] > L.MAX_PANEL_H + EPS:
            bad.append(f"C10 {b['band_id']}: band height {b['height']} > {L.MAX_PANEL_H}")
    lobby = sched.band("lobby")
    if abs(lobby["rows"] * lobby["height"] - p.lobby_h) > EPS:
        bad.append(f"C10 lobby rows {lobby['rows']} x {lobby['height']} != {p.lobby_h}")

    # C8
    for rec in sched.floors:
        f = rec["floor"]
        if abs(rec["level"] - (p.lobby_h + (f - 1) * p.floor_h)) > EPS:
            bad.append(f"C8 floor {f}: level {rec['level']}")
        if rec["tier"] != (f - 1) // p.setback_every:
            bad.append(f"C8 floor {f}: tier {rec['tier']}")
        if f not in sched.floor_types[rec["floor_type"]]["floors"]:
            bad.append(f"C8 floor {f}: not listed under its floor type {rec['floor_type']}")
    base = L.edge_frames(sched.tiers[0])
    for k, poly in enumerate(sched.tiers):
        for eb, et in zip(base, L.edge_frames(poly)):  # each tier edge line sits k * depth inside the base edge line
            gap = L._dot(L._sub(eb["v0"], et["v0"]), eb["n"])
            if abs(gap - k * p.setback_depth) > 1.0e-6:
                bad.append(f"C8 tier {k}: edge setback {gap:.6f} != {k * p.setback_depth}")
        top = max(f for f in range(1, p.n_floors + 1) if (f - 1) // p.setback_every == k)
        if abs(sched.levels[f"roof{k}"] - (p.lobby_h + top * p.floor_h)) > EPS:
            bad.append(f"C8 roof{k} level {sched.levels[f'roof{k}']}")

    return bad


# ---------------------------------------------------------------- C3 guard matrix


def _rejects(stage, **overrides) -> bool:
    """stage: the narrowest engine entry that owns the guard, so a neighbouring guard cannot mask it."""
    try:
        params = L.default_params(**overrides)
        stage(params)
    except L.LayoutError:
        return True
    return False


def guard_matrix() -> list[str]:
    p = L.default_params()
    d = 1.0e-6
    # shortest default edge: tier-top chamfer. Setback that shrinks it to exactly 2c + 2 closer_min is the boundary.
    chamfer_top = L.edge_frames(L.tier_plans(p)[-1])[2]["length"]
    tiers = len(L.tier_plans(p))
    # the chamfer edge shrinks by 2 * tan(22.5 deg) per unit of setback
    shrink = 2.0 * math.tan(math.radians(22.5)) * (tiers - 1)
    limit_depth = p.setback_depth + (chamfer_top - 2.0 * p.corner_c - 2.0 * p.closer_min) / shrink
    full, params_only, tiers_only = L.build_schedule, L.assert_params, L.tier_plans
    rows = [
        # (name, entry, overrides past boundary -> must reject, overrides just inside -> must accept)
        ("edge too short", full, dict(setback_depth=limit_depth + d), dict(setback_depth=limit_depth - d)),
        ("closer_min >= w_std", params_only, dict(closer_min=p.w_std), dict(closer_min=p.w_std - d)),
        ("K < 2", params_only, dict(fin_bins=1), dict(fin_bins=2)),
        ("P not multiple of 4", params_only, dict(fin_period_floors=6), dict(fin_period_floors=8)),
        ("corner_c <= frame_d + joint", params_only, dict(corner_c=p.frame_d + p.joint),
         dict(corner_c=p.frame_d + p.joint + d)),
        ("setback reverses an edge", tiers_only,  # RECT, 2 tiers: the 24000 edge vanishes at depth 12000
         dict(plan_kind=L.PlanKind.RECT, setback_depth=p.plan_d / 2.0 + d, n_floors=24),
         dict(plan_kind=L.PlanKind.RECT, setback_depth=p.plan_d / 2.0 - 1.0, n_floors=24)),
        ("WWR unreachable", full, dict(wwr_target=(("N", 0.62), ("E", 0.4), ("S", 0.35), ("W", 0.4))),
         dict(wwr_target=(("N", 0.52), ("E", 0.4), ("S", 0.35), ("W", 0.4)))),
        ("fin_amp > 45", params_only, dict(fin_amp=45.0 + d), dict(fin_amp=45.0)),
        ("floor_h > transport height", params_only, dict(floor_h=L.MAX_PANEL_H + d), dict(floor_h=L.MAX_PANEL_H)),
        ("glass outside frame", params_only, dict(glass_recess=p.frame_d - p.glass_t),
         dict(glass_recess=p.frame_d - p.glass_t - d)),
    ]
    bad = []
    for name, entry, reject, accept in rows:
        r, a = _rejects(entry, **reject), not _rejects(entry, **accept)
        print(f"   guard {name:28s} past -> {'rejected' if r else 'ACCEPTED'}   inside -> {'accepted' if a else 'REJECTED'}")
        if not r:
            bad.append(f"C3 {name}: accepted past the boundary {reject}")
        if not a:
            bad.append(f"C3 {name}: rejected inside the boundary {accept}")
    return bad


def main() -> int:
    failures = []
    for kind in L.PlanKind:
        sched = L.build_schedule(L.default_params(plan_kind=kind))
        again = json.loads(sched.to_json())
        if again["stats"]["n_instances"] != sched.stats["n_instances"] or len(again["bands"]) != len(sched.bands):
            failures.append(f"C9 {kind.value}: JSON round-trip mismatch")
        errs = check_s1(sched)
        st = sched.stats
        print(f"-- {kind.value:8s} types {st['n_types']:3d} {st['types_by_family']}  std panels {len(st['standard_panel_types'])} fins {len(st['fin_types'])}"
              f"  floor types {st['n_floor_types']}  instances {st['n_instances']}  height {st['height']:.0f}")
        print("   WWR design " + "  ".join(f"{o} {v:.3f}/{dict(sched.params.wwr_target)[o]}" for o, v in st["design_wwr"].items())
              + f"   max fin err {st['max_fin_quant_error']:.3f} deg")
        failures += [f"[{kind.value}] {e}" for e in errs]
    failures += guard_matrix()
    return report("S1 layout", failures)


if __name__ == "__main__":
    sys.exit(main())

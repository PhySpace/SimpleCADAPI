"""S7 gate (V9): incremental rebuild — what a parameter edit costs, and that the SDK reports exactly that.

Every Part / band / tower build of each step is recorded (factories wrapped, not changed). Expectations are derived
from the schedules alone, independently of the SDK:
  part miss       its (builder, arguments) were never built before in this run (the cache keeps every variant)
  band dirty      component added / removed / retyped / moved vs that band's previous build
  band geo-dirty  component whose part arguments changed since that band's previous build
  tower dirty     component added / removed / re-referenced / moved vs the previous tower build
  tower geo-dirty component whose band / slab / canopy content changed since the previous tower build

Steps: prime (default) -> warm (default again: all hit, nothing dirty) -> fin_depth 300 -> 350 (misses == fin
types) -> revert (all parts hit) -> n_floors 36 -> 48, setback_every 16 (panel types all hit) -> revert.

    ../../../.venv/bin/python s7_verify.py
"""
from __future__ import annotations

import json
import sys
import time

from _common import PART_DIR, report

import corners as C
import floor as F
import layout as L
import panels as P
import slabs as S
import tower as T

LOG: dict = {}


def _record_part(mod, name):
    orig = getattr(mod, name)

    def wrapped(*args, **kwargs):
        r = orig(*args, **kwargs)
        pid = r.value.part_id
        LOG["parts"][pid] = LOG["parts"].get(pid, True) and bool(r.cache_report.hit)
        return r
    setattr(mod, name, wrapped)


def _record_band():
    orig = F.make_band_assembly

    def wrapped(sched, band_id):
        r = orig(sched, band_id)
        LOG["bands"][band_id] = r
        return r
    F.make_band_assembly = wrapped


for _mod, _name in ((P, "make_panel_part"), (C, "make_corner_part"), (S, "make_slab_part"), (S, "make_canopy_part")):
    _record_part(_mod, _name)
_record_band()


def _key(builder, kwargs) -> str:
    return json.dumps([builder.__name__, sorted((k, round(v, 9) if isinstance(v, float) else v)
                                                for k, v in kwargs.items())], default=str)


def part_keys(sched: L.FacadeSchedule) -> dict:
    """part id -> build key (builder + arguments) for every part the tower uses."""
    out = {}
    for tid, spec in sched.types.items():
        mod = C if spec["family"] == "corner" else P
        out[tid] = _key(*mod.builder_args(spec, sched.params))
    for k in range(len(sched.tiers)):
        out[S.slab_type_id(k)] = _key(S.build_slab, S.slab_args(sched, k))
    out[S.CANOPY_ID] = _key(S.build_canopy, S.canopy_args(sched))
    return out


def _frame_key(frame) -> tuple:
    return tuple(round(x, 6) for v in (frame["origin"], frame["x_axis"], frame["y_axis"]) for x in v)


def band_state(sched: L.FacadeSchedule, band_id: str) -> dict:
    return {c["component_id"]: (c["type_id"], _frame_key(c["frame"]))
            for c in F.band_components(sched, sched.band(band_id))}


def tower_state(sched: L.FacadeSchedule) -> dict:
    return {c["component_id"]: (_ref_id(c["ref"]), round(c["level"], 6))
            for c in T.tower_components(sched)}


def _ref_id(ref) -> str:
    kind, key = ref
    return F.band_assembly_id(key) if kind == "band" else S.slab_type_id(key) if kind == "slab" else S.CANOPY_ID


def _diff(before: dict | None, after: dict) -> set:
    if before is None:
        return set(after)
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


class Run:
    def __init__(self):
        self.seen: set = set()  # part build keys built so far
        self.band_prev: dict = {}  # band id -> (band_state, {part id: key})
        self.tower_prev = None  # (tower_state, {ref id: content key})
        self.rows: list = []

    def step(self, name: str, params: L.FacadeParams, expect_all_parts_hit: bool | None = None) -> list[str]:
        sched = L.build_schedule(params)
        keys = part_keys(sched)
        LOG.clear()
        LOG.update(parts={}, bands={})
        start = time.perf_counter()
        tower = T.make_tower(sched)
        seconds = time.perf_counter() - start
        bad = []
        # parts
        want_miss = {pid for pid, key in keys.items() if key not in self.seen}
        got_miss = {pid for pid, hit in LOG["parts"].items() if not hit}
        if got_miss != want_miss:
            bad.append(f"V9 {name}: part misses {sorted(got_miss)[:4]} (+{len(got_miss)}) != expected "
                       f"{sorted(want_miss)[:4]} (+{len(want_miss)})")
        if expect_all_parts_hit and got_miss:
            bad.append(f"V9 {name}: {len(got_miss)} part misses, expected all hit")
        # bands
        band_content = {}
        dirty_bands = 0
        for band_id, r in LOG["bands"].items():
            state = band_state(sched, band_id)
            used = {c.item.part_id for c in r.value.components}
            prev = self.band_prev.get(band_id)
            rep = r.solve_report
            changed = True
            if prev is not None:
                want_dirty = _diff(prev[0], state)
                want_geo = {cid for cid, (tid, _) in state.items()
                            if cid not in want_dirty and prev[1].get(tid) != keys[tid]}
                changed = bool(want_dirty or want_geo)
                if set(rep.dirty_instances) != want_dirty:
                    bad.append(f"V9 {name} {band_id}: dirty {sorted(rep.dirty_instances)[:3]} "
                               f"(+{len(rep.dirty_instances)}) != {sorted(want_dirty)[:3]} (+{len(want_dirty)})")
                got_geo = set(rep.geometry_dirty_instances) - want_dirty
                if got_geo != want_geo:
                    bad.append(f"V9 {name} {band_id}: geometry dirty {sorted(got_geo)[:3]} (+{len(got_geo)}) "
                               f"!= {sorted(want_geo)[:3]} (+{len(want_geo)})")
            if rep.corrupt_entries:
                bad.append(f"V9 {name} {band_id}: {rep.corrupt_entries} corrupt entries")
            dirty_bands += bool(rep.dirty_instances or rep.geometry_dirty_instances)
            band_content[F.band_assembly_id(band_id)] = changed
            self.band_prev[band_id] = (state, {tid: keys[tid] for tid in used})
        # tower
        tstate = tower_state(sched)
        content = {rid: keys[rid] for rid in keys if rid.startswith("slab-") or rid == S.CANOPY_ID}
        prev_t = self.tower_prev
        rep = tower.solve_report
        if prev_t is not None:
            want_dirty = _diff(prev_t[0], tstate)
            want_geo = {cid for cid, (rid, _) in tstate.items() if cid not in want_dirty and (
                band_content.get(rid, False) if rid.startswith("band-") else prev_t[1].get(rid) != content.get(rid))}
            if set(rep.dirty_instances) != want_dirty:
                bad.append(f"V9 {name} tower: dirty {sorted(rep.dirty_instances)[:4]} (+{len(rep.dirty_instances)}) "
                           f"!= {sorted(want_dirty)[:4]} (+{len(want_dirty)})")
            if set(rep.geometry_dirty_instances) - want_dirty != want_geo:
                bad.append(f"V9 {name} tower: geometry dirty {sorted(set(rep.geometry_dirty_instances) - want_dirty)[:4]} "
                           f"!= {sorted(want_geo)[:4]} (+{len(want_geo)})")
        self.tower_prev = (tstate, content)
        self.seen |= set(keys.values())
        row = {"step": name, "build_s": round(seconds, 1), "parts": len(LOG["parts"]), "part_misses": len(got_miss),
               "bands": len(LOG["bands"]), "bands_dirty": dirty_bands, "tower_dirty": len(rep.dirty_instances),
               "tower_geometry_dirty": len(rep.geometry_dirty_instances), "pieces": sched.stats["n_instances"]}
        self.rows.append(row)
        print(f"  {name:22s} {seconds:6.1f}s  parts {row['parts']:3d} ({row['part_misses']:2d} miss)  "
              f"bands {row['bands']:2d} ({dirty_bands:2d} changed)  tower dirty {row['tower_dirty']:2d} / "
              f"geo {row['tower_geometry_dirty']:2d}  {'ok' if not bad else f'{len(bad)} FAIL'}", flush=True)
        return bad


def main() -> int:
    base = L.default_params()
    run = Run()
    bad = run.step("prime (default)", base)
    bad = []  # the prime step only establishes the previous state (its "expected" misses are unknowable)
    bad += run.step("warm (default)", base, expect_all_parts_hit=True)
    # the content-addressed part store keeps every variant ever built, so a fixed edit would hit on a rerun of this
    # gate: salt the new depth (sub-micron) so its fin parts are cold every time
    depth = 350.0 + (time.time_ns() // 1000 % 997) * 1.0e-6
    bad += run.step(f"fin_depth {depth:.6f}", L.default_params(fin_depth=depth))
    fins = {t for t, s in L.build_schedule(base).types.items() if s["family"] == "fin"}
    if run.rows[-1]["part_misses"] != len(fins):
        bad.append(f"V9 fin_depth: {run.rows[-1]['part_misses']} part misses != {len(fins)} fin types")
    bad += run.step("revert fin_depth", base, expect_all_parts_hit=True)
    bad += run.step("n_floors 48 (every 16)", L.default_params(n_floors=48, setback_every=16), expect_all_parts_hit=True)
    bad += run.step("revert n_floors", base, expect_all_parts_hit=True)
    out = PART_DIR / "out"
    out.mkdir(exist_ok=True)
    (out / "incremental.json").write_text(json.dumps(run.rows, indent=1))
    print(f"  {out / 'incremental.json'}")
    return report("S7", bad)


if __name__ == "__main__":
    sys.exit(main())

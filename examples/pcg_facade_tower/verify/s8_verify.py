"""S8 gate (V10): the exported tower reopens, in a fresh process, as the same product.

Expected values come from the schedule and the per-definition part volumes of this process' build (not from the
package):
  P1 package   fresh process: read + materialize the .scadpkg; root id; distinct definitions = tower + bands + piece
               types + tier slabs + canopy; leaf occurrences per part id = schedule counts (facade pieces) / slab
               instances / 1 canopy; volume sum (part volume x multiplicity) within 1e-9 relative; the SDK world
               compound of the reopened tower has that many solids and z extent [0, height - joint/2]
  P2 STEP      report: AP242, definition ids = the package's, occurrence count = Σ components over the assembly
               definitions (each definition written once, occurrences are located references); fresh process: read
               the STEP back -> leaf solids = pieces + slabs + canopy, volume within 1e-6 relative
  P3 CSV       one row per piece type, counts = schedule, Σ count = pieces
Known-bad (run after the gate): a truncated package copy must be rejected by the fresh process (KB1); a CSV with one
count off by one must fail P3 (KB2).

    ../../../.venv/bin/python s8_verify.py
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from _common import PART_DIR, report

import export as E
import layout as L
import slabs as S
import tower as T

CHILD = r"""
import json, sys, time
import simplecadapi as scad
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

def volume(shape):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g); return g.Mass()

pkg_path, step_path = sys.argv[1], sys.argv[2]
out = {}
start = time.perf_counter()
package = scad.read_product_package(pkg_path)
root = scad.materialize_definition(package.root_definition)
out["read_s"] = time.perf_counter() - start
out["root_id"] = package.root_id
leaves, defs, part_volume = {}, set(), {}

def walk(item):  # every occurrence path to a part is one leaf
    if isinstance(item, scad.Assembly):
        defs.add(("assembly", item.assembly_id))
        for c in item.components:
            walk(c.item)
    else:
        defs.add(("part", item.part_id))
        leaves[item.part_id] = leaves.get(item.part_id, 0) + 1
        if item.part_id not in part_volume:
            part_volume[item.part_id] = item.body.get_volume()

walk(root)
out["definitions"] = sorted(f"{k}:{i}" for k, i in defs)
out["leaves"] = leaves
out["volume"] = sum(part_volume[p] * n for p, n in leaves.items())
whole = scad.make_compound_from_assembly_rcompound(assembly=root).wrapped
n = 0
ex = TopExp_Explorer(whole, TopAbs_SOLID)
while ex.More():
    n += 1; ex.Next()
box = Bnd_Box(); box.SetGap(0.0); BRepBndLib.AddOptimal_s(whole, box, useTriangulation=False)
out["world_solids"] = n
out["world_bbox"] = list(box.Get())
start = time.perf_counter()
reader = STEPControl_Reader()
if reader.ReadFile(step_path) != IFSelect_RetDone:
    raise SystemExit("STEP read failed")
reader.TransferRoots()
shape = reader.OneShape()
n, vol = 0, 0.0
ex = TopExp_Explorer(shape, TopAbs_SOLID)
while ex.More():
    n += 1; vol += volume(ex.Current()); ex.Next()
out["step_solids"], out["step_volume"], out["step_read_s"] = n, vol, time.perf_counter() - start
print("RESULT " + json.dumps(out))
"""


def fresh_process(package: Path, step: Path) -> tuple[int, dict | None, str]:
    proc = subprocess.run([sys.executable, "-c", CHILD, str(package), str(step)], capture_output=True, text=True,
                          cwd=PART_DIR)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")), None)
    return proc.returncode, (json.loads(line[7:]) if line else None), proc.stderr[-600:]


def expected(sched: L.FacadeSchedule, result) -> dict:
    comps = T.tower_components(sched)
    leaves = Counter(sched.stats["instances_by_type"])
    for c in comps:
        kind, key = c["ref"]
        if kind == "slab":
            leaves[S.slab_type_id(key)] += 1
        elif kind == "canopy":
            leaves[S.CANOPY_ID] += 1
    bands = {c.item.assembly_id: c.item for c in result.value.components if hasattr(c.item, "assembly_id")}
    parts = {c.item.part_id: c.item for b in bands.values() for c in b.components}
    parts |= {c.item.part_id: c.item for c in result.value.components if hasattr(c.item, "part_id")}
    defs = sorted([f"assembly:{T.TOWER_ID}"] + [f"assembly:{b}" for b in bands] + [f"part:{p}" for p in parts])
    return {"leaves": dict(leaves), "definitions": defs, "pieces": sum(leaves.values()),
            "volume": sum(parts[p].body.get_volume() * n for p, n in leaves.items()),
            "occurrences": len(result.value.components) + sum(len(b.components) for b in bands.values()),
            "height": sched.stats["height"] - sched.params.joint / 2.0}


def check_package(want: dict, got: dict | None, code: int, err: str) -> list[str]:
    if got is None:
        return [f"P1 fresh process failed (exit {code}): {err.strip().splitlines()[-1] if err.strip() else '?'}"]
    bad = []
    if got["root_id"] != T.TOWER_ID:
        bad.append(f"P1 root {got['root_id']} != {T.TOWER_ID}")
    if got["definitions"] != want["definitions"]:
        missing = sorted(set(want["definitions"]) - set(got["definitions"]))
        extra = sorted(set(got["definitions"]) - set(want["definitions"]))
        bad.append(f"P1 definitions: missing {missing[:4]} extra {extra[:4]}")
    if got["leaves"] != want["leaves"]:
        diff = sorted(k for k in set(got["leaves"]) | set(want["leaves"]) if got["leaves"].get(k) != want["leaves"].get(k))
        bad.append(f"P1 leaf occurrences differ for {diff[:4]} (+{len(diff)})")
    if abs(got["volume"] - want["volume"]) > 1e-9 * want["volume"]:
        bad.append(f"P1 volume {got['volume']:.6e} != {want['volume']:.6e}")
    if got["world_solids"] != want["pieces"]:
        bad.append(f"P1 world compound {got['world_solids']} solids != {want['pieces']}")
    z0, z1 = got["world_bbox"][2], got["world_bbox"][5]
    if abs(z0) > 1e-6 or abs(z1 - want["height"]) > 1e-6:
        bad.append(f"P1 world z [{z0:.4f}, {z1:.4f}] != [0, {want['height']:.4f}]")
    return bad


def check_step(want: dict, rep, got: dict | None) -> list[str]:
    bad = []
    if "AP242" not in rep.schema.upper():
        bad.append(f"P2 schema {rep.schema}")
    ids = sorted(d.split(":", 1)[1] for d in want["definitions"])
    if sorted(rep.definition_ids) != ids:
        bad.append(f"P2 {len(rep.definition_ids)} STEP definitions != {len(ids)}")
    if rep.occurrence_count != want["occurrences"]:
        bad.append(f"P2 {rep.occurrence_count} STEP occurrences != {want['occurrences']} (Σ assembly components)")
    if got is not None:
        if got["step_solids"] != want["pieces"]:
            bad.append(f"P2 STEP read back {got['step_solids']} solids != {want['pieces']}")
        if abs(got["step_volume"] - want["volume"]) > 1e-6 * want["volume"]:
            bad.append(f"P2 STEP volume {got['step_volume']:.6e} != {want['volume']:.6e}")
    return bad


def check_csv(sched: L.FacadeSchedule, path: Path) -> list[str]:
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    bad = []
    counts = sched.stats["instances_by_type"]
    got = {r["type_id"]: int(r["count"]) for r in rows}
    if len(rows) != len(sched.types) or set(got) != set(sched.types):
        bad.append(f"P3 CSV {len(rows)} rows / types != {len(sched.types)} schedule types")
    wrong = sorted(t for t in got if got[t] != counts.get(t))
    if wrong:
        bad.append(f"P3 CSV counts differ for {wrong[:4]}")
    if sum(got.values()) != sched.stats["n_instances"]:
        bad.append(f"P3 CSV Σ count {sum(got.values())} != {sched.stats['n_instances']} pieces")
    for r in rows:
        spec = sched.types.get(r["type_id"], {})
        if r["family"] != spec.get("family") or float(r["h_mm"]) != spec.get("h"):
            bad.append(f"P3 CSV row {r['type_id']}: family / h do not match the type table")
            break
    return bad


def known_bad(sched: L.FacadeSchedule, paths: dict) -> list[str]:
    from _common import OUT as RENDERS  # scratch space next to the renders, not in out/

    wrong = []
    RENDERS.mkdir(exist_ok=True)
    cut = RENDERS / "_kb_truncated.scadpkg"
    data = Path(paths["scadpkg"]).read_bytes()
    cut.write_bytes(data[: len(data) // 2])
    code, got, err = fresh_process(cut, Path(paths["step"]))
    fired = got is None and code != 0
    print(f"--- KB1 truncated package      => {'rejected' if fired else 'ACCEPTED'} "
          f"({'as designed' if fired else 'GATE BROKEN'})  {err.strip().splitlines()[-1][:110] if err.strip() else ''}")
    wrong += [] if fired else ["KB1"]
    cut.unlink()
    rows = E.panel_rows(sched)
    rows[3]["count"] += 1
    off = RENDERS / "_kb_panels.csv"
    with off.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=E.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    bad = check_csv(sched, off)
    print(f"--- KB2 CSV count off by one    => {'fail ' + bad[0] if bad else 'pass'} "
          f"({'as designed' if bad else 'GATE BROKEN'})")
    wrong += [] if bad else ["KB2"]
    off.unlink()
    return [f"{k}: gate did not discriminate" for k in wrong]


def main() -> int:
    sched = L.build_schedule(L.default_params())
    start = time.perf_counter()
    out = E.export(sched)
    total = time.perf_counter() - start
    paths = out["paths"]
    for name, path in paths.items():
        print(f"  {name:8s} {path}  ({Path(path).stat().st_size / 1e6:.2f} MB)")
    print("  export " + ", ".join(f"{k} {v:.1f}s" for k, v in out["timings"].items()) + f" (total {total:.1f}s)")
    want = expected(sched, out["result"])
    code, got, err = fresh_process(paths["scadpkg"], paths["step"])
    bad = check_package(want, got, code, err)
    bad += check_step(want, out["step_report"], got)
    bad += check_csv(sched, paths["csv"])
    if got:
        print(f"  fresh process: {len(got['definitions'])} definitions, {sum(got['leaves'].values())} leaves, "
              f"{got['world_solids']} world solids, read {got['read_s']:.1f}s; STEP {got['step_solids']} solids, "
              f"read {got['step_read_s']:.1f}s")
    print(f"  STEP {out['step_report'].schema}: {out['step_report'].occurrence_count} occurrences "
          f"(expanded {want['pieces']}), {len(out['step_report'].definition_ids)} definitions")
    status = report("S8", bad)
    return status or report("S8 known-bad", known_bad(sched, paths))


if __name__ == "__main__":
    sys.exit(main())

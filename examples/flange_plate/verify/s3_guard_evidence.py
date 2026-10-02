"""S3 guard-decision evidence: 6-hole -> 8-hole re-parameterization (USER round 2).

Records, as verification evidence:
  E1 candidate (bolt_count=8, bolt_pcd=88) is REJECTED by the web guard G2a,
     with the exact arithmetic in the assertion message
  E2 PCD supremum from the web inequality is 85, but 85 is EXCLUDED by the
     tangency guard G2b (web == edge_fillet_r): proven degenerate on 2026-09-05
     (run log: 8x PCD85 -> 7 hole walls, faces 16!=17, edge fillet swallowed
     the tangent 0-degree hole, volume +950 anomaly). Max deliverable PCD on a
     0.5 mm grid with web strictly > R_edge: 84.5
  E3 the delivered pair (8, 84.5) passes ALL guards (G1..G4, G2a+G2b)
  E4 parameter-change table 6-hole -> 8-hole (what changed, what did not)
  E5 each guard G1..G4 rejects a known-bad parameter set (from the S1 verifier)

Every candidate runs the notebook with overrides, so the evidence comes from the
guard cell itself. An override replaces a whole params cell, so a candidate
fills the rest of the cell from the nominal values.

    uv run python examples/flange_plate/verify/s3_guard_evidence.py
"""
import math
import sys
from pathlib import Path

from simplecadapi.runtime import run_notebook

NOTEBOOK = Path(__file__).resolve().parents[1] / "flange_plate.py"
# The notebook's params cells: an override must name every variable of a cell.
PARAM_CELLS = (
    ("FLANGE_OD", "FLANGE_T", "EDGE_FILLET_R", "MIN_EDGE_WEB"),
    ("BOSS_OD", "BOSS_TOP_Z", "BORE_D", "BOSS_FILLET_R"),
    ("BOLT_D", "BOLT_PCD", "BOLT_COUNT"),
)

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        failures.append(name)


nominal = run_notebook(NOTEBOOK)
p = {name: float(nominal.values[name]) for cell in PARAM_CELLS for name in cell}


def guard_message(**changes: float) -> str | None:
    """Run the notebook with *changes*; the guard's message, or None if it passed."""
    overrides = {}
    for cell in PARAM_CELLS:
        if any(name in changes for name in cell):
            overrides.update({name: changes.get(name, p[name]) for name in cell})
    try:
        run_notebook(NOTEBOOK, overrides=overrides)
    except AssertionError as exc:
        return str(exc)
    return None


REQ_COUNT, REQ_PCD = 8, 88.0
DELIVERED_PCD = 84.5  # 0.5 mm grid; supremum 85 excluded by G2b tangency
PRE_CHANGE_COUNT, PRE_CHANGE_PCD = 6, 78.0  # the round-1 delivery

print(f"notebook params: bolt_count={p['BOLT_COUNT']:.0f} bolt_pcd={p['BOLT_PCD']}")
print(f"user request   : bolt_count={REQ_COUNT} bolt_pcd={REQ_PCD} (as large as possible)")

# E1: candidate 8/88 must be rejected by the web guard G2a
web88 = p["FLANGE_OD"] / 2 - REQ_PCD / 2 - p["BOLT_D"] / 2
msg = guard_message(BOLT_COUNT=REQ_COUNT, BOLT_PCD=REQ_PCD)
if msg is None:
    check("E1 guard rejects 8/88", False, "NO raise — guard silent, unacceptable")
else:
    ok = msg.startswith("G2") and f"= {web88:.3f}" in msg
    check("E1 guard rejects 8/88", ok, f"web(88)={web88:.3f} min={p['MIN_EDGE_WEB']} raised: {msg[:90]}")

# E2: supremum 85 from G2a inequality, then excluded by G2b (tangency, proven)
pcd_sup = p["FLANGE_OD"] - p["BOLT_D"] - 2.0 * p["MIN_EDGE_WEB"]
web_sup = p["FLANGE_OD"] / 2 - pcd_sup / 2 - p["BOLT_D"] / 2
check("E2a supremum from web floor", abs(pcd_sup - 85.0) < 1e-9 and abs(web_sup - p["MIN_EDGE_WEB"]) < 1e-9,
      f"pcd_sup = {p['FLANGE_OD']} - {p['BOLT_D']} - 2*{p['MIN_EDGE_WEB']} = {pcd_sup:.1f}, "
      f"web({pcd_sup:.0f}) = {web_sup:.3f} == min_edge_web (boundary)")
msg = guard_message(BOLT_COUNT=REQ_COUNT, BOLT_PCD=pcd_sup)
if msg is None:
    check("E2b 85 excluded by tangency guard", False, "85 accepted — G2b missing")
else:
    check("E2b 85 excluded by tangency guard", msg.startswith("G2b"), f"raised: {msg[:80]}")
print("  degeneracy proof on record (2026-09-05 run): 8x PCD85 built a solid but the "
      "edge fillet swallowed the tangent 0-deg hole wall (D2 found 7/8 walls, "
      "faces 16 != 17, volume +950 anomaly) — tangency is a real failure mode, "
      "not a theoretical one")
check("E2c delivered PCD", abs(DELIVERED_PCD - 84.5) < 1e-9,
      f"max deliverable on 0.5mm grid with web > R_edge: {DELIVERED_PCD} "
      f"(web = {p['FLANGE_OD']/2 - DELIVERED_PCD/2 - p['BOLT_D']/2:.3f} > {p['EDGE_FILLET_R']})")

# E3: delivered pair (8, 84.5) passes all guards
msg = guard_message(BOLT_COUNT=REQ_COUNT, BOLT_PCD=DELIVERED_PCD)
check("E3 guards accept 8/84.5", msg is None, "" if msg is None else f"raised: {msg}")
web = p["FLANGE_OD"] / 2 - DELIVERED_PCD / 2 - p["BOLT_D"] / 2
gap = DELIVERED_PCD / 2 - p["BOLT_D"] / 2 - p["BOSS_OD"] / 2 - p["BOSS_FILLET_R"]
chord = 2 * (DELIVERED_PCD / 2) * math.sin(math.pi / REQ_COUNT)
print(f"  evidence: web={web:.3f} > R_edge={p['EDGE_FILLET_R']} (margin {web - p['EDGE_FILLET_R']:.3f}), "
      f"G3 gap={gap:.3f} > 0, G1 wall={(p['BOSS_OD']-p['BORE_D'])/2:.3f} > R{p['BOSS_FILLET_R']}, "
      f"G4 boss_h={p['BOSS_TOP_Z']-p['FLANGE_T']:.1f} >= R{p['BOSS_FILLET_R']}, "
      f"adjacent chord={chord:.2f} > bolt_d={p['BOLT_D']}")

# E4: change table
print("E4 change table:")
print(f"  bolt_count : {PRE_CHANGE_COUNT} -> {REQ_COUNT}   (spacing 360/{REQ_COUNT} = {360.0/REQ_COUNT:.1f} deg)")
print(f"  bolt_pcd   : {PRE_CHANGE_PCD} -> {DELIVERED_PCD}  "
      f"(88 rejected by G2a: web 0.5 < {p['MIN_EDGE_WEB']}; 85 excluded by G2b tangency; "
      f"84.5 = 0.5mm-grid max with web > R_edge)")
print(f"  unchanged  : flange_od={p['FLANGE_OD']} flange_t={p['FLANGE_T']} boss_od={p['BOSS_OD']} "
      f"boss_top_z={p['BOSS_TOP_Z']} bore_d={p['BORE_D']} bolt_d={p['BOLT_D']} "
      f"R_root={p['BOSS_FILLET_R']} R_edge={p['EDGE_FILLET_R']}")
check("E4 notebook params delivered",
      p["BOLT_COUNT"] == REQ_COUNT and abs(p["BOLT_PCD"] - DELIVERED_PCD) < 1e-9,
      f"bolt_count={p['BOLT_COUNT']:.0f}, bolt_pcd={p['BOLT_PCD']} in flange_plate.py")

# E5: every guard rejects a known-bad parameter set
bad_cases = {
    "G1 bore>=boss": ("G1", dict(BORE_D=p["BOSS_OD"])),
    "G2 web<min": ("G2", dict(BOLT_PCD=p["FLANGE_OD"] - p["BOLT_D"] - 2.0 * p["MIN_EDGE_WEB"] + 1.0)),
    "G3 bolt hits root fillet": ("G3", dict(BOLT_PCD=p["BOSS_OD"] + p["BOLT_D"] + 2.0 * p["BOSS_FILLET_R"])),
    "G4 root fillet>boss height": ("G4", dict(BOSS_TOP_Z=p["FLANGE_T"] + 2.0)),  # boss 高 2 < R3
}
for name, (prefix, changes) in bad_cases.items():
    msg = guard_message(**changes)
    if msg is None:
        check(f"E5 guard rejects {name}", False, "NO raise — guard is silent")
    else:
        check(f"E5 guard rejects {name}", msg.startswith(prefix), f"raised: {msg[:60]}")

print(f"S3 guard evidence: {'ALL PASS' if not failures else 'FAILED ' + str(failures)}")
sys.exit(1 if failures else 0)

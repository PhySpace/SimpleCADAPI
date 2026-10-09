"""S7 report (V9): what a parameter edit costs — full rebuild timings per edit step.

The part cache this gate used to verify was removed from the SDK (dev now rebuilds through the
notebook runtime), so there are no hit / dirty reports to assert anymore. What survives is the
question the gate always answered, now measured honestly as full rebuilds: how long each edit
step takes, and how the piece count moves. Every build is a complete, deterministic rebuild of
the same design policy.

Steps: prime (default) -> warm (default again) -> fin_depth 300 -> 350 -> revert ->
n_floors 36 -> 48, setback_every 16 -> revert. Artifacts: out/incremental.json (per step:
build seconds, pieces, types).

    ../../../.venv/bin/python s7_verify.py
"""
from __future__ import annotations

import json
import sys
import time

from _common import PART_DIR, report

import layout as L
import tower as T


class Run:
    def __init__(self):
        self.rows: list = []

    def step(self, name: str, params: L.FacadeParams) -> list[str]:
        start = time.perf_counter()
        sched = L.build_schedule(params)
        tower = T.make_tower(sched)
        seconds = time.perf_counter() - start
        st = sched.stats
        row = {
            "step": name,
            "build_s": round(seconds, 1),
            "pieces": st["n_instances"],
            "types": st["n_types"],
            "fin_types": len(st["fin_types"]),
            "height_m": round(st["height"] / 1000.0, 2),
        }
        self.rows.append(row)
        print(f"  {name:22s} {seconds:6.1f}s  pieces {row['pieces']:5d}  types {row['types']:3d}  "
              f"fins {row['fin_types']:3d}  {row['height_m']:6.2f} m", flush=True)
        return []


def main() -> int:
    base = L.default_params()
    run = Run()
    bad = []
    bad += run.step("prime (default)", base)
    bad += run.step("warm (default)", base)
    bad += run.step("fin_depth 350", L.default_params(fin_depth=350.0))
    bad += run.step("revert fin_depth", base)
    bad += run.step("n_floors 48 (every 16)", L.default_params(n_floors=48, setback_every=16))
    bad += run.step("revert n_floors", base)
    out = PART_DIR / "out"
    out.mkdir(exist_ok=True)
    (out / "incremental.json").write_text(json.dumps(run.rows, indent=1))
    print(f"  {out / 'incremental.json'}")
    return report("S7 rebuild timings", bad)


if __name__ == "__main__":
    sys.exit(main())

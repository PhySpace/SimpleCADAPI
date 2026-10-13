"""S6 gate: rationalization / scale / plan sweeps — the same rules at any size.

  R1 rationalization  K in {2, 3, 4, 6, 8, 12, 24} (fin bins): fin types <= K, total types non-decreasing in K,
                      max quantization error <= 90 / (2 (K - 1)) (half a bin), design WWR independent of K
  R2 scale            n_floors in {8, 20, 36, 48}, setback_every = ceil(n / 3) (3 tiers): the standard panel type
                      set is the same at every size; each tower is built and passes the S5 gate
  R3 plan             RECT / CHAMFER (36 floors): each tower is built and passes the S5 gate (V1, V4, ...);
                      L_SHAPE is layout-verified only — see the README "Known limitations"

Artifacts: out/rationalization.png (types and error vs K), out/scale_sweep.json (per size / plan: types, pieces,
definitions, build seconds, S5 result).

    ../../../.venv/bin/python s6_verify.py [--no-geometry]
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

from _common import PART_DIR, report
from s3_verify import TOL

import layout as L

OUT = PART_DIR / "out"
KS = (2, 3, 4, 6, 8, 12, 24)
SIZES = (8, 20, 36, 48)


def rationalization() -> tuple[list[str], list[dict]]:
    bad, rows = [], []
    base_wwr = None
    for k in KS:
        s = L.build_schedule(L.default_params(fin_bins=k))
        st = s.stats
        bound = 90.0 / (2.0 * (k - 1))
        row = {"K": k, "types": st["n_types"], "fin_types": len(st["fin_types"]), "instances": st["n_instances"],
               "max_error": st["max_fin_quant_error"], "bound": bound, "wwr": st["design_wwr"]}
        rows.append(row)
        if row["fin_types"] > k:
            bad.append(f"R1 K={k}: {row['fin_types']} fin types > K")
        if row["max_error"] > bound + TOL:
            bad.append(f"R1 K={k}: max quantization error {row['max_error']:.4f} > half bin {bound:.4f}")
        base_wwr = base_wwr or st["design_wwr"]
        if any(abs(st["design_wwr"][o] - base_wwr[o]) > TOL for o in base_wwr):
            bad.append(f"R1 K={k}: design WWR {st['design_wwr']} depends on K")
    for a, b in zip(rows, rows[1:]):
        if b["types"] < a["types"]:
            bad.append(f"R1 types fall from {a['types']} (K={a['K']}) to {b['types']} (K={b['K']})")
    return bad, rows


def rationalization_figure(rows: list[dict], path: Path) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ks = [r["K"] for r in rows]
    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(10.5, 3.8))
    ink, muted = "#222222", "#8a8a8a"
    ax0.plot(ks, [r["fin_types"] for r in rows], color=ink, lw=2, marker="o", ms=5)
    for r in rows:
        ax0.annotate(str(r["fin_types"]), (r["K"], r["fin_types"]), textcoords="offset points", xytext=(0, 7),
                     ha="center", fontsize=8, color=ink)
    ax0.set_title("fin part types vs K (panels, corners, slabs unchanged)", fontsize=10)
    ax0.set_ylabel("fin part types")
    ax1.plot(ks, [r["max_error"] for r in rows], color=ink, lw=2, marker="o", ms=5)
    ax1.plot(ks, [r["bound"] for r in rows], color=muted, lw=1, ls="--")
    ax1.annotate("half bin 90/(2(K-1))", (ks[1], rows[1]["bound"]), textcoords="offset points", xytext=(8, 4),
                 fontsize=8, color=muted)
    ax1.set_title("max fin angle quantization error vs K", fontsize=10)
    ax1.set_ylabel("degrees")
    for ax in (ax0, ax1):
        ax.set_xscale("log", base=2)
        ax.set_xticks(ks, [str(k) for k in ks])
        ax.set_xlabel("fin bins K")
        ax.grid(True, color="#e6e6e6", lw=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return str(path)


def scale_schedules() -> tuple[list[str], dict]:
    bad, out = [], {}
    std = None
    for n in SIZES:
        s = L.build_schedule(L.default_params(n_floors=n, setback_every=math.ceil(n / 3)))
        out[n] = s
        if std is None:
            std = s.stats["standard_panel_types"]
        if s.stats["standard_panel_types"] != std:
            bad.append(f"R2 {n} floors: standard types {s.stats['standard_panel_types']} != {std}")
        if s.stats["n_tiers"] != 3:
            bad.append(f"R2 {n} floors: {s.stats['n_tiers']} tiers != 3")
    return bad, out


def build_and_check(tag: str, sched: L.FacadeSchedule) -> tuple[list[str], dict]:
    from s5_verify import check_tower
    from tower import make_tower

    start = time.perf_counter()
    r = make_tower(sched)
    built = time.perf_counter() - start
    bad, info = check_tower(sched, r.value, r.definition)
    st = sched.stats
    row = {"plan": sched.params.plan_kind.value, "n_floors": sched.params.n_floors,
           "setback_every": sched.params.setback_every, "height_m": st["height"] / 1000.0, "types": st["n_types"],
           "standard_types": st["standard_panel_types"], "floor_types": st["n_floor_types"],
           "pieces": info["pieces"], "tower_components": info["components"],
           "definitions": len(r.definition.definition_refs), "build_s": round(built, 1),
           "wwr": {o: round(v, 4) for o, v in info["wwr"].items()}, "s5_failures": len(bad)}
    print(f"  {tag:18s} {row['height_m']:6.1f} m  {row['types']:3d} types  {row['pieces']:5d} pieces  "
          f"{row['definitions']:3d} defs  build {built:5.1f}s  S5 {'ok' if not bad else f'{len(bad)} FAIL'}", flush=True)
    return [f"{tag}: {b}" for b in bad], row


def main(geometry: bool) -> int:
    OUT.mkdir(exist_ok=True)
    failures, sweep = [], {"rationalization": [], "scale": [], "plan": []}
    bad, rows = rationalization()
    failures += bad
    sweep["rationalization"] = rows
    print("  K     " + " ".join(f"{r['K']:6d}" for r in rows))
    print("  types " + " ".join(f"{r['types']:6d}" for r in rows))
    print("  fins  " + " ".join(f"{r['fin_types']:6d}" for r in rows))
    print("  err   " + " ".join(f"{r['max_error']:6.2f}" for r in rows))
    print("  " + rationalization_figure(rows, OUT / "rationalization.png"))
    bad, scheds = scale_schedules()
    failures += bad
    for n, s in scheds.items():
        print(f"  {n:2d} floors: {s.stats['n_types']} types, {s.stats['n_instances']} pieces, "
              f"{s.stats['n_floor_types']} floor types, std {s.stats['standard_panel_types']}")
    if geometry:
        for n, s in scheds.items():
            bad, row = build_and_check(f"chamfer {n}F", s)
            failures += bad
            sweep["scale"].append(row)
        # L_SHAPE is layout-verified only (see the example README "Known limitations"):
        # its reflex-corner profile extends past frame_d and fails S5 V5 at tower fit.
        bad, row = build_and_check(f"{L.PlanKind.RECT.value} 36F", L.build_schedule(L.default_params(plan_kind=L.PlanKind.RECT)))
        failures += bad
        sweep["plan"].append(row)
        sweep["plan"].append(next(r for r in sweep["scale"] if r["n_floors"] == 36))
    path = OUT / "scale_sweep.json"
    path.write_text(json.dumps(sweep, indent=1, default=str))
    print(f"  {path}")
    return report("S6", failures)


if __name__ == "__main__":
    sys.exit(main(geometry="--no-geometry" not in sys.argv))

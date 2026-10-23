"""pcg_facade_tower export: product package, AP242 STEP (shared definitions), panel schedule CSV, hero render.

    ../../.venv/bin/python export.py [rect|chamfer|l_shape] [n_floors]

out/<stem>.scadpkg   the tower closure (tower -> bands -> panel / fin / corner types; slabs, canopy)
out/<stem>.step      XCAF assembly: every definition written once, every occurrence a located reference
out/<stem>_panels.csv one row per facade piece type (type_id, family, sizes, count) — the fabrication list
out/<stem>.png       iso from the south-west
"""
from __future__ import annotations

import csv
import math
import sys
import time
from pathlib import Path

import simplecadapi as scad

import layout as L
import tower as T

OUT = Path(__file__).resolve().parent / "out"
CSV_FIELDS = ("type_id", "family", "w_mm", "h_mm", "spandrel_mm", "fin_angle_deg", "corner_turn_deg", "count")


def panel_rows(sched: L.FacadeSchedule) -> list[dict]:
    counts = sched.stats["instances_by_type"]
    rows = []
    for tid in sorted(sched.types):
        spec = sched.types[tid]
        rows.append({"type_id": tid, "family": spec["family"], "w_mm": spec.get("w", ""), "h_mm": spec["h"],
                     "spandrel_mm": spec.get("spandrel", ""), "fin_angle_deg": spec.get("angle", ""),
                     "corner_turn_deg": spec.get("turn", ""), "count": counts[tid]})
    return rows


def write_csv(sched: L.FacadeSchedule, path: Path) -> Path:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(panel_rows(sched))
    return path


def export(sched: L.FacadeSchedule, stem: str = "facade_tower", render: bool = True) -> dict:
    OUT.mkdir(exist_ok=True)
    timings = {}
    start = time.perf_counter()
    result = T.make_tower(sched)
    timings["build"] = time.perf_counter() - start
    package = OUT / f"{stem}.scadpkg"
    start = time.perf_counter()
    scad.capture(result, package, include_scene=False)  # the scene projection of 3700 pieces is not needed here
    timings["capture"] = time.perf_counter() - start
    start = time.perf_counter()
    step = scad.exporter.export_product_package_to_step(package, OUT / f"{stem}.step")
    timings["step"] = time.perf_counter() - start
    paths = {"scadpkg": package, "step": step.output_path, "csv": write_csv(sched, OUT / f"{stem}_panels.csv")}
    if render:
        start = time.perf_counter()
        whole = scad.make_compound_from_assembly_rcompound(assembly=result.value)
        paths["png"] = Path(scad.render_screenshot_rpath(
            shapes=list(whole.solids()), output_path=str(OUT / f"{stem}.png"), view=(20.0, 225.0), view_up=(0.0, 0.0, 1.0),
            show_callouts=False, show_legend=False))
        timings["render"] = time.perf_counter() - start
    return {"result": result, "step_report": step, "paths": paths, "timings": timings}


if __name__ == "__main__":
    kind = L.PlanKind(sys.argv[1]) if len(sys.argv) > 1 else L.PlanKind.CHAMFER
    n = int(sys.argv[2]) if len(sys.argv) > 2 else None
    params = (L.default_params(plan_kind=kind) if n is None else
              L.default_params(plan_kind=kind, n_floors=n, setback_every=math.ceil(n / 3)))
    s = L.build_schedule(params)
    out = export(s, stem="facade_tower" if n is None and kind is L.PlanKind.CHAMFER else f"facade_tower_{kind.value}_{s.params.n_floors}f")
    for name, path in out["paths"].items():
        print(f"{name:8s} {path}  ({Path(path).stat().st_size / 1e6:.1f} MB)")
    print(f"{out['step_report'].occurrence_count} STEP occurrences, {len(out['step_report'].definition_ids)} definitions; "
          + ", ".join(f"{k} {v:.1f}s" for k, v in out["timings"].items()))

"""The C++ port against the Python SDK it replaces: median microseconds per call.

    .venv/bin/python tools/bench/bench_native.py [--build build/<dir>] [--reference] [--json]

`--build` is a build tree holding the `python/` package (default: build/ops_geometry, or
$SCAD_BUILD_DIR).  The cases mirror tools/bench/bench_reference.py; a case whose operators
the module does not export yet is skipped.  With `--reference` the reference interpreter
(SCAD_REF_PYTHON) runs bench_reference.py too and the table shows the speed-up.

"bare OCCT" is the module's own raw primitive (`_testing.box`), the floor the operators can
approach: everything above it is the semantic layer (tags, roles, track summary, recording hook).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF_PYTHON = os.environ.get("SCAD_REF_PYTHON", "/Users/lildino/Project/ocws/SimpleCADAPI/.venv/bin/python")


def median_us(fn, repeat: int = 200, warmup: int = 20) -> float:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1e6)
    return statistics.median(samples)


def cases(scad):
    raw = scad._testing
    table = {
        "box": (lambda: raw.box(10, 20, 30), lambda: scad.make_box_rsolid(10, 20, 30)),
        "cylinder": (lambda: raw.cylinder(5.0, 10.0), lambda: scad.make_cylinder_rsolid(5.0, 10.0)),
    }
    if hasattr(scad, "fillet_rsolid") and hasattr(scad, "ql"):
        table["box_fillet_all_edges"] = (
            lambda: raw.box(10, 20, 30),
            lambda: scad.fillet_rsolid(scad.make_box_rsolid(10, 20, 30), scad.ql.edges(), 1.0),
        )
    if hasattr(scad, "cut_rsolid"):
        table["box_cut_cylinder"] = (
            lambda: (raw.box(10, 20, 30), raw.cylinder(4.0, 40.0)),
            lambda: scad.cut_rsolid(scad.make_box_rsolid(10, 20, 30), scad.make_cylinder_rsolid(4.0, 40.0)),
        )
    if hasattr(scad, "extrude_rsolid") and hasattr(scad, "make_rectangle_rface"):
        table["extrude"] = (
            lambda: raw.box(2.0, 1.0, 3.0),
            lambda: scad.extrude_rsolid(scad.make_rectangle_rface(2.0, 1.0), (0, 0, 1), 3.0),
        )
    if hasattr(scad, "loft_rsolid") and hasattr(scad, "make_rectangle_rwire"):
        table["loft"] = (
            lambda: raw.box(4.0, 4.0, 3.0),
            lambda: scad.loft_rsolid([scad.make_rectangle_rwire(4.0, 4.0), scad.make_rectangle_rwire(2.0, 2.0, center=(0, 0, 3))]),
        )
    if hasattr(scad, "std"):
        # The standard parts chain dozens of operators: no single bare-OCCT floor (raw is None).
        table["std_spur_gear"] = (None, lambda: scad.std.gear.make_spur_gear_rsolid(12, 2.0, gear_height=4.0))
        if hasattr(scad, "Assembly"):
            table["std_ball_bearing"] = (None, lambda: scad.std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5, 7, 0.05))
        table["std_bolt_cosmetic"] = (None, lambda: scad.std.fastener.make_bolt_rsolid(8.0, 24.0, thread_detail="cosmetic"))
        table["std_bolt_modeled"] = (None, lambda: scad.std.fastener.make_bolt_rsolid(8.0, 24.0), 3)
    return table


def reference_us() -> dict:
    script = ROOT / "tools" / "bench" / "bench_reference.py"
    out = subprocess.run([REF_PYTHON, str(script), "--json"], capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default=os.environ.get("SCAD_BUILD_DIR", str(ROOT / "build" / "ops_geometry")))
    ap.add_argument("--reference", action="store_true", help="also run bench_reference.py and show the speed-up")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repeat", type=int, default=200)
    args = ap.parse_args()

    sys.path.insert(0, str(Path(args.build) / "python"))
    import simplecadapi._cpp as scad

    reference = reference_us() if args.reference else {}
    result = {}
    header = f"{'case':<26}{'bare OCCT us':>14}{'native us':>12}{'native/bare':>13}"
    print(header + (f"{'reference us':>14}{'speed-up':>10}" if reference else ""))
    for name, (raw, native, *repeat) in cases(scad).items():
        count = min(args.repeat, repeat[0]) if repeat else args.repeat
        bare = median_us(raw, count) if raw else 0.0
        ours = median_us(native, count, warmup=1 if repeat else 20)
        result[name] = {"raw_us": bare, "native_us": ours}
        ratio = f"{ours / bare:.1f}x" if bare else "-"
        line = f"{name:<26}{bare:>14.1f}{ours:>12.1f}{ratio:>13}"
        if name in reference:
            result[name]["reference_us"] = reference[name]["sdk_us"]
            line += f"{reference[name]['sdk_us']:>14.1f}{reference[name]['sdk_us'] / ours:>9.1f}x"
        print(line)
    if args.json:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

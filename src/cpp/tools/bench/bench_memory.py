"""Process memory of the Python SDK vs the C++ port for the same models.

One case per fresh process (RSS is per process), N objects kept alive:

    <py> tools/bench/bench_memory.py reference box 2000
    <py> tools/bench/bench_memory.py native    box 2000 --build build/ops_features-rel

Prints one JSON line: RSS after import, RSS after building, KB per object.
Case names: box, box_faces (also touches every face and edge), fillet, gear.
RSS is read from `ps`, so it counts everything the process holds (OCCT shapes included,
which are identical in both implementations: the difference is the wrapper layer).
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import time


def rss_kb() -> int:
    return int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())]).split()[0])


def load(impl: str, build: str | None):
    if impl == "native":
        sys.path.insert(0, os.path.join(build or "build/mac", "python"))
        import simplecadapi._cpp as scad
        from simplecadapi._cpp import ql
    else:
        import simplecadapi as scad
        import simplecadapi.ql as ql
    return scad, ql


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("impl", choices=["reference", "native"])
    ap.add_argument("case", choices=["box", "box_faces", "fillet", "gear"])
    ap.add_argument("n", type=int)
    ap.add_argument("--build", default=None)
    a = ap.parse_args()

    scad, ql = load(a.impl, a.build)
    gc.collect()
    after_import = rss_kb()

    def make():
        if a.case in ("box", "box_faces"):
            s = scad.make_box_rsolid(10, 20, 30)
            if a.case == "box_faces":
                for f in s._iter_faces():
                    f.get_area()
                    f._list_tags()
                s._iter_edges()
            return s
        if a.case == "fillet":
            return scad.fillet_rsolid(scad.make_box_rsolid(10, 20, 30), ql.edges(), 1.0)
        return scad.std.gear.make_spur_gear_rsolid(20, 2.0, gear_height=6.0)

    make()  # warm up allocators/caches so the first object is not charged with them
    gc.collect()
    base = rss_kb()
    keep = []
    t0 = time.perf_counter()
    for _ in range(a.n):
        keep.append(make())
    seconds = time.perf_counter() - t0
    gc.collect()
    end = rss_kb()
    print(json.dumps({
        "impl": a.impl, "case": a.case, "n": a.n,
        "after_import_mb": round(after_import / 1024, 1),
        "after_build_mb": round(end / 1024, 1),
        "kb_per_object": round((end - base) / a.n, 1),
        "seconds": round(seconds, 2),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Benchmark the 6-DOF arm (sandbox-envs/desktop_arm_sources/arm6.py) on two SDK builds: time and RAM.

The driver is independent of the SDK: every measured run is a fresh subprocess of the interpreter that belongs to one
variant (``--variant name=/path/to/python``), started in its own copy of the case (so each variant has its own cache and
the sources are identical).  The driver samples the whole process tree (the run plus the workers it starts) every
20 ms and reports

* wall seconds,
* CPU seconds (user+system, the run and its workers: robust to a loaded machine),
* peak RSS of the tree in MB (sum over processes: shared pages count once per process) and of the largest single process,
* cells that ran / were restored from the cache, and the summed volume of the arm's solids (a cross-check that every
  variant computed the same model),
* the size of the cache directory afterwards.

Conditions: an edit sequence on a persistent cache (cold, warm, edit one joint, edit a length that rebuilds a link,
edit the base, edit the gripper), the cold build with different worker counts (``SCA_JOBS``), and the bare interpreter
(import time and idle RSS).

    python tools/bench_arm6.py --variant native=/path/to/native/.venv/bin/python \\
        --variant original=/path/to/original/.venv/bin/python [--repeat 1] [--out results.json]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

CASE = Path(__file__).resolve().parent.parent / "sandbox-envs" / "desktop_arm_sources"

# Runs in the measured interpreter: the notebook runtime on one notebook, then a summary line.
CHILD = r"""
import json, sys, time
t0 = time.perf_counter()
import simplecadapi as scad
t_import = time.perf_counter() - t0
from simplecadapi.runtime import run_notebook
t1 = time.perf_counter()
run = run_notebook(sys.argv[1])
t_run = time.perf_counter() - t1
ran = sum(1 for c in run.cells if c.status == "ran" and c.name != "setup")
cached = sum(1 for c in run.cells if c.status == "cached")
errors = [c.name for c in run.cells if getattr(c, "status", "") == "error"]

def volume(value):
    kind = type(value).__name__
    if kind == "Part":
        return value.body.get_volume()
    if kind == "Assembly":
        return sum(volume(component.item) for component in value.components)
    return 0.0

try:
    total = float(volume(run.product))
except Exception as error:  # noqa: BLE001
    total = None
print("RESULT " + json.dumps({"import_s": t_import, "run_s": t_run, "ran": ran, "cached": cached,
                              "errors": errors, "volume": total}))
"""

def tree_sample(root: psutil.Process, stop: threading.Event, box: dict) -> None:
    peak_tree = peak_one = 0
    cpu = {}
    while not stop.is_set():
        try:
            procs = [root] + root.children(recursive=True)
        except psutil.Error:
            break
        total = 0
        for proc in procs:
            try:
                rss = proc.memory_info().rss
                times = proc.cpu_times()
            except psutil.Error:
                continue
            total += rss
            peak_one = max(peak_one, rss)
            cpu[proc.pid] = times.user + times.system + times.children_user + times.children_system
        peak_tree = max(peak_tree, total)
        box["peak_tree"], box["peak_one"] = peak_tree, peak_one
        box["cpu"] = sum(cpu.values())
        time.sleep(0.02)


def measure(python: str, args: list[str], cwd: Path, env: dict[str, str]) -> dict:
    start = time.perf_counter()
    proc = subprocess.Popen([python, *args], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stop, box = threading.Event(), {"peak_tree": 0, "peak_one": 0, "cpu": 0.0}
    sampler = threading.Thread(target=tree_sample, args=(psutil.Process(proc.pid), stop, box), daemon=True)
    sampler.start()
    out, err = proc.communicate()
    wall = time.perf_counter() - start
    stop.set()
    sampler.join()
    result = {"wall_s": wall, "cpu_s": box["cpu"], "peak_tree_mb": box["peak_tree"] / 2**20,
              "peak_proc_mb": box["peak_one"] / 2**20, "rc": proc.returncode}
    for line in out.splitlines():
        if line.startswith("RESULT "):
            result.update(json.loads(line[7:]))
    if proc.returncode != 0:
        result["stderr"] = err[-600:]
    return result


def directory_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 2**20 if path.exists() else 0.0


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def fresh_case(root: Path) -> Path:
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(CASE, root, ignore=shutil.ignore_patterns("__marimo__", "__pycache__", "out"))
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", action="append", required=True, metavar="NAME=PYTHON")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--jobs", default="1,4", help="worker counts for the cold-build condition")
    parser.add_argument("--out", type=Path, default=Path("arm6_bench.json"))
    parser.add_argument("--only", default="", help="comma list of conditions: bare,sequence,jobs")
    args = parser.parse_args()
    variants = dict(item.split("=", 1) for item in args.variant)
    only = set(filter(None, args.only.split(",")))
    results: list[dict] = []
    work = Path(tempfile.mkdtemp(prefix="arm6bench_"))
    base_env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}

    def record(variant: str, condition: str, step: str, data: dict, extra: dict | None = None) -> None:
        row = {"variant": variant, "condition": condition, "step": step, **data, **(extra or {})}
        results.append(row)
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(f"{variant:9} {condition:9} {step:34} wall {data['wall_s']:7.1f}s cpu {data['cpu_s']:7.1f}s "
              f"tree {data['peak_tree_mb']:7.0f}MB main {data['peak_proc_mb']:6.0f}MB "
              f"ran/cached {data.get('ran', '?')}/{data.get('cached', '?')}"
              + (f" rc={data['rc']} {data.get('stderr', '')[-200:]}" if data["rc"] else ""), flush=True)

    # -- the bare interpreter -----------------------------------------------------------------------------------------
    if not only or "bare" in only:
        for name, python in variants.items():
            for _ in range(max(3, args.repeat)):
                data = measure(python, ["-c", "import json, simplecadapi; print('RESULT ' + json.dumps({}))"], work, base_env)
                record(name, "bare", "import simplecadapi", data)

    # -- the edit sequence on a persistent cache ------------------------------------------------------------------------
    if not only or "sequence" in only:
        for name, python in variants.items():
            for repeat in range(args.repeat):
                root = fresh_case(work / f"{name}_seq{repeat}" / "arm")
                top = root / "arm6.py"
                env = {**base_env, "SCA_JOBS": os.environ.get("SCA_JOBS", "4")}
                steps = [
                    ("cold", None),
                    ("warm (nothing changed)", None),
                    ("edit J1 0->15 (solve only)", (top, 'J1=scad.var("j1", 0.0,unit="deg")', 'J1=scad.var("j1", 15.0,unit="deg")')),
                    ("edit UPPER_LENGTH 90->95", (top, 'upper_length", 90.0', 'upper_length", 95.0')),
                    ("edit yaw_base BASE_D", (root / "yaw_base.py", "default=90.0", "default=92.0")),
                    ("edit OPEN_STROKE (gripper)", (top, 'open_stroke", 3.0', 'open_stroke", 4.0')),
                ]
                for label, change in steps:
                    if change:
                        edit(*change)
                    data = measure(python, ["-c", CHILD, str(top)], root, env)
                    record(name, "sequence", label, data, {"repeat": repeat, "cache_mb": directory_mb(root / "__marimo__")})

    # -- the cold build with different worker counts --------------------------------------------------------------------
    if not only or "jobs" in only:
        for jobs in args.jobs.split(","):
            for name, python in variants.items():
                root = fresh_case(work / f"{name}_jobs{jobs}" / "arm")
                data = measure(python, ["-c", CHILD, str(root / "arm6.py")], root, {**base_env, "SCA_JOBS": jobs})
                record(name, "jobs", f"cold, SCA_JOBS={jobs}", data, {"cache_mb": directory_mb(root / "__marimo__")})

    shutil.rmtree(work, ignore_errors=True)
    print("\nresults:", args.out.resolve())


if __name__ == "__main__":
    main()

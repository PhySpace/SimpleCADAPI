#!/usr/bin/env python3
"""Print the landing plan: which files go into which pull request of the stack (see docs/LANDING_PLAN.md).

    python3 src/cpp/tools/landing_plan.py                 # summary table (files, lines), rule check
    python3 src/cpp/tools/landing_plan.py --files         # every file of every PR
    python3 src/cpp/tools/landing_plan.py --pr 6          # the files of one PR
    python3 src/cpp/tools/landing_plan.py --rev WORKTREE  # the working tree (tracked + untracked, not ignored)

By default the tree of HEAD is read (`git ls-tree -r --name-only HEAD`).  The universe is every file below src/cpp plus the
Python files that exist only to drive the compiled module (src/simplecadapi/_cpp, src/simplecadapi/_glue, pyproject.toml,
.github/workflows).  Each file is assigned by the longest matching prefix in PRS below; the script exits 1 if a file
matches no prefix (left over) or if a prefix matches nothing (a stale rule).  Every file then belongs to exactly one PR
by construction.  Nothing here creates branches or builds anything.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

C = "src/cpp/"

# (title, [path prefixes]).  A prefix matches a file when the file path starts with it; the longest prefix wins.
PRS: list[tuple[str, list[str]]] = [
    ("build, CI, format, docs", [
        C + "CMakeLists.txt", C + "src/CMakeLists.txt", C + "cmake/ScadCompile.cmake", C + "cmake/ScadOcct.cmake",
        C + "tests/cpp/CMakeLists.txt", C + "tests/cpp/test_main.cpp", C + "third_party/doctest/",
        C + ".clang-format", C + ".clang-tidy", C + ".gitignore", C + "tools/check_format.sh", C + "tools/build_occt.py",
        C + "tools/check_occt_guard.py", C + "tools/lsan.supp", C + "tools/gen_stubs.sh",
        C + "tools/landing_plan.py", C + "tools/gen_status.py", C + "scripts/",
        C + "README.md", C + "CONTRIBUTING.md", C + "ARCHITECTURE.md", C + "AGENTS.md", C + "PORTING_STATUS.md",
        C + "docs/READING_ORDER.md", C + "docs/LANDING_PLAN.md", C + "docs/DEVIATIONS.md", C + "docs/HANDOFF.md",
        C + "docs/briefs.md",
    ]),
    ("core, topo, kernel", [
        C + "include/scad/core/", C + "include/scad/topo/", C + "include/scad/kernel/",
        C + "src/core/", C + "src/topo/", C + "src/kernel/",
        C + "tests/cpp/core/", C + "tests/cpp/topo/", C + "tests/cpp/kernel/",
        C + "docs/memory.md", C + "tools/bench/",
    ]),
    ("semantic (tags, lineage, tracking, finalize)", [
        C + "include/scad/semantic/", C + "src/semantic/", C + "tests/cpp/semantic/",
    ]),
    ("reactive (expressions, units, graph, recompute)", [
        C + "include/scad/reactive/", C + "src/reactive/", C + "tests/cpp/reactive/",
    ]),
    ("io, render, ql", [
        C + "include/scad/io/", C + "src/io/", C + "tests/cpp/io/", C + "tests/golden/io_", C + "docs/io.md",
        C + "include/scad/render/", C + "src/render/", C + "tests/cpp/render/", C + "docs/render.md",
        C + "docs/render/",
        C + "include/scad/ql/", C + "src/ql/", C + "tests/cpp/ql/",
    ]),
    ("ops_geometry, ops_features", [
        C + "include/scad/ops/", C + "src/ops/", C + "tests/cpp/ops_geometry/", C + "tests/cpp/ops_features/",
    ]),
    ("sketch, surface", [
        C + "include/scad/sketch/", C + "src/sketch/", C + "tests/cpp/sketch/", C + "docs/sketch-solver.md",
        C + "include/scad/surface/", C + "src/surface/", C + "tests/cpp/surface/",
        C + "cmake/ScadGordon.cmake", C + "third_party/occ_gordon/",
    ]),
    ("product, std", [
        C + "include/scad/product/", C + "src/product/", C + "tests/cpp/product/",
        C + "include/scad/std/", C + "src/std/", C + "tests/cpp/std/",
    ]),
    ("python bindings, adapter, parity tests", [
        C + "bindings/python/", "src/simplecadapi/_cpp/", "src/simplecadapi/_glue/",
        C + "tests/python/", C + "tests/golden/",
        C + "tools/graph_parity/", C + "docs/NATIVE_INTEGRATION.md", C + "docs/NATIVE_PROGRESS.md", C + "docs/PERF.md",
    ]),
    ("OCCT shim, wheels, release, research", [
        C + "bindings/python/occt/", C + "occt_dev/", C + "docs/OCCT_BINDINGS.md", C + "tools/occt_usage_trace.json",
        "src/simplecadapi/_cpp/occt.py", "src/simplecadapi/_cpp/_occt_layout.json",
        "pyproject.toml", ".github/workflows/", C + ".github/", C + "tests/wheel_smoke.py",
        C + "docs/research/", C + "tools/research/",
    ]),
]
# Files the glob rules above would give to an earlier, broader prefix are overridden by the longest match; the golden
# files of tests/golden other than io_* therefore land in the bindings PR (the prefix C + "tests/golden/").


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def universe(rev: str) -> list[str]:
    if rev == "WORKTREE":
        names = git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    else:
        names = git("ls-tree", "-r", "--name-only", rev).splitlines()
    wanted = (C, "src/simplecadapi/_cpp/", "src/simplecadapi/_glue/", ".github/workflows/")
    out = [n for n in names if n.startswith(wanted) or n == "pyproject.toml"]
    if rev == "WORKTREE":
        out = [n for n in out if Path(n).is_file()]
    return sorted(out)


def is_data(path: str) -> bool:
    """Vendored code, recorded goldens and binary/JSON data: counted apart, they are not reviewed line by line."""
    return (path.startswith(C + "third_party/") or path.startswith(C + "tests/golden/") or path.endswith(".png")
            or path.endswith(".json") or path.endswith("tracking_golden.hpp"))


def line_counts(rev: str, files: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    if rev == "WORKTREE":
        for f in files:
            counts[f] = Path(f).read_bytes().count(b"\n")
        return counts
    proc = subprocess.run(["git", "cat-file", "--batch"], input="".join(f"{rev}:{f}\n" for f in files).encode(),
                          check=True, capture_output=True)
    data, pos = proc.stdout, 0
    for f in files:
        end = data.index(b"\n", pos)
        _sha, _type, size = data[pos:end].decode().split()
        pos = end + 1
        counts[f] = data[pos:pos + int(size)].count(b"\n")
        pos += int(size) + 1
    return counts


def assign(files: list[str]) -> tuple[dict[int, list[str]], list[str], list[str]]:
    rules = [(prefix, i) for i, (_title, prefixes) in enumerate(PRS, 1) for prefix in prefixes]
    seen = Counter(prefix for prefix, _ in rules)
    dup = [p for p, n in seen.items() if n > 1]
    if dup:
        sys.exit(f"duplicate prefixes: {dup}")
    groups: dict[int, list[str]] = {i: [] for i in range(1, len(PRS) + 1)}
    left_over: list[str] = []
    used: set[str] = set()
    for f in files:
        best = max((r for r in rules if f.startswith(r[0])), key=lambda r: len(r[0]), default=None)
        if best is None:
            left_over.append(f)
        else:
            groups[best[1]].append(f)
            used.add(best[0])
    stale = sorted({p for p, _ in rules} - used)
    return groups, left_over, stale


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rev", default="HEAD", help="a git revision, or WORKTREE (default HEAD)")
    ap.add_argument("--files", action="store_true", help="list every file")
    ap.add_argument("--pr", type=int, help="list the files of this PR only")
    args = ap.parse_args()

    root = Path(git("rev-parse", "--show-toplevel").strip())
    import os
    os.chdir(root)

    files = universe(args.rev)
    groups, left_over, stale = assign(files)
    lines = line_counts(args.rev, files)

    if args.pr:
        for f in groups[args.pr]:
            print(f)
    else:
        total_f = total_l = 0
        total_d = 0
        print(f"{'PR':>2}  {'files':>5}  {'lines':>7}  {'data':>7}  title")
        print("    lines = code, docs, scripts; data = vendored code, goldens, json (png files count as 0)")
        for i, (title, _) in enumerate(PRS, 1):
            n = len(groups[i])
            ln = sum(lines[f] for f in groups[i] if not is_data(f))
            dl = sum(lines[f] for f in groups[i] if is_data(f) and not f.endswith(".png"))
            total_f, total_l, total_d = total_f + n, total_l + ln, total_d + dl
            print(f"{i:>2}  {n:>5}  {ln:>7}  {dl:>7}  {title}")
        print(f"{'':>2}  {total_f:>5}  {total_l:>7}  {total_d:>7}  total ({len(files)} files in the universe)")
        if args.files:
            for i, (title, _) in enumerate(PRS, 1):
                print(f"\n== PR {i}: {title}")
                for f in groups[i]:
                    print(f"{'-' if f.endswith('.png') else lines[f]:>7}  {f}")

    ok = True
    if left_over:
        ok = False
        print("\nLEFT OVER (matches no PR):", *left_over, sep="\n  ", file=sys.stderr)
    if stale:
        ok = False
        print("\nSTALE RULES (match no file):", *stale, sep="\n  ", file=sys.stderr)
    assigned = sum(len(g) for g in groups.values())
    if assigned != len(files):
        ok = False
        print(f"\nassigned {assigned} of {len(files)} files", file=sys.stderr)
    if not args.pr:
        print("\ncheck:", "every file in exactly one PR, no stale rule" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

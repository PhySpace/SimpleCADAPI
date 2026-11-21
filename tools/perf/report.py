"""Summarize two-process-order A/B batches, fail on a changed BLDC interface."""

from pathlib import Path
import json
from statistics import median

ROOT = Path(__file__).resolve().parent


def data(label, kind):
    return [
        json.loads((ROOT / "results" / f"{label}-{n}-{kind}.json").read_text())["data"]
        for n in (1, 2)
    ]


def main():
    ref, mod = data("ab-dev", "bldc"), data("ab-final", "bldc")
    for r in ref + mod:
        for field in ("components", "constraints", "parts", "root_cells"):
            if ref[0][field] != r[field]:
                raise ValueError(f"BLDC {field} differs")
    raw = json.loads((ROOT / "results/dev-blobs.json").read_text())
    final = json.loads((ROOT / "results/final-brep.json").read_text())["data"]
    release = json.loads((ROOT / "results/release-wheel-bldc.json").read_text())["data"]
    for measured in (final, release):
        if raw != measured["brep_sha256"] or ref[0]["parts"] != measured["parts"]:
            raise ValueError("BLDC exact BREP bytes or geometry interface changed")
    print(
        f"BLDC: {len(ref[0]['parts'])} matching part hashes and tolerance profiles, "
        f"{len(raw)} byte-identical binary BReps, {r['components']} top-level components, {r['constraints']} constraints.\n"
    )
    print("| BLDC (s) | dev | optimized | dev/optimized |")
    print("|---|---:|---:|---:|")
    for field in ("build_s", "capture_s", "total_s"):
        a, b = (median(x[field] for x in group) for group in (ref, mod))
        print(f"| {field} | {a:.3f} | {b:.3f} | {a/b:.3f} |")
    print("\n| Factory (ms) | dev | optimized | dev/optimized |")
    print("|---|---:|---:|---:|")
    ref, mod = data("ab-dev", "operators"), data("ab-final", "operators")
    for field in ref[0]:
        a, b = (median(median(x[field]) for x in group) for group in (ref, mod))
        print(f"| {field} | {a:.4f} | {b:.4f} | {a/b:.3f} |")


if __name__ == "__main__":
    main()

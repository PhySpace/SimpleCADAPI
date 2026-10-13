"""Stage 3 — validate generated FTC solids against source traces and optional STEP."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from b3ftc.validation import validate_directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ftc-dir", type=Path, required=True)
    parser.add_argument("--traces-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--reference-step-dir", type=Path)
    parser.add_argument("--reference-python", help="Optional independent OCCT interpreter for STEP differences")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--python", dest="python_executable", help="SimpleCADAPI worker interpreter")
    args = parser.parse_args(argv)
    if not args.ftc_dir.is_dir() or not args.traces_dir.is_dir():
        parser.error("--ftc-dir and --traces-dir must be existing directories")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be positive and finite")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.reference_python and not args.reference_step_dir:
        parser.error("--reference-python requires --reference-step-dir")
    report = validate_directory(args.ftc_dir, args.traces_dir, timeout=args.timeout,
                                reference_step_dir=args.reference_step_dir, limit=args.limit,
                                python_executable=args.python_executable,
                                reference_python=args.reference_python)
    for row in report["rows"]:
        print(f"{row['stem']}: {row['quality']} (build={row['build']}, reasons={','.join(row['reasons']) or 'none'})")
    print(json.dumps(report["counts"]))
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["rows"] and not (report["counts"]["rejected"] or report["counts"]["partial"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

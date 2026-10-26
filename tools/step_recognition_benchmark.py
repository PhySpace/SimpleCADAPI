"""Re-run STEP feature recognition from a comparison measurements manifest.

Example:
    python tools/step_recognition_benchmark.py --measurements measurements.json \
        --output recognition-current.json --version input
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid


FEATURE_KINDS = (
    "hole",
    "extrusion",
    "revolution",
    "loft",
    "sweep",
    "fillet",
    "chamfer",
    "sheet_metal",
)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _worker(
    path: Path, output: Path, max_features: int, kinds: tuple[str, ...]
) -> None:
    from simplecadapi.inspect import brep

    catalog = brep.inspect_geometric_features_rdescriptor(
        path,
        feature_kinds=kinds,
        max_features=max_features,
    )
    features = catalog["features"]
    output.write_text(
        json.dumps(
            {
                "candidate_count": len(features),
                "categories": dict(
                    sorted(Counter(f["category"] for f in features).items())
                ),
                "features": [
                    {
                        "category": f["category"],
                        "subtype": f["subtype"],
                        "confidence": f["confidence"]["level"],
                        "recommended_api": (
                            (f.get("reconstruction") or {}).get("recommended_operation")
                            or {}
                        ).get("api"),
                        "spine_source": (
                            (f.get("reconstruction") or {}).get("spine") or {}
                        ).get("source"),
                    }
                    for f in features
                ],
                "unowned_face_count": len(catalog["coverage"]["unowned_face_ids"]),
                "truncated": catalog.get("truncated", False),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", default="input")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-features", type=int, default=200)
    parser.add_argument("--feature-kinds", nargs="+", default=FEATURE_KINDS)
    parser.add_argument(
        "--case", action="append", help="Run only this case; repeatable"
    )
    parser.add_argument("--worker", nargs=4, metavar=("STEP", "OUTPUT", "MAX", "KINDS"))
    args = parser.parse_args()
    if args.worker is not None:
        _worker(
            Path(args.worker[0]),
            Path(args.worker[1]),
            int(args.worker[2]),
            tuple(args.worker[3].split(",")),
        )
        return
    if args.timeout <= 0 or args.max_features <= 0:
        parser.error("timeout and max-features must be positive")
    measurements = json.loads(args.measurements.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in measurements:
        if args.case and case["case"] not in args.case:
            continue
        step = Path(case[args.version]["path"])
        row = {"case": case["case"], "version": args.version}
        if not step.is_file():
            row.update(status="missing_input")
            rows.append(row)
            continue
        row["step_sha256"] = _hash(step)
        started = time.monotonic()
        result_path = args.output.with_name(
            f".{args.output.stem}-{uuid.uuid4().hex}.tmp.json"
        )
        try:
            run = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--measurements",
                    str(args.measurements),
                    "--output",
                    str(args.output),
                    "--worker",
                    str(step),
                    str(result_path),
                    str(args.max_features),
                    ",".join(args.feature_kinds),
                ],
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
            if run.returncode == 0 and result_path.is_file():
                row.update(
                    status="completed",
                    **json.loads(result_path.read_text(encoding="utf-8")),
                )
            else:
                row.update(status="error", error=(run.stderr or run.stdout)[-1000:])
        except subprocess.TimeoutExpired:
            row.update(status="timeout")
        finally:
            result_path.unlink(missing_ok=True)
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        rows.append(row)
        print(f"{row['case']}: {row['status']}", flush=True)
    result = {
        "source_manifest": str(args.measurements.resolve()),
        "version": args.version,
        "timeout_seconds_per_case": args.timeout,
        "max_features": args.max_features,
        "feature_kinds": args.feature_kinds,
        "cases": rows,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

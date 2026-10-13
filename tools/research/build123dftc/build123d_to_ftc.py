"""Stage 2: translate portable build123d traces into native FTC Python."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def safe_stem(stem):
    if not isinstance(stem, str) or stem in ("", ".", "..") or any(c in stem for c in ("/", "\\", "\x00", "\n", "\r")):
        raise ValueError("stem must be a single nonempty filename")
    return stem


def translate_trace_file(trace_path: Path, out_dir: Path, *, constraints_mode=False):
    from b3ftc.replay import replay_trace_to_ftc
    from b3ftc.schema import SCHEMA_VERSION
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    stem = safe_stem(payload.get("stem", trace_path.name.removesuffix(".trace.json")))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported trace schema: {payload.get('schema_version')!r}")
    options = {"constraints_mode": True} if constraints_mode else {}
    source, meta = replay_trace_to_ftc(payload, stem=stem, **options)
    meta = {"stem": stem, "source_file": payload.get("source_file"), **meta}
    snapshots = meta.pop("sketches", [])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.ftc.py").write_text(source, encoding="utf-8")
    (out_dir / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (out_dir / f"{stem}.sketches.json").write_text(json.dumps({"stem": stem, "constraints_mode": constraints_mode, "sketches": snapshots},
        ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return stem, source, meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--trace")
    inputs.add_argument("--traces-dir")
    parser.add_argument("--out", default="tools/research/build123dftc/out/ftc")
    parser.add_argument("--constraints", choices=("on", "off"), default="off", help="recover inferred constraints with the existing CQ engine")
    args = parser.parse_args(argv)
    paths = [Path(args.trace)] if args.trace else sorted(Path(args.traces_dir).glob("*.trace.json"))
    if not paths:
        parser.error("no traces found")
    failed = 0
    for path in paths:
        try:
            stem, source, meta = translate_trace_file(path, Path(args.out), constraints_mode=args.constraints == "on")
            failed += meta["status"] != "ok"
            print(f"{stem}: {meta['status']} ({meta.get('feature_count', 0)} features, {len(meta.get('unsupported', []))} unsupported)", flush=True)
        except Exception as error:
            failed += 1
            stem = safe_stem(path.name.removesuffix(".trace.json"))
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{stem}.meta.json").write_text(json.dumps({"stem": stem, "status": "error", "unsupported": [f"{type(error).__name__}: {error}"]}, indent=2) + "\n")
            print(f"{stem}: translation_error: {type(error).__name__}: {error}", flush=True)
    print(f"translated {len(paths)} traces, {failed} incomplete -> {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

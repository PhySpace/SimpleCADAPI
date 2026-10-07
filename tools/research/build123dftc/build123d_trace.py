"""Stage 1: execute trusted build123d models in isolated worker processes."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from b3ftc.schema import empty_trace


def discover_inputs(*, input_file=None, inputs_dir=None, manifest=None):
    if input_file:
        paths = [Path(input_file).resolve()]
    elif manifest:
        path = Path(manifest).resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        paths = [(path.parent / item["file"]).resolve() for item in payload["examples"]]
    elif inputs_dir:
        paths = sorted(Path(inputs_dir).resolve().glob("*.py"))
    else:
        raise ValueError("one input source is required")
    if not paths:
        raise ValueError("no Python models found")
    if any(not p.is_file() for p in paths):
        raise FileNotFoundError("some declared model files do not exist")
    stems = [p.stem for p in paths]
    if len(set(stems)) != len(stems):
        raise ValueError("model stems must be unique within one batch")
    return paths


def trace_model(path: Path, out_dir: Path, *, stem=None, timeout=120, python_executable=None, source_metadata=None):
    from build123d_to_ftc import safe_stem
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    path = path.resolve()
    stem = safe_stem(stem or path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"{stem}.trace.json"
    temporary = out_dir / f"{stem}.trace.tmp.json"
    log_path = out_dir / f"{stem}.trace.log"
    temporary.unlink(missing_ok=True)
    command = [python_executable or sys.executable, str(TOOLS / "b3ftc/_trace_worker.py"),
               str(path), str(temporary.resolve())]
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, cwd=path.parent,
                                   start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
            failure = f"trace worker exited with code {code}" if code else ""
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait()
            failure = f"source execution timed out after {timeout}s"
    if failure or not temporary.exists():
        payload = empty_trace()
        payload.update(b3d_status="error", source_file=str(path), error=failure or "worker produced no trace")
        with log_path.open("rb") as log:
            log.seek(max(0, log_path.stat().st_size - 4096))
            payload["error"] += "\n" + log.read().decode("utf-8", errors="replace")
    else:
        payload = json.loads(temporary.read_text(encoding="utf-8"))
    payload["stem"] = stem
    if source_metadata:
        payload["source_metadata"] = source_metadata
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", dest="input_file", help="one trusted Python source")
    inputs.add_argument("--inputs-dir", "--dataset", dest="inputs_dir", help="directory of Python models")
    inputs.add_argument("--manifest", help="JSON examples manifest, paths relative to manifest")
    parser.add_argument("--out", default="tools/research/build123dftc/out/traces")
    parser.add_argument("--stem", help="output stem for one source")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--python", dest="python_executable", help="interpreter with build123d installed")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error("timeout and limit must be positive")
    if args.stem and not args.input_file:
        parser.error("--stem requires --input")
    paths = discover_inputs(input_file=args.input_file, inputs_dir=args.inputs_dir, manifest=args.manifest)
    metadata = {}
    if args.manifest:
        manifest_path = Path(args.manifest).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        metadata = {str((manifest_path.parent / row["file"]).resolve()):
            {key: row[key] for key in ("source_url", "source_sha256", "export_options") if key in row}
            for row in manifest["examples"]}
    paths = paths[:args.limit] if args.limit else paths
    failed = 0
    for path in paths:
        row = trace_model(path, Path(args.out), stem=args.stem, timeout=args.timeout,
                          python_executable=args.python_executable, source_metadata=metadata.get(str(path)))
        failed += row["b3d_status"] != "ok"
        print(f"{row['stem']}: {row['b3d_status']} ({len(row['steps'])} operations, "
              f"{len(row['unsupported'])} unsupported)", flush=True)
    print(f"captured {len(paths)} models, {failed} failed -> {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stage 3 — external acceptance: reconcile FTC builds against the trace.

All correctness questions live here, never in the translated source.  For each
row the validator:

1. executes the generated ``<stem>.ftc.py`` in this interpreter (the repo
   environment — no cadquery needed) and sums the ``BODIES`` volumes;
2. compares against the ground-truth ``cq_volume`` / ``cq_bbox`` recorded in
   the trace by stage 1;
3. classifies the row and writes a per-run report JSON.

Usage:

    .venv/bin/python tools/research/cadquery/cadquery_validate.py \
        --ftc-dir out/ftc --traces-dir out/traces --report out/validate.json
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
# the checkout's source tree only when it is a built one (it would shadow an installed wheel otherwise)
# (the module is a file; a directory `_native/` next to it holds the type stubs and is no sign of a build)
if str(_REPO_ROOT / "src") not in sys.path and any(
    path.is_file() for path in (_REPO_ROOT / "src" / "simplecadapi" / "_cpp").glob("_native*")
):
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from cqftc.tracer.trace_schema import OperationTrace  # noqa: E402

VOLUME_TOL = 1e-3  # relative
BBOX_TOL = 1e-3  # relative, per extent


_CASE_COUNTER = itertools.count()


def _run_ftc_build(ftc_path: Path, workdir: Path) -> tuple[str, Any]:
    """Materialize + exec the part source; returns (status, module).

    @scad.part is content-addressed cached: on a cache hit the builder body
    never re-executes, so module globals like BODIES would stay stale.  A
    unique staging filename per run forces a fresh build (same trick as the
    histjson validator's case files).
    """
    workdir.mkdir(parents=True, exist_ok=True)
    staged = workdir / f"{ftc_path.stem}_{os.getpid()}_{next(_CASE_COUNTER)}.ftc.py"
    staged.write_text(ftc_path.read_text(encoding="utf-8"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(staged.stem, staged)
    if spec is None or spec.loader is None:
        return f"build_error: cannot load {staged}", None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.build()
    except Exception as exc:
        return f"build_error: {type(exc).__name__}: {exc}", module
    finally:
        staged.unlink(missing_ok=True)
    return "ok", module


def _bodies_volume(module: Any) -> float | None:
    bodies = getattr(module, "BODIES", None)
    if not bodies:
        return None
    try:
        return sum(float(body.get_volume()) for body in bodies)
    except Exception:
        return None


def _relative_error(actual: float | None, expected: float | None) -> float | None:
    if actual is None or expected is None or expected == 0.0:
        return None
    return abs(actual - expected) / abs(expected)


def validate_row(ftc_path: Path, trace_path: Path, workdir: Path) -> dict:
    trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))
    cq_volume = trace_payload.get("cq_volume")
    cq_bbox = trace_payload.get("cq_bbox")
    unsupported = 0
    meta_path = ftc_path.with_name(ftc_path.name.replace(".ftc.py", ".meta.json"))
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        unsupported = len(meta.get("unsupported", []))

    status, module = _run_ftc_build(ftc_path, workdir)
    volume = _bodies_volume(module) if status == "ok" else None
    volume_err = _relative_error(volume, cq_volume)
    bbox_err = None
    if volume is not None and cq_bbox and status == "ok":
        try:
            from simplecadapi._cpp.occt.Bnd import Bnd_Box
            from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib

            box = Bnd_Box()
            for body in module.BODIES:
                # useTriangulation=False, useShapeTolerance=False: exact tight
                # bounds; defaults inflate by shape tolerance and fake
                # percent-scale bbox errors against the CadQuery ground truth.
                BRepBndLib.AddOptimal_s(body.wrapped, box, False, False)
            xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
            extents = [xmax - xmin, ymax - ymin, zmax - zmin]
            cq_extents = [
                cq_bbox[3] - cq_bbox[0],
                cq_bbox[4] - cq_bbox[1],
                cq_bbox[5] - cq_bbox[2],
            ]
            bbox_err = max(
                abs(a - b) / max(abs(b), 1e-9) for a, b in zip(extents, cq_extents)
            )
        except Exception:
            bbox_err = None

    quality = "rejected"
    if status == "ok" and volume_err is not None and volume_err <= VOLUME_TOL:
        if bbox_err is None or bbox_err <= BBOX_TOL:
            quality = "accepted" if unsupported == 0 else "partial"
        else:
            quality = "partial" if unsupported == 0 else "rejected"
    elif status == "ok" and unsupported:
        quality = "partial"

    return {
        "stem": ftc_path.name.replace(".ftc.py", ""),
        "build": status,
        "cq_volume": cq_volume,
        "ftc_volume": volume,
        "volume_error": volume_err,
        "bbox_error": bbox_err,
        "untranslated_notes": unsupported,
        "quality": quality,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ftc-dir", required=True, help="directory of *.ftc.py from stage 2")
    parser.add_argument("--traces-dir", required=True, help="directory of *.trace.json from stage 1")
    parser.add_argument("--report", default="", help="write a report JSON to this path")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    ftc_dir = Path(args.ftc_dir)
    traces_dir = Path(args.traces_dir)
    workdir = ftc_dir / "_cases"
    rows = []
    for ftc_path in sorted(ftc_dir.glob("*.ftc.py")):
        stem = ftc_path.name.replace(".ftc.py", "")
        trace_path = traces_dir / f"{stem}.trace.json"
        if not trace_path.exists():
            rows.append({"stem": stem, "build": "missing trace", "quality": "rejected"})
            continue
        try:
            rows.append(validate_row(ftc_path, trace_path, workdir))
        except Exception as exc:
            rows.append(
                {
                    "stem": stem,
                    "build": f"validator_error: {type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=3),
                    "quality": "rejected",
                }
            )
        if args.limit is not None and len(rows) >= args.limit:
            break

    summary = {
        "rows": rows,
        "counts": {
            "accepted": sum(1 for r in rows if r.get("quality") == "accepted"),
            "partial": sum(1 for r in rows if r.get("quality") == "partial"),
            "rejected": sum(1 for r in rows if r.get("quality") == "rejected"),
        },
    }
    for row in rows:
        print(
            f"{row.get('stem')}: {row.get('quality')} "
            f"(build={row.get('build')}, vol_err={row.get('volume_error')}, "
            f"bbox_err={row.get('bbox_error')}, notes={row.get('untranslated_notes')})"
        )
    print(json.dumps(summary["counts"]))
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

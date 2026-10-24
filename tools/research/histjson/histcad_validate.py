#!/usr/bin/env python3
"""Execute translated HistCAD FTC sources and reconcile against STEP truth.

For each sampled uid: translate the HistCAD JSON into a clean FTC source
(``histcad_to_ftc.translate_steps`` — pure translation), execute it
in-process, read the packaged STEP file, and compare total solid volume.
Writes a JSON report and prints a pass/fail summary. Constraint auditing
(solve outcomes, conflicts, drift) lives in histcad_conflicts.py.

Usage:
    python tools/research/histjson/histcad_validate.py --tar JSON.tar.gz
        --step-tar STEP.tar.gz [--uids a/b,c/d] [--count N] [--stride K]
        [--workers W] [--constraints on|off] [--report PATH]
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import os
import sys
import tarfile
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from histcad_to_ftc import translate_steps  # noqa: E402

_TOLERANCE = 1e-3  # relative volume error


def _step_volume(step_bytes: bytes) -> Optional[float]:
    from simplecadapi._cpp.occt.BRepGProp import BRepGProp
    from simplecadapi._cpp.occt.GProp import GProp_GProps
    from simplecadapi._cpp.occt.IFSelect import IFSelect_RetDone
    from simplecadapi._cpp.occt.STEPControl import STEPControl_Reader
    from simplecadapi._cpp.occt.TopAbs import TopAbs_SOLID
    from simplecadapi._cpp.occt.TopExp import TopExp_Explorer

    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as handle:
        handle.write(step_bytes)
        path = handle.name
    reader = STEPControl_Reader()
    try:
        if reader.ReadFile(path) != IFSelect_RetDone:
            return None
        reader.TransferRoots()
        shape = reader.OneShape()
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        volume = 0.0
        while explorer.More():
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(explorer.Current(), props)
            volume += props.Mass()
            explorer.Next()
        return volume if volume > 0 else None
    finally:
        Path(path).unlink(missing_ok=True)


_CASES_DIR = Path(__file__).resolve().parent / "out" / "_cases"
_CASE_COUNTER = itertools.count()


def _build_volume(source: str) -> Optional[float]:
    # @scad.part inspects the build function's real source file and needs a
    # project root, so materialize the case inside the repository tree.
    _CASES_DIR.mkdir(parents=True, exist_ok=True)
    module_path = _CASES_DIR / f"case_{os.getpid()}_{next(_CASE_COUNTER)}.py"
    module_path.write_text(source)
    try:
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.build()

        from simplecadapi._cpp.occt.BRepGProp import BRepGProp
        from simplecadapi._cpp.occt.GProp import GProp_GProps

        def _volume(solid) -> float:
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(solid, props)
            return float(props.Mass())

        bodies = getattr(module, "BODIES", None)
        if bodies:
            return sum(_volume(b.wrapped) for b in bodies)
        part = getattr(result, "part", result)
        body = getattr(part, "body", part)
        solid = getattr(body, "wrapped", None)
        if solid is None:
            return _ErrorVolume("build returned no solid")
        return _volume(solid)
    except Exception as exc:  # noqa: BLE001
        return _ErrorVolume(str(exc)[:300])
    finally:
        module_path.unlink(missing_ok=True)


class _ErrorVolume(float):
    def __new__(cls, message: str) -> "_ErrorVolume":
        instance = super().__new__(cls, math.nan)
        instance.message = message  # type: ignore[attr-defined]
        return instance


def _evaluate_case(payload: Dict[str, Any]) -> Dict[str, Any]:
    uid = payload["uid"]
    entry: Dict[str, Any] = {"uid": uid}
    try:
        source = translate_steps(
            payload["steps"], uid, constraints_mode=payload["constraints"]
        )
    except Exception as exc:  # noqa: BLE001
        entry.update(status="translate_error", error=str(exc)[:300])
        return entry
    entry["source"] = source
    entry["line_count"] = source.count("\n")
    built = _build_volume(source)
    if isinstance(built, _ErrorVolume) or built is None:
        entry.update(status="build_error", error=getattr(built, "message", "no volume"))
        return entry
    entry["built_volume"] = built
    truth = _step_volume(payload["step_bytes"])
    if truth is None:
        entry.update(status="step_missing")
        return entry
    entry["step_volume"] = truth
    relative = abs(built - truth) / truth if truth > 0 else math.inf
    entry["rel_error"] = relative
    entry["status"] = "pass" if relative <= _TOLERANCE else "volume_mismatch"
    return entry


def _pick_members(tar: tarfile.TarFile, names: List[str]) -> Dict[str, Any]:
    payloads: Dict[str, Any] = {}
    for member in tar:
        if member.name in names:
            payloads[member.name] = tar.extractfile(member).read()
    return payloads


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tar", type=Path, required=True)
    parser.add_argument("--step-tar", type=Path, required=True)
    parser.add_argument("--uids", type=str, default="")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--stride", type=int, default=997)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--constraints", choices=["on", "off"], default="off")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    with tarfile.open(args.tar, "r:gz") as json_tar:
        members = [m.name for m in json_tar if m.name.endswith(".json")]
        if args.uids:
            wanted = {f"{uid}.json" for uid in args.uids.split(",")}
            members = [m for m in members if m in wanted]
        else:
            members = members[:: args.stride][: args.count]
        json_payloads = _pick_members(json_tar, members)

    with tarfile.open(args.step_tar, "r:gz") as step_tar:
        stems = {Path(name).stem for name in json_payloads}
        step_names = [m.name for m in step_tar if Path(m.name).stem in stems]
        step_payloads = _pick_members(step_tar, step_names)

    payloads = []
    for name, blob in json_payloads.items():
        uid = name[: -len(".json")]
        step_bytes = step_payloads.get(uid + ".step")
        if step_bytes is None:
            # HistCAD stores steps under the same relative path stem
            step_bytes = next(
                (b for n, b in step_payloads.items() if Path(n).stem == Path(name).stem),
                None,
            )
        if step_bytes is None:
            continue
        payloads.append(
            {
                "uid": uid,
                "steps": json.loads(blob),
                "step_bytes": step_bytes,
                "constraints": args.constraints,
            }
        )

    print(f"evaluating {len(payloads)} cases (constraints={args.constraints})")
    results: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(_evaluate_case, payloads):
            status = result.get("status")
            extra = (
                f" rel={result.get('rel_error'):.2e}"
                if status in {"pass", "volume_mismatch"}
                else f" err={result.get('error', '')[:120]}"
            )
            print(f"  {result['uid']}: {status}{extra}")
            results.append(result)

    counts: Dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    print("summary:", dict(sorted(counts.items())))
    errors = [r for r in results if r["status"] in {"translate_error", "build_error"}]
    for error in errors[:10]:
        print(f"  ! {error['uid']}: {error.get('error', '')[:200]}")

    report = args.report or Path(__file__).resolve().parent / "out" / "histcad_validate.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    slim = [
        {k: v for k, v in r.items() if k != "source"} for r in results
    ]
    report.write_text(json.dumps({"counts": counts, "results": slim}, indent=2))
    print(f"wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

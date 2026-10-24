#!/usr/bin/env python3
"""Sampling validation: translate WHUCAD h5 → FTC, execute, reconcile volume
against the packaged BRep truth (sampled download from the official mirror).

Because the released vectors are unit-cube normalized (absolute scale is not
in the data), the FTC model and the BRep truth are compared shape-wise: the
built solid is rescaled by the bbox-diagonal ratio before the volume check.

Usage:
    .venv/bin/python tools/research/whucad/whucad_validate.py \
        --vec-dir .../WHUCAD/data/vec/0000 --count 40 --stride 37 \
        [--truth-dir /tmp/whucad_truth] [--report out/whucad_validate.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

_TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS))

import whucad_vec as wvec  # noqa: E402
from whucad_to_ftc import translate_features  # noqa: E402

_TOLERANCE = 2e-2  # relative volume error (256-level quantization ≈ 0.4%/dim)

_TRUTH_URL = "https://gitee.com/fred926/whucad-brep/raw/master/Brep/{folder}/{uid}.stp"


def _fetch_truth(uid: str, truth_dir: Path) -> Optional[Path]:
    folder = uid[:4]
    path = truth_dir / folder / f"{uid}.stp"
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    url = _TRUTH_URL.format(folder=folder, uid=uid)
    try:
        with urllib.request.urlopen(url, timeout=60) as response, path.open("wb") as handle:
            handle.write(response.read())
        return path
    except Exception:
        path.unlink(missing_ok=True)
        return None


def _bbox_diagonal(solid) -> float:
    from simplecadapi._cpp.occt.Bnd import Bnd_Box
    from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    box.SetGap(0.0)
    # optimal + no triangulation: the default Add uses surface control
    # points (and triangulation boxes overshoot) — curved faces come back
    # ~7% loose, corrupting the scale correction
    BRepBndLib.AddOptimal_s(solid, box, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return math.dist((xmin, ymin, zmin), (xmax, ymax, zmax))


def _solid_volume(shape) -> float:
    from simplecadapi._cpp.occt.BRepGProp import BRepGProp
    from simplecadapi._cpp.occt.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return float(props.Mass())


def _step_volume(path: Path) -> Optional[float]:
    from simplecadapi._cpp.occt.IFSelect import IFSelect_RetDone
    from simplecadapi._cpp.occt.STEPControl import STEPControl_Reader
    from simplecadapi._cpp.occt.TopAbs import TopAbs_SOLID
    from simplecadapi._cpp.occt.TopExp import TopExp_Explorer

    reader = STEPControl_Reader()
    try:
        if reader.ReadFile(str(path)) != IFSelect_RetDone:
            return None
        reader.TransferRoots()
        shape = reader.OneShape()
    except Exception:
        return None
    volume = 0.0
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    count = 0
    while explorer.More():
        volume += _solid_volume(explorer.Current())
        count += 1
        explorer.Next()
    return volume if volume > 0 and count == 1 else (volume if volume > 0 else None)


def _build_volume(source: str, case_dir: Path, tag: str) -> Any:
    case_dir.mkdir(parents=True, exist_ok=True)
    module_path = case_dir / f"case_{tag}.py"
    module_path.write_text(source)
    try:
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.build()

        solids = []
        # @scad.part may re-execute the source in its own namespace, in which
        # case module.BODIES is not written — fall back to the returned Part
        bodies = getattr(module, "BODIES", None)
        if bodies:
            solids = [b.wrapped for b in bodies]
        else:
            part = getattr(result, "part", result)
            body = getattr(part, "body", part)
            solid = getattr(body, "wrapped", None)
            if solid is None:
                return _ErrorVolume("build returned no solid")
            solids = [solid]
        volumes = [_solid_volume(s) for s in solids]
        volume = sum(volumes)
        if volume <= 0:
            return _ErrorVolume("empty build")
        return _Built(volume, _bbox_diagonal(solids[0]), len(solids))
    except Exception as exc:  # noqa: BLE001
        return _ErrorVolume(str(exc)[:300])
    finally:
        module_path.unlink(missing_ok=True)


class _ErrorVolume(str):
    def __new__(cls, message: str) -> "_ErrorVolume":
        return super().__new__(cls, message)


class _Built:
    def __init__(self, volume: float, diagonal: float, n_bodies: int):
        self.volume = volume
        self.diagonal = diagonal
        self.n_bodies = n_bodies


def evaluate_case(payload: Dict[str, Any]) -> Dict[str, Any]:
    uid = payload["uid"]
    entry: Dict[str, Any] = {"uid": uid}
    try:
        features = wvec.decode_vec(payload["vec"], is_numerical=True)
        source = translate_features(features, f"{uid[:4]}/{uid}")
    except Exception as exc:  # noqa: BLE001
        entry.update(status="translate_error", error=str(exc)[:300])
        return entry
    entry["feature_count"] = len(features)
    entry["skipped_features"] = source.count("# step ")
    built = _build_volume(source, Path(payload["case_dir"]), uid)
    if isinstance(built, _ErrorVolume):
        entry.update(status="build_error", error=str(built)[:300])
        return entry
    entry["built_volume"] = built.volume
    entry["built_diagonal"] = built.diagonal
    entry["n_bodies"] = built.n_bodies
    truth = _step_volume(Path(payload["truth_path"]))
    if truth is None:
        entry.update(status="step_missing")
        return entry
    entry["truth_volume"] = truth
    truth_diag = _step_diagonal(Path(payload["truth_path"]))
    scale = truth_diag / built.diagonal if built.diagonal > 0 and truth_diag else None
    if scale is None:
        entry.update(status="scale_unknown")
        return entry
    entry["scale"] = scale
    relative = abs(built.volume * scale ** 3 - truth) / truth
    entry["rel_error"] = relative
    entry["status"] = "pass" if relative <= _TOLERANCE else "volume_mismatch"
    return entry


def _step_diagonal(path: Path) -> Optional[float]:
    from simplecadapi._cpp.occt.Bnd import Bnd_Box
    from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
    from simplecadapi._cpp.occt.IFSelect import IFSelect_RetDone
    from simplecadapi._cpp.occt.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    try:
        if reader.ReadFile(str(path)) != IFSelect_RetDone:
            return None
        reader.TransferRoots()
        shape = reader.OneShape()
        box = Bnd_Box()
        box.SetGap(0.0)
        BRepBndLib.AddOptimal_s(shape, box, False, False)
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        return math.dist((xmin, ymin, zmin), (xmax, ymax, zmax))
    except Exception:
        return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vec-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--stride", type=int, default=37)
    parser.add_argument("--uids", type=str, default="")
    parser.add_argument("--truth-dir", type=Path,
                        default=_TOOLS / "out" / "truth")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    paths = sorted(args.vec_dir.glob("*.h5"))
    if args.uids:
        wanted = set(args.uids.split(","))
        paths = [p for p in paths if p.stem in wanted]
    else:
        paths = paths[:: args.stride][: args.count]

    payloads = []
    skipped = []
    for path in paths:
        uid = path.stem
        truth = _fetch_truth(uid, args.truth_dir)
        if truth is None:
            skipped.append(uid)
            continue
        import h5py

        with h5py.File(path, "r") as fp:
            vec = fp["vec"][:].astype(int)
        payloads.append({"uid": uid, "vec": vec, "truth_path": str(truth),
                         "case_dir": str(_TOOLS / "out" / "_cases")})

    print(f"evaluating {len(payloads)} cases ({len(skipped)} truth downloads failed)")
    results: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(evaluate_case, payloads):
            status = result.get("status")
            extra = (f" rel={result.get('rel_error'):.3e}"
                     if status in {"pass", "volume_mismatch"}
                     else f" err={str(result.get('error', ''))[:110]}")
            print(f"  {result['uid']}: {status}{extra}")
            results.append(result)

    counts: Dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    print("summary:", dict(sorted(counts.items())))
    report = args.report or _TOOLS / "out" / "whucad_validate.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"counts": counts, "results": results}, indent=2))
    print(f"wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

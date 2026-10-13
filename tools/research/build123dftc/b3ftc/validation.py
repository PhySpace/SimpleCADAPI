"""Stage 3 acceptance, independent of the source CAD interpreter.

Each generated program runs in a separate process. Acceptance requires all
source metrics, complete translation, real nonempty valid solids, and matching
volume, absolute bounds and solid count. Optional STEP comparison checks both
directions of the geometric difference.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

VOLUME_RTOL = 1e-3
VOLUME_ATOL = 1e-6
BBOX_RTOL = 1e-3
BBOX_ATOL = 1e-4
DIFFERENCE_RTOL = 1e-3


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _bbox(value: Any) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 6
            and all(_finite_number(v) for v in value)
            and all(value[i] <= value[i + 3] for i in range(3)))


def _positive_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _translation_notes(payload: Mapping[str, Any]) -> bool:
    return any(bool(value) for name, value in payload.items()
               if name in {"unsupported", "untranslated", "unhandled"} or name.startswith("unknown"))


def compare_metrics(trace: Mapping[str, Any], actual: Mapping[str, Any],
                    meta: Mapping[str, Any] | None, *,
                    volume_rtol: float = VOLUME_RTOL, volume_atol: float = VOLUME_ATOL,
                    bbox_rtol: float = BBOX_RTOL, bbox_atol: float = BBOX_ATOL,
                    difference_rtol: float = DIFFERENCE_RTOL,
                    require_reference: bool = False) -> dict[str, Any]:
    """Compare untrusted JSON evidence; missing metrics always reject."""
    reasons: list[str] = []
    if trace.get("b3d_status") != "ok":
        reasons.append("source_failed")
    expected_volume, expected_bbox = trace.get("b3d_volume"), trace.get("b3d_bbox")
    expected_count = trace.get("solid_count")
    valid_source = (_finite_number(expected_volume) and expected_volume > 0
                    and _bbox(expected_bbox) and _positive_count(expected_count)
                    and bool(trace.get("result_refs")))
    if not valid_source:
        reasons.append("missing_source_metrics")
    if trace.get("b3d_valid") is False or trace.get("b3d_is_valid") is False:
        reasons.append("invalid_source")
    if _translation_notes(trace):
        reasons.append("unsupported_source")
    if not isinstance(meta, Mapping) or meta.get("status") != "ok":
        reasons.append("incomplete_translation")
    if isinstance(meta, Mapping) and _translation_notes(meta):
        reasons.append("untranslated_operations")
    if actual.get("status") != "ok":
        reasons.append("build_failed")
    if not _positive_count(actual.get("body_count")):
        reasons.append("empty_bodies")
    if actual.get("is_valid") is not True:
        reasons.append("invalid_topology")
    volume, bounds, count = actual.get("volume"), actual.get("bbox"), actual.get("solid_count")
    valid_actual = (_finite_number(volume) and volume > 0 and _bbox(bounds)
                    and _positive_count(count))
    if not valid_actual:
        reasons.append("missing_actual_metrics")
    volume_error = bbox_error = bbox_absolute_error = area_error = None
    if valid_source and valid_actual:
        volume_error = abs(volume - expected_volume) / abs(expected_volume)
        if abs(volume - expected_volume) > volume_atol + volume_rtol * abs(expected_volume):
            reasons.append("volume_mismatch")
        # Six world coordinates, scaled by axis span (never by world position).
        # A rigid translation therefore fails even when every extent matches.
        spans = [max(expected_bbox[i + 3] - expected_bbox[i], 1.0) for i in range(3)]
        deviations = [abs(a - b) for a, b in zip(bounds, expected_bbox)]
        bbox_absolute_error = max(deviations)
        bbox_error = max(delta / spans[i % 3] for i, delta in enumerate(deviations))
        if any(delta > bbox_atol + bbox_rtol * spans[i % 3]
               for i, delta in enumerate(deviations)):
            reasons.append("bbox_mismatch")
        if count != expected_count:
            reasons.append("solid_count_mismatch")
    expected_area, area = trace.get("b3d_area"), actual.get("area")
    if expected_area is not None:
        if not (_finite_number(expected_area) and expected_area > 0 and _finite_number(area) and area > 0):
            reasons.append("missing_area_metrics")
        else:
            area_error = abs(area - expected_area) / expected_area
            if abs(area - expected_area) > volume_atol + volume_rtol * abs(expected_area):
                reasons.append("area_mismatch")
    difference = actual.get("symmetric_difference_volume")
    difference_error = None
    if require_reference:
        reference_volume = actual.get("reference_volume")
        if (actual.get("reference_status") != "ok" or not _finite_number(difference)
                or difference < 0 or not _finite_number(reference_volume) or reference_volume <= 0):
            reasons.append("reference_error")
        else:
            difference_error = difference / reference_volume
            if difference > volume_atol + difference_rtol * reference_volume:
                reasons.append("symmetric_difference_mismatch")
        if "roundtrip_actual_volume" in actual:
            exported = {"status": "ok", "volume": actual.get("roundtrip_actual_volume"),
                        "bbox": actual.get("roundtrip_actual_bbox"),
                        "solid_count": actual.get("roundtrip_actual_solid_count"),
                        "body_count": actual.get("body_count"),
                        "is_valid": actual.get("roundtrip_actual_valid")}
            original = {"b3d_status": "ok", "b3d_volume": volume, "b3d_bbox": bounds,
                        "solid_count": count, "result_refs": ["actual"]}
            check = compare_metrics(original, exported, {"status": "ok"},
                                    volume_rtol=volume_rtol, volume_atol=volume_atol,
                                    bbox_rtol=bbox_rtol, bbox_atol=bbox_atol)
            if check["quality"] != "accepted":
                reasons.append("reference_roundtrip_changed_geometry")
    return {
        "quality": "rejected" if reasons else "accepted", "reasons": reasons,
        "b3d_volume": expected_volume if _finite_number(expected_volume) else None,
        "ftc_volume": volume if _finite_number(volume) else None,
        "b3d_bbox": expected_bbox if _bbox(expected_bbox) else None,
        "ftc_bbox": bounds if _bbox(bounds) else None,
        "b3d_solid_count": expected_count, "ftc_solid_count": count,
        "body_count": actual.get("body_count"), "is_valid": actual.get("is_valid"),
        "volume_error": volume_error, "bbox_error": bbox_error,
        "b3d_area": expected_area if _finite_number(expected_area) else None,
        "ftc_area": area if _finite_number(area) else None,
        "area_error": area_error,
        "bbox_absolute_error": bbox_absolute_error,
        "symmetric_difference_volume": difference if _finite_number(difference) else None,
        "symmetric_difference_error": difference_error,
    }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _interpreter(executable: str | None) -> str:
    executable = executable or sys.executable
    # Keep a venv symlink instead of resolving it to the base Python binary.
    return os.path.abspath(executable) if os.sep in executable else executable


def _process(command: list[str], staging: Path, env: Mapping[str, str],
             output: Path, timeout: float) -> dict[str, Any]:
    if timeout <= 0:
        return {"status": "timeout", "error": "case timeout exhausted before reference comparison"}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, cwd=staging, env=env,
                               start_new_session=os.name == "posix")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        stdout, stderr = process.communicate()
        return {"status": "timeout", "error": f"build exceeded {timeout:g} seconds",
                "stdout": stdout[-4000:], "stderr": stderr[-4000:]}
    if output.exists():
        try:
            result = _load_json(output)
        except (ValueError, OSError) as exc:
            result = {"status": "worker_error", "error": str(exc)}
    else:
        result = {"status": "worker_error", "error": f"worker exited {process.returncode} without metrics"}
    if process.returncode and result.get("status") == "ok":
        result.update(status="worker_error", error=f"worker exited {process.returncode}")
    if stdout.strip():
        result["stdout"] = stdout[-4000:]
    if stderr.strip():
        result["stderr"] = stderr[-4000:]
    return result


def _worker(ftc_path: Path, workdir: Path | None, timeout: float,
            reference_step: Path | None, python_executable: str | None,
            reference_python: str | None = None,
            export_options: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if timeout <= 0 or not math.isfinite(timeout):
        raise ValueError("timeout must be a positive finite number")
    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
    tool_dir = Path(__file__).resolve().parent.parent
    repo_root = tool_dir.parents[2]
    with tempfile.TemporaryDirectory(prefix="b3ftc-validate-", dir=workdir) as tmp:
        staging = Path(tmp).resolve()
        output = staging / "result.json"
        command = [_interpreter(python_executable), str(tool_dir / "b3ftc/_validate_worker.py"),
                   "--ftc", str(ftc_path.resolve()), "--output", str(output),
                   "--staging-dir", str(staging)]
        actual_step = staging / "actual.step"
        if reference_step is not None and reference_python is not None:
            command.extend(["--export-step", str(actual_step)])
            if export_options:
                command.extend(["--export-options", json.dumps(export_options)])
        elif reference_step is not None:
            command.extend(["--reference-step", str(reference_step.resolve())])
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([str(repo_root / "src"), str(tool_dir),
                                            env.get("PYTHONPATH", "")])
        started = time.monotonic()
        result = _process(command, staging, env, output, timeout)
        if reference_python is not None and reference_step is not None and result.get("status") == "ok":
            ref_output = staging / "reference.json"
            command = [_interpreter(reference_python), str(tool_dir / "b3ftc/_reference_worker.py"),
                       "--actual-step", str(actual_step), "--reference-step", str(reference_step.resolve()),
                       "--output", str(ref_output)]
            ref = _process(command, staging, env, ref_output, timeout - (time.monotonic() - started))
            result.update({key: value for key, value in ref.items()
                           if key.startswith(("reference_", "roundtrip_actual_", "symmetric_difference_"))})
            if ref.get("status") != "ok":
                result.update(reference_status="error", reference_error=ref.get("reference_error", ref.get("error", "")))
        return result


def validate_row(ftc_path: Path, trace_path: Path, workdir: Path | None = None, *,
                 timeout: float = 120, reference_step: Path | None = None,
                 python_executable: str | None = None,
                 reference_python: str | None = None) -> dict[str, Any]:
    """Validate one FTC. Errors are returned as rejected rows for batch use."""
    ftc_path, trace_path = Path(ftc_path), Path(trace_path)
    stem = ftc_path.name.removesuffix(".ftc.py")
    row: dict[str, Any] = {"stem": stem, "quality": "rejected", "metrics_quality": "rejected", "metrics_reasons": ["not_evaluated"]}
    try:
        if not ftc_path.is_file():
            return {**row, "build": "missing_ftc", "reasons": ["missing_ftc"]}
        if not trace_path.is_file():
            return {**row, "build": "missing_trace", "reasons": ["missing_trace"]}
        trace = _load_json(trace_path)
        meta_path = ftc_path.with_name(stem + ".meta.json")
        meta = _load_json(meta_path) if meta_path.is_file() else None
        # Reject absent/failed source or incomplete conversion without executing it.
        preliminary = compare_metrics(trace, {}, meta)
        source_reasons = [reason for reason in preliminary["reasons"] if reason in {
            "source_failed", "missing_source_metrics", "invalid_source", "unsupported_source",
            "incomplete_translation", "untranslated_operations"}]
        if source_reasons:
            return {**row, **preliminary, "build": "not_run", "reasons": source_reasons,
                    "error": trace.get("error", "")}
        metadata = trace.get("source_metadata") or {}
        export_options = metadata.get("export_options", trace.get("export_options"))
        metrics = _worker(ftc_path, Path(workdir) if workdir is not None else None,
                          timeout, Path(reference_step) if reference_step is not None else None,
                          python_executable, reference_python, export_options)
        result = compare_metrics(trace, metrics, meta, require_reference=reference_step is not None)
        basic = compare_metrics(trace, metrics, meta, require_reference=False)
        return {**row, **result, "build": metrics.get("status", "worker_error"),
                "metrics_quality": basic["quality"], "metrics_reasons": basic["reasons"],
                "error": metrics.get("error", ""),
                "reference_status": metrics.get("reference_status"),
                "reference_kernel": metrics.get("reference_kernel"),
                "reference_export_options": metrics.get("reference_export_options"),
                "reference_boolean_fuzzy_tolerance": metrics.get("reference_boolean_fuzzy_tolerance"),
                "reference_python": reference_python,
                "build_kernel": metrics.get("build_kernel"),
                "volume_method": metrics.get("volume_method"),
                "area_method": metrics.get("area_method"),
                "reference_error": metrics.get("reference_error", ""),
                "stdout": metrics.get("stdout", ""), "stderr": metrics.get("stderr", "")}
    except Exception as exc:
        return {**row, "build": "validator_error", "reasons": ["validator_error"],
                "error": f"{type(exc).__name__}: {exc}"}


def validate_directory(ftc_dir: Path, traces_dir: Path, *, timeout: float = 120,
                       reference_step_dir: Path | None = None, limit: int | None = None,
                       python_executable: str | None = None,
                       reference_python: str | None = None) -> dict[str, Any]:
    """Check the union of FTC and trace stems, never omit a failed conversion."""
    ftc_dir, traces_dir = Path(ftc_dir), Path(traces_dir)
    stems = sorted({path.name.removesuffix(".ftc.py") for path in ftc_dir.glob("*.ftc.py")}
                   | {path.name.removesuffix(".trace.json") for path in traces_dir.glob("*.trace.json")})
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be nonnegative")
        stems = stems[:limit]
    rows = [validate_row(ftc_dir / (stem + ".ftc.py"), traces_dir / (stem + ".trace.json"),
                         timeout=timeout, python_executable=python_executable,
                         reference_python=reference_python,
                         reference_step=(Path(reference_step_dir) / (stem + ".step"))
                         if reference_step_dir is not None else None) for stem in stems]
    return {"schema_version": "1.0", "rows": rows,
            "counts": {quality: sum(row["quality"] == quality for row in rows)
                       for quality in ("accepted", "partial", "rejected")},
            "tolerances": {"volume_relative": VOLUME_RTOL, "volume_absolute": VOLUME_ATOL,
                           "bbox_relative_to_axis_span": BBOX_RTOL, "bbox_absolute": BBOX_ATOL,
                           "symmetric_difference_relative": DIFFERENCE_RTOL},
            "volume_method": "Gauss-Kronrod, epsilon=1e-9, closed shells, BSpline spans",
            "area_method": "Independent geometry copy, C1 continuity spans, adaptive epsilon=1e-10",
            "reference_step_dir": str(reference_step_dir) if reference_step_dir else None,
            "reference_python": reference_python}

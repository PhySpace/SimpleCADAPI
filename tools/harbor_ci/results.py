"""Interpret native Harbor job results without trusting CLI exit status alone."""

from __future__ import annotations

import json
import math
from pathlib import Path


def _failed_verifier_checks(trial_dir: Path) -> list[dict]:
    """Read compact failure evidence without copying large verifier payloads."""
    status_path = trial_dir / "verifier" / "status.json"
    if not status_path.is_file():
        return []
    try:
        status = json.loads(status_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(status, dict):
        return []

    failed = []
    for check in status.get("checks") or []:
        if not isinstance(check, dict) or check.get("passed") is not False:
            continue
        detail = check.get("reason") or check.get("message") or check.get("error")
        actual = check.get("actual")
        if detail is None and isinstance(actual, dict):
            detail = (
                actual.get("reason")
                or actual.get("message")
                or actual.get("error")
            )
        failed.append(
            {
                "id": check.get("id") or "unknown",
                "gating": bool(check.get("gating")),
                "detail": detail if isinstance(detail, str) else None,
            }
        )
    return failed


def summarize(job_dir: Path, metadata: dict) -> dict:
    top_level = job_dir / "result.json"
    if not top_level.is_file():
        return {
            "overall": "ERROR",
            "metadata": metadata,
            "trials": [],
            "error": "missing result.json",
        }

    job = json.loads(top_level.read_text())
    trial_documents = []
    for child in sorted(job_dir.iterdir()):
        result = child / "result.json"
        if child.is_dir() and result.is_file():
            trial_documents.append(
                (json.loads(result.read_text()), _failed_verifier_checks(child))
            )

    trials = []
    for trial, failed_checks in trial_documents:
        exception = trial.get("exception_info")
        verifier = trial.get("verifier_result") or {}
        rewards = verifier.get("rewards") or {}
        reward = rewards.get("reward")
        reward_is_valid = (
            not isinstance(reward, bool)
            and isinstance(reward, (int, float))
            and math.isfinite(reward)
            and 0 <= reward <= 1
        )
        if exception or not reward_is_valid:
            status = "ERROR"
        elif reward == 1:
            status = "PASS"
        else:
            status = "FAIL"
        trials.append(
            {
                "task": trial.get("task_name"),
                "trial": trial.get("trial_name"),
                "status": status,
                "rewards": rewards,
                "exception": exception,
                "failed_checks": failed_checks,
            }
        )

    expected = job.get("n_total_trials")
    if (
        not isinstance(expected, int)
        or expected < 1
        or len(trials) != expected
        or any(trial["status"] == "ERROR" for trial in trials)
    ):
        overall = "ERROR"
    elif any(trial["status"] == "FAIL" for trial in trials):
        overall = "FAIL"
    else:
        overall = "PASS"
    return {"overall": overall, "metadata": metadata, "trials": trials, "job": job}


def write_reports(report: dict, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = ["# CADIR Harbor CI", "", f"Overall: **{report['overall']}**", ""]
    for trial in report.get("trials", []):
        reward = trial.get("rewards", {}).get("reward", "missing")
        lines.append(
            f"- `{trial.get('task')}`: **{trial['status']}** (reward={reward})"
        )
        if trial["status"] != "PASS" and trial.get("failed_checks"):
            for check in trial["failed_checks"]:
                qualifier = "gating" if check["gating"] else "non-gating"
                detail = f": {check['detail']}" if check.get("detail") else ""
                lines.append(f"  - failed `{check['id']}` ({qualifier}){detail}")
    if report.get("error"):
        lines.extend(["", f"Error: {report['error']}"])
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n")

"""Capture the BLDC actuator package once, then export STEP, FCStd and MJCF in parallel.

    uv run python examples/integrated_bldc_joint_actuator/export_all.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from export import capture_package

HERE = Path(__file__).resolve().parent
SCRIPTS = tuple(str(HERE / name) for name in ("export_mjcf.py", "export_step.py", "export_fcstd.py"))


def run(script: str) -> tuple[str, int, float, str, str]:
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, script, "--reuse-package"],
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    return script, proc.returncode, elapsed, proc.stdout, proc.stderr


def main() -> None:
    """Export MJCF, STEP, and FCStd from one captured package in parallel."""

    start = time.perf_counter()
    capture_package()
    print(f"[export] capture {time.perf_counter() - start:.1f}s")
    with ThreadPoolExecutor(max_workers=len(SCRIPTS)) as pool:
        futures = [pool.submit(run, script) for script in SCRIPTS]
        results = [future.result() for future in futures]
    for script, code, elapsed, stdout, stderr in sorted(results):
        status = "OK" if code == 0 else f"FAIL({code})"
        print(f"[export] {script.rsplit('/', 1)[-1]}: {status} {elapsed:.1f}s")
        if stdout.strip():
            print(_indent(stdout.strip()))
        if code != 0 and stderr.strip():
            print(_indent(stderr.strip()[-2000:]))
    failed = [r for r in results if r[1] != 0]
    print(f"[export] total {time.perf_counter() - start:.1f}s failed={len(failed)}")
    if failed:
        raise SystemExit(1)


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())


if __name__ == "__main__":
    main()

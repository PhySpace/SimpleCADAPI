"""Benchmark: the desktop 6-DOF arm (sandbox-envs/desktop_arm_sources/arm6.py).

Copies the case to a temporary directory (the source stays clean), then runs
the top notebook headlessly through a series of edits and prints the tree of
nested notebook runs with wall seconds and ran/cached cell counts.

    uv run python tools/profile_arm6.py [--keep DIR]

Baseline before cache work (2026-10-20, 8-core Apple silicon): cold 80.5s,
warm (no change) 23.6s, J1 edit 18.2s, UPPER_LENGTH edit 35.1s, BASE_D edit
22.8s, OPEN_STROKE edit 10.1s; cache directory 1.7 GB.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import profile_use_cascade as P  # noqa: E402

CASE = Path(__file__).resolve().parent.parent / "sandbox-envs" / "desktop_arm_sources"


def main() -> None:
    import os

    if os.environ.get("SCA_NO_PACK"):  # A/B: write cache entries uncompressed
        from simplecadapi.runtime import cache

        cache._MIN_PACKED = 1 << 60

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=Path, help="copy the case here and keep it")
    args = parser.parse_args()
    temporary = None if args.keep else tempfile.TemporaryDirectory()
    root = (args.keep or Path(temporary.name)).resolve() / "arm"  # type: ignore[union-attr]
    shutil.copytree(CASE, root, ignore=shutil.ignore_patterns("__marimo__", "__pycache__", "out"))
    top = root / "arm6.py"
    P.install_probe()
    P.scenario("cold", top)
    P.scenario("warm (nothing changed)", top)
    P.edit(top, 'J1=scad.var("j1", 0.0,unit="deg")', 'J1=scad.var("j1", 15.0,unit="deg")')
    P.scenario("edit J1 0->15 (solve only)", top)
    P.edit(top, 'upper_length", 90.0', 'upper_length", 95.0')
    P.scenario("edit UPPER_LENGTH 90->95", top)
    P.edit(root / "yaw_base.py", "default=90.0", "default=92.0")
    P.scenario("edit yaw_base BASE_D", top)
    P.edit(top, 'open_stroke", 3.0', 'open_stroke", 4.0')
    P.scenario("edit OPEN_STROKE (gripper)", top)
    if temporary is not None:
        temporary.cleanup()


if __name__ == "__main__":
    main()

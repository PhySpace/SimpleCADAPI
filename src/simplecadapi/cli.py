"""The single ``sca`` console script: the whole SimpleCADAPI command line.

Groups, each owned by its module and registered here at parser level so
``sca <group> --help`` works::

    sca init                      # machine setup: addon home + shell wiring
    sca addon add|update|remove|list|use
    sca skill targets|install
    sca export <package.scadpkg> [--format ...]
    sca run <notebook.py> [--set NAME=VALUE] [--out ...]

Shared contract: group handlers return ``(report, exit_code)`` and are
followed by the group's own printer (human-readable for init/addon, JSON
for export and run); errors print one ``sca: ...`` line to stderr and exit 2.
The historical ``simplecad-export`` entry point is gone — the same
command lives here.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

from .addon import AddonError
from .addon.install import sca_version
from .skill.compiler import SkillBuildError


def build_parser() -> argparse.ArgumentParser:
    from .addon import cli as addon_cli
    from .exporter import cli as exporter_cli
    from .runtime import cli as runtime_cli
    from .skill import cli as skill_cli

    parser = argparse.ArgumentParser(
        prog="sca",
        description="SimpleCADAPI command line: setup, addons, skills, package "
        "export, notebook runs.",
    )
    parser.add_argument(
        "--version", action="version", version=f"sca {sca_version()}"
    )
    subparsers = parser.add_subparsers(dest="group", required=True)
    addon_cli.configure(subparsers)
    exporter_cli.configure(subparsers)
    runtime_cli.configure(subparsers)
    skill_cli.configure(subparsers)
    return parser


def run(argv: Sequence[str] | None = None) -> tuple[dict[str, Any], int, Any]:
    """Parse and dispatch; return ``(report, exit_code, printer)``."""
    args = build_parser().parse_args(argv)
    report, exit_code = args.handler(args)
    return report, exit_code, args.printer


def main(argv: Sequence[str] | None = None) -> int:
    try:
        report, exit_code, printer = run(argv)
    except (AddonError, SkillBuildError, OSError, ValueError) as exc:
        print(f"sca: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    printer(report)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

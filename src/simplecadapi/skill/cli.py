"""The ``sca skill`` command group."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..addon.home import resolve_paths
from .runtime import build_skill, bundled_project


def configure(subparsers: argparse._SubParsersAction) -> None:
    skill = subparsers.add_parser(
        "skill", help="install the bundled Agent Skill for a harness"
    )
    commands = skill.add_subparsers(dest="command", required=True)
    commands.add_parser("targets", help="list supported harness targets")
    where = commands.add_parser(
        "where", help="print where `install` would put the skill (nothing is written)"
    )
    where.add_argument(
        "--skills-dir", type=Path,
        help="skills parent directory (default: config/env or ~/.agents/skills)",
    )
    install = commands.add_parser(
        "install", help="compile the bundled skill into <skills-dir>/<skill name>"
    )
    install.add_argument(
        "--target", required=True, help="harness target; see sca skill targets"
    )
    install.add_argument(
        "--skills-dir", type=Path,
        help="skills parent directory (default: config/env or ~/.agents/skills)",
    )
    install.add_argument(
        "--force", action="store_true",
        help="replace an existing install of this same skill",
    )
    skill.set_defaults(handler=_run, printer=_print)


def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    project = bundled_project()
    if args.command == "targets":
        return {"targets": list(project.targets)}, 0
    skills_dir = resolve_paths(skills_dir=args.skills_dir).skills_dir
    if args.command == "where":
        destination = skills_dir.expanduser().absolute() / project.name
        return {"where": str(destination), "exists": destination.exists()}, 0
    report = build_skill(
        project=project,
        target=args.target,
        output=skills_dir / project.name,
        force=args.force,
    )
    report["action"] = "install"
    return report, 0


def _print(report: dict[str, Any]) -> None:
    if "targets" in report:
        print("\n".join(report["targets"]))
    elif "where" in report:
        print(report["where"])
    else:
        print(
            f"installed {report['name']} for {report['target']}: "
            f"{report['files']} files -> {report['output']}"
        )

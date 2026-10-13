"""The ``sca example`` command (see :mod:`simplecadapi.cli`).

::

    sca example                 # list the examples
    sca example u_link [DIR]    # copy one out, ready for ``sca edit``
"""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path
from typing import Any

from .runtime import EXAMPLES, copy_example, example_names


def configure(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "example",
        help="copy a bundled example workspace out to open in the editor",
        description="Copy a bundled example (a directory of SimpleCAD notebooks) into DIR "
        "(default: ./<example directory>), then open it with `sca edit`.  Without a name, "
        "list the examples.  An existing directory is never overwritten.",
    )
    parser.add_argument("name", nargs="?", choices=example_names(), help="the example to copy")
    parser.add_argument("directory", nargs="?", type=Path, help="where to copy it to")
    parser.set_defaults(handler=_run, printer=_print)


def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.name is None:
        return {"examples": {name: EXAMPLES[name].summary for name in example_names()}}, 0
    target = copy_example(args.name, args.directory)
    example = EXAMPLES[args.name]
    opened = (target / example.open_with).resolve()
    return {
        "name": args.name,
        "path": str(target),
        "files": sorted(path.name for path in target.iterdir()),
        "edit": f"sca edit {shlex.quote(str(opened))}",
    }, 0


def _print(report: dict[str, Any]) -> None:
    if "examples" in report:
        for name, summary in report["examples"].items():
            print(f"{name}\t{summary}")
        return
    print(f"copied {report['name']} to {report['path']} ({len(report['files'])} files)")
    print(f"open it:  {report['edit']}")

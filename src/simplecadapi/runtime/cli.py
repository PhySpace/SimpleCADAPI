"""The ``sca run`` command (see :mod:`simplecadapi.cli`).

::

    sca run bracket.py                        # run, report the definition
    sca run bracket.py --set width=20         # override a top-level variable
    sca run link_bar.py --id crank            # run one member of a part family
    sca run bracket.py --out bracket.scadpkg  # also write the product package
    sca run bracket.py --no-cache             # ignore the cell cache

The report is one JSON object on stdout.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any, Sequence

from ..product.packages import build_product_package, encode_product_package
from .runner import run_notebook


def configure(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``run`` group on a parent subparsers action."""

    parser = subparsers.add_parser(
        "run",
        help="run a SimpleCAD notebook and build its product definition",
        description="Run a SimpleCAD notebook headlessly, with the cell cache.",
    )
    parser.add_argument("notebook", type=Path, help="marimo notebook (.py)")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        dest="overrides",
        metavar="NAME=VALUE",
        help="override a top-level variable; VALUE is a Python literal, "
        "else a string; may be repeated",
    )
    parser.add_argument(
        "--id",
        dest="run_id",
        metavar="ID",
        help="replace the notebook's id for this run (a part family member)",
    )
    parser.add_argument("--no-cache", action="store_true", help="run every cell")
    parser.add_argument("--out", type=Path, help="write the product package here")
    parser.set_defaults(handler=_execute, printer=_print_report)


def parse_overrides(items: Sequence[str]) -> dict[str, Any]:
    """Parse ``NAME=VALUE`` items; ``VALUE`` is a literal or else a string."""

    overrides: dict[str, Any] = {}
    for item in items:
        name, separator, raw = item.partition("=")
        name = name.strip()
        if not separator or not name.isidentifier():
            raise ValueError(f"--set expects NAME=VALUE, got {item!r}")
        if name in overrides:
            raise ValueError(f"--set {name} given twice")
        try:
            overrides[name] = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            overrides[name] = raw
    return overrides


def _execute(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    run = run_notebook(
        args.notebook,
        id=args.run_id,
        overrides=parse_overrides(args.overrides),
        cache=not args.no_cache,
    )
    definition = run.definition
    report: dict[str, Any] = {
        "notebook": str(run.config.path),
        "definition_id": definition.definition_id,
        "definition_kind": definition.definition_kind,
        "revision": definition.revision,
        "content_hash": definition.content_hash,
        "cells": [
            {"name": cell.name, "key": cell.key, "status": cell.status}
            for cell in run.cells
        ],
    }
    if args.out is not None:
        payload = encode_product_package(build_product_package(definition))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(payload)
        report["package"] = str(args.out)
    return report, 0


def _print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, sort_keys=True))


__all__ = ["configure", "parse_overrides"]

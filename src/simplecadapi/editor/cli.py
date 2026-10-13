"""The ``sca edit`` command (see :mod:`simplecadapi.cli`).

::

    sca edit [WORKSPACE]            # open the editor on a directory of notebooks
    sca edit path/to/model.py       # ... starting at one notebook
    sca edit --port 7180 --no-browser
    sca snapshot [WORKSPACE]        # what the person has selected / is looking at
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

DEFAULT_PORT = 7180


def configure(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "edit",
        help="open the web editor on a workspace of SimpleCAD notebooks",
        description="Serve the code-first CAD editor for WORKSPACE (default: the "
        "current directory): a directory of notebooks with [tool.simplecadapi] "
        "headers, or one such notebook.  Needs the 'editor' extra.",
    )
    parser.add_argument("workspace", type=Path, nargs="?", default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    parser.set_defaults(handler=_execute, printer=lambda report: None)

    snapshot = subparsers.add_parser(
        "snapshot",
        help="print what the editor user has selected and is looking at",
        description="Print the editor's snapshot for WORKSPACE (default: the current "
        "directory) as JSON: the selection (the ql code is in the notebook's selection "
        "cell, saved in the file), the cells' state and errors, the parameter values, and "
        "the path of the viewport image (a PNG an agent can look at).  The editor keeps "
        "it in WORKSPACE/.sca-editor/ while it runs.",
    )
    snapshot.add_argument("workspace", type=Path, nargs="?", default=Path.cwd())
    snapshot.set_defaults(handler=_snapshot, printer=_print_snapshot)


def _execute(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    try:
        from .server import serve_workspace
    except ModuleNotFoundError as error:
        raise ValueError(
            f"the editor needs the 'editor' extra ({error.name} is missing): "
            'pip install "simplecadapi[editor]"'
        ) from error
    target = args.workspace.expanduser().resolve()
    notebook = None
    if target.is_file():
        notebook, target = target, target.parent
    elif not target.is_dir():
        raise ValueError(f"{args.workspace}: no such file or directory")
    code = serve_workspace(
        target,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        notebook=notebook,
    )
    return {}, code


def _snapshot(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    import json

    root = args.workspace.expanduser().resolve()
    if root.is_file():
        root = root.parent
    path = root / ".sca-editor" / "snapshot.json"
    if not path.is_file():
        raise ValueError(f"{root}: no editor snapshot; is `sca edit` running on this workspace?")
    return json.loads(path.read_text(encoding="utf-8")), 0


def _print_snapshot(report: dict[str, Any]) -> None:
    import json

    print(json.dumps(report, indent=2, ensure_ascii=False))


__all__ = ["configure"]

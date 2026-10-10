"""The ``sca edit`` command (see :mod:`simplecadapi.cli`).

::

    sca edit [WORKSPACE]            # open the editor on a directory of notebooks
    sca edit path/to/model.py       # ... starting at one notebook
    sca edit --port 7180 --no-browser
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


__all__ = ["configure"]

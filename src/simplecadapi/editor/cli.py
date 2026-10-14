"""The ``sca edit`` command (see :mod:`simplecadapi.cli`).

::

    sca edit [WORKSPACE]            # open the editor on a directory of notebooks
    sca edit path/to/model.py       # ... starting at one notebook
    sca edit --port 7180 --no-browser
    sca snapshot [WORKSPACE]        # what the person has selected / is looking at
    sca cell ls|get|put|insert|rm|run   # edit the cells of the notebook the editor has open
    sca new NAME [--kind part|assembly] # a new notebook; the editor lists it at once
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

    cell = subparsers.add_parser(
        "cell",
        help="read and edit the cells of a notebook through the running editor",
        description="Edit a notebook's cells through the editor that has it open: the page "
        "shows the change live (no reload) and the editor, the one writer of the file, saves "
        "it, so nothing is overwritten.  Cells are named by number (see `sca cell ls`), by key "
        "or by id.  When the editor is not running, or has another notebook open, `ls` and "
        "`get` read the file and the write commands refuse: edit the file directly then, "
        "nothing else holds it.",
    )
    cell_sub = cell.add_subparsers(dest="cell_command", required=True)

    def common(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--notebook", "-n", type=Path, default=None, help="the notebook (default: the one the editor has open)")
        parser.add_argument("--workspace", "-w", type=Path, default=None, help="the workspace the editor serves (default: found from the current directory)")

    ls = cell_sub.add_parser("ls", help="list the cells with their state")
    common(ls)
    ls.add_argument("--code", action="store_true", help="include each cell's code")
    ls.set_defaults(handler=_cell_ls, printer=_print_json)
    get = cell_sub.add_parser("get", help="print one cell: its code, state, errors and output")
    common(get)
    get.add_argument("cell")
    get.set_defaults(handler=_cell_get, printer=_print_json)
    put = cell_sub.add_parser("put", help="replace a cell's code (the code comes from --file or stdin) and run it")
    common(put)
    put.add_argument("cell")
    put.add_argument("--file", "-f", type=Path, default=None, help="read the code from this file (default: stdin)")
    put.add_argument("--no-run", action="store_true", help="save the code without running the cell")
    put.set_defaults(handler=_cell_put, printer=_print_json)
    insert = cell_sub.add_parser("insert", help="add a cell (the code comes from --file or stdin)")
    common(insert)
    insert.add_argument("--after", default="end", help="a cell, or `start` / `end` (default)")
    insert.add_argument("--name", default=None, help="the cell's function name")
    insert.add_argument("--file", "-f", type=Path, default=None)
    insert.add_argument("--no-run", action="store_true")
    insert.set_defaults(handler=_cell_insert, printer=_print_json)
    rm = cell_sub.add_parser("rm", help="delete a cell")
    common(rm)
    rm.add_argument("cell")
    rm.set_defaults(handler=_cell_rm, printer=_print_json)
    run = cell_sub.add_parser("run", help="run cells (default: all) and what they feed")
    common(run)
    run.add_argument("cells", nargs="*")
    run.set_defaults(handler=_cell_run, printer=_print_json)

    new = subparsers.add_parser(
        "new",
        help="create a notebook in the workspace (the running editor lists it at once)",
        description="Write a new notebook from the template into WORKSPACE (default: the "
        "current directory).  A running editor on that workspace lists it without a reload.",
    )
    new.add_argument("name")
    new.add_argument("--kind", choices=("part", "assembly"), default="part")
    new.add_argument("--workspace", "-w", type=Path, default=None)
    new.set_defaults(handler=_new_notebook, printer=_print_json)


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


# -- sca cell / sca new ---------------------------------------------------------


def _print_json(report: dict[str, Any]) -> None:
    import json

    print(json.dumps(report, indent=2, ensure_ascii=False))


def _find_editor(start: Path) -> tuple[Path, str] | None:
    """The running editor whose workspace holds *start*: ``(workspace, base url)``."""
    import json
    import urllib.request

    here = start.expanduser().resolve()
    for directory in (here, *here.parents):
        record = directory / ".sca-editor" / "server.json"
        if not record.is_file():
            continue
        try:
            url = json.loads(record.read_text(encoding="utf-8"))["url"]
            with urllib.request.urlopen(f"{url}/api/health", timeout=1.5):
                pass
        except (OSError, ValueError, KeyError):
            continue  # a stale record: the editor is gone
        return directory, str(url)
    return None


def _call(url: str, path: str, body: dict | None = None) -> dict[str, Any]:
    import json
    import urllib.error
    import urllib.request

    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url + path, data=data, headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read())
        except ValueError:
            return {"error": f"editor answered {error.code}"}


def _session(args: argparse.Namespace, *, write: bool) -> tuple[str | None, Path | None, str]:
    """``(editor url or None, notebook path or None, relative notebook name)`` for a cell command."""
    start = args.workspace or (args.notebook.parent if args.notebook else Path.cwd())
    found = _find_editor(start)
    notebook = args.notebook.expanduser().resolve() if args.notebook else None
    if found is None:
        if write:
            raise ValueError(
                "no editor is running on this workspace (start `sca edit`), or edit the notebook file "
                "directly: nothing else holds it"
            )
        if notebook is None:
            raise ValueError("no editor is running here; name the notebook with --notebook")
        return None, notebook, notebook.name
    workspace, url = found
    open_path = _call(url, "/api/cells").get("notebook")
    if notebook is None:
        if open_path is None:
            raise ValueError("the editor has no notebook open")
        return url, workspace / open_path, open_path
    relative = notebook.relative_to(workspace).as_posix() if notebook.is_relative_to(workspace) else notebook.name
    if relative == open_path:
        return url, notebook, relative
    if write:
        raise ValueError(
            f"the editor has {open_path} open, not {relative}: edit {relative} directly "
            "(the editor does not hold it), or open it in the editor first"
        )
    return None, notebook, relative


def _cells_from_file(notebook: Path) -> list[dict[str, Any]]:
    from ..runtime._marimo import parse_notebook

    parsed = parse_notebook(notebook.read_text(encoding="utf-8"))
    cells = []
    for cell in (parsed.cells if parsed is not None else []):
        if getattr(cell, "name", None) == "setup":
            continue
        cells.append({"index": len(cells) + 1, "name": getattr(cell, "name", None), "code": cell.code, "source": "file"})
    return cells


def _slim(report: dict[str, Any], *, code: bool) -> dict[str, Any]:
    if "cells" not in report:
        return report
    keep = ("index", "key", "name", "title", "status", "errors", "output", "ref", "readonly")
    return {
        **report,
        "cells": [
            {**{k: c[k] for k in keep if k in c and c[k] not in (None, [], False)}, **({"code": c["code"]} if code else {})}
            for c in report["cells"]
        ],
    }


def _cell_ls(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    url, notebook, name = _session(args, write=False)
    if url is None:
        assert notebook is not None
        return {"notebook": name, "source": "file", "cells": _cells_from_file(notebook)}, 0
    return _slim(_call(url, "/api/cells"), code=args.code), 0


def _cell_get(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    url, notebook, name = _session(args, write=False)
    if url is None:
        assert notebook is not None
        cells = _cells_from_file(notebook)
        if not args.cell.isdigit() or not 1 <= int(args.cell) <= len(cells):
            raise ValueError("without the editor, name a cell by its number (see `sca cell ls`)")
        return {"notebook": name, "source": "file", **cells[int(args.cell) - 1]}, 0
    report = _call(url, "/api/cells")
    for cell in report.get("cells", []):
        if args.cell in (str(cell["index"]), cell.get("key"), cell["id"]):
            return {"notebook": report.get("notebook"), **cell}, 0
    raise ValueError(f"no cell {args.cell!r}; run `sca cell ls`")


def _read_code(args: argparse.Namespace) -> str:
    import sys

    if args.file is not None:
        return args.file.read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise ValueError("give the code with --file, or on stdin")
    return sys.stdin.read()


def _write_op(args: argparse.Namespace, op: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    url, _notebook, _name = _session(args, write=True)
    assert url is not None
    report = _call(url, f"/api/cells/{op}", body)
    if "error" in report:
        return _slim(report, code=False), 1
    touched = set(report.get("touched", []))
    report = _slim(report, code=False)
    # What the change did: the touched cells with their state; the rest as a count.
    report["cells"] = [c for c in report["cells"] if c.get("index") in touched] or report["cells"]
    return report, 0


def _cell_put(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    return _write_op(args, "edit", {"cell": args.cell, "code": _read_code(args), "run": not args.no_run})


def _cell_insert(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    return _write_op(args, "insert", {"after": args.after, "name": args.name, "code": _read_code(args), "run": not args.no_run})


def _cell_rm(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    return _write_op(args, "delete", {"cell": args.cell})


def _cell_run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    return _write_op(args, "run", {"cells": args.cells})


def _new_notebook(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from .templates import create_notebook

    start = (args.workspace or Path.cwd()).expanduser().resolve()
    found = _find_editor(start)
    root = found[0] if found is not None else start
    # Only the file is written: the running editor lists it on its own and the
    # person's current notebook stays open.
    path = create_notebook(root, args.name, args.kind)
    return {"ok": True, "path": str(path), "editor_listed": found is not None}, 0


__all__ = ["configure"]

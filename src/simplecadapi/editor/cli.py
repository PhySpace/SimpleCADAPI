"""The ``sca edit`` command (see :mod:`simplecadapi.cli`).

::

    sca edit [WORKSPACE]            # open the editor on a directory of notebooks
    sca edit path/to/model.py       # ... starting at one notebook
    sca edit --port 7180 --no-browser
    sca snapshot [WORKSPACE]        # what the person has selected / is looking at
    sca viewport [WORKSPACE] [--out PATH]  # the image of what the person sees
    sca cell ls|get|put|insert|rm|run   # edit the cells of the notebook the editor has open
    sca cell open NOTEBOOK [--wait S]   # have the editor open another notebook
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

    viewport = subparsers.add_parser(
        "viewport",
        help="the image of what the editor user sees, to look at or copy out",
        description="Locate the editor's viewport image (the PNG of what the person sees, "
        "kept in WORKSPACE/.sca-editor/ while the editor runs), tell its path, age and "
        "size, and with --out copy it somewhere an agent's image reader reaches.  A stale "
        "age means the page has not redrawn since then; there is no image until the page "
        "showed a model at least once.",
    )
    viewport.add_argument("workspace", type=Path, nargs="?", default=Path.cwd())
    viewport.add_argument("--out", type=Path, default=None, help="copy the PNG to this path")
    viewport.set_defaults(handler=_viewport, printer=_print_json)

    cell = subparsers.add_parser(
        "cell",
        help="read and edit the cells of a notebook through the running editor",
        description="Edit a notebook's cells through the editor that has it open: the page "
        "shows the change live (no reload) and the editor, the one writer of the file, saves "
        "it, so nothing is overwritten.  Cells are named by number (see `sca cell ls`), by key "
        "or by id.  When the editor is not running, or has another notebook open, `ls` and "
        "`get` read the file and the write commands refuse: `sca cell open NOTEBOOK` switches "
        "(or pass --open to switch and write in one step), or edit the file directly then — "
        "nothing else holds it.",
    )
    cell_sub = cell.add_subparsers(dest="cell_command", required=True)

    def common(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--notebook", "-n", type=Path, default=None, help="the notebook (default: the one the editor has open)")
        parser.add_argument("--workspace", "-w", type=Path, default=None, help="the workspace the editor serves (default: found from the current directory)")

    def writable(parser: argparse.ArgumentParser) -> None:
        common(parser)
        parser.add_argument(
            "--open", action="store_true",
            help="when the editor has another notebook open, open this one first "
            "(the editor switches and the notebook's kernel restarts)",
        )
        parser.add_argument(
            "--wait", type=float, default=None,
            help="seconds to wait for a notebook opened by --open to be ready "
            "(default: SCA_EDITOR_OPEN_WAIT or 120)",
        )

    ls = cell_sub.add_parser("ls", help="list the cells with their state")
    common(ls)
    ls.add_argument("--code", action="store_true", help="include each cell's code")
    ls.set_defaults(handler=_cell_ls, printer=_print_json)
    get = cell_sub.add_parser("get", help="print one cell: its code, state, errors and output")
    common(get)
    get.add_argument("cell")
    get.set_defaults(handler=_cell_get, printer=_print_json)
    put = cell_sub.add_parser("put", help="replace a cell's code (the code comes from --file or stdin) and run it")
    writable(put)
    put.add_argument("cell")
    put.add_argument("--file", "-f", type=Path, default=None, help="read the code from this file (default: stdin)")
    put.add_argument("--no-run", action="store_true", help="save the code without running the cell")
    put.set_defaults(handler=_cell_put, printer=_print_json)
    insert = cell_sub.add_parser("insert", help="add a cell (the code comes from --file or stdin)")
    writable(insert)
    insert.add_argument("--after", default="end", help="a cell, or `start` / `end` (default)")
    insert.add_argument("--name", default=None, help="the cell's function name")
    insert.add_argument("--file", "-f", type=Path, default=None)
    insert.add_argument("--no-run", action="store_true")
    insert.set_defaults(handler=_cell_insert, printer=_print_json)
    rm = cell_sub.add_parser("rm", help="delete a cell")
    writable(rm)
    rm.add_argument("cell")
    rm.set_defaults(handler=_cell_rm, printer=_print_json)
    run = cell_sub.add_parser("run", help="run cells (default: all) and what they feed")
    writable(run)
    run.add_argument("cells", nargs="*")
    run.set_defaults(handler=_cell_run, printer=_print_json)
    open_ = cell_sub.add_parser(
        "open",
        help="have the running editor open another notebook of this workspace",
        description="Switch the editor to NOTEBOOK: the page shows it at once and its "
        "kernel restarts, so `sca cell` writes go to it.  Waits until the kernel is "
        "up so a following write does not race the boot.",
    )
    open_.add_argument("notebook", type=Path, help="the notebook file (workspace-relative, or absolute inside the workspace)")
    open_.add_argument("--workspace", "-w", type=Path, default=None, help="the workspace the editor serves (default: found from the current directory)")
    open_.add_argument("--wait", type=float, default=None, help="seconds to wait for the notebook's kernel (default: SCA_EDITOR_OPEN_WAIT or 120)")
    open_.set_defaults(handler=_cell_open, printer=_print_json)

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


def _viewport(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    import time

    root = args.workspace.expanduser().resolve()
    if root.is_file():
        root = root.parent
    png = root / ".sca-editor" / "viewport.png"
    if not png.is_file():
        # The record knows the editor's workspace even when this directory is
        # one of its children; the image the person sees lives next to it.
        found = _find_editor(root)
        if found is not None:
            png = found[0] / ".sca-editor" / "viewport.png"
    if not png.is_file():
        raise ValueError(
            f"{root}: no viewport image; is `sca edit` running with the page showing a model?"
        )
    stat = png.stat()
    report: dict[str, Any] = {
        "path": str(png),
        "bytes": stat.st_size,
        "age_seconds": round(time.time() - stat.st_mtime, 1),
    }
    if args.out is not None:
        target = args.out.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(png.read_bytes())
        report["copied_to"] = str(target)
    return report, 0


# -- sca cell / sca new ---------------------------------------------------------


def _print_json(report: dict[str, Any]) -> None:
    import json

    print(json.dumps(report, indent=2, ensure_ascii=False))


def _opener() -> Any:
    """An opener that bypasses the proxy environment for the local editor.

    The editor is on this machine (its url is 127.0.0.1); a container's
    ``http_proxy`` does not know that and swallows the request, which once
    read as "no editor is running" while one was.
    """
    import urllib.request

    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _find_editor(start: Path) -> tuple[Path, str] | None:
    """The running editor whose workspace holds *start*: ``(workspace, base url)``.

    A record whose server does not answer is an error, not a stale record to
    skip quietly: "an editor was running here" is exactly the belief that
    must not be dropped in silence.  The one definite stale case is a record
    whose process is gone (a crashed editor leaves its server.json behind).
    """
    import json
    import os
    import urllib.error

    here = start.expanduser().resolve()
    unreachable: list[str] = []
    opener = _opener()
    for directory in (here, *here.parents):
        record = directory / ".sca-editor" / "server.json"
        if not record.is_file():
            continue
        try:
            body = json.loads(record.read_text(encoding="utf-8"))
            url = body["url"]
        except (OSError, ValueError, KeyError) as error:
            unreachable.append(f"{record}: unreadable ({error})")
            continue
        pid = body.get("pid")
        if isinstance(pid, int):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                unreachable.append(
                    f"stale record {record} (pid {pid} is gone); delete it or restart the editor"
                )
                continue
            except OSError:
                pass  # a live process we cannot signal
        try:
            with opener.open(f"{url}/api/health", timeout=1.5):
                pass
        except urllib.error.HTTPError:
            pass  # an editor that answers at all is running
        except OSError as error:
            unreachable.append(f"found {record} but {url} is unreachable: {error}")
            continue
        return directory, str(url)
    if unreachable:
        raise ValueError("; ".join(unreachable))
    return None


def _call_timeout() -> float:
    """How long one editor call may take; a heavy downstream rerun is on the
    clock of the write that triggered it. ``SCA_EDITOR_CALL_TIMEOUT`` seconds."""
    import os

    return float(os.environ.get("SCA_EDITOR_CALL_TIMEOUT", "300"))


def _call(url: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict[str, Any]:
    import json
    import socket
    import urllib.error
    import urllib.request

    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url + path, data=data, headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST"
    )
    seconds = _call_timeout() if timeout is None else timeout
    try:
        with _opener().open(request, timeout=seconds) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read())
        except ValueError:
            return {"error": f"editor answered {error.code}"}
    except (socket.timeout, TimeoutError) as error:
        raise TimeoutError(f"the editor did not answer {path} within {seconds:g}s") from error


def _open_wait_seconds(wait: float | None) -> float:
    """How long to wait for a switched notebook's kernel; ``--wait`` or
    ``SCA_EDITOR_OPEN_WAIT`` seconds (a marimo boot takes a few)."""
    import os

    return float(os.environ.get("SCA_EDITOR_OPEN_WAIT", "120")) if wait is None else float(wait)


def _wait_open(url: str, relative: str, wait: float | None = None) -> dict[str, Any]:
    """Poll until the editor has *relative* open and its kernel is up.

    The switch itself lands in milliseconds; the kernel boot is the slow part,
    and a write sent into it reads as "no kernel yet".  Waiting here is what
    makes `sca cell open` a safe step before a write instead of a race.
    """
    import time

    seconds = _open_wait_seconds(wait)
    deadline = time.monotonic() + seconds
    while True:
        report = _call(url, "/api/cells")
        if report.get("notebook") == relative and report.get("kernel"):
            return {"ok": True, "open": relative}
        if time.monotonic() >= deadline:
            return {
                "ok": False,
                "error": f"the editor is still opening {relative} after {seconds:g}s "
                "(the switch was asked for; check `sca cell ls`; "
                "SCA_EDITOR_OPEN_WAIT or --wait raises the time)",
            }
        time.sleep(0.25)


def _open_notebook(url: str, relative: str, wait: float | None = None) -> dict[str, Any]:
    """Ask the editor to open *relative* and wait until it is writable."""
    current = _call(url, "/api/cells")
    if current.get("notebook") == relative and current.get("kernel"):
        return {"ok": True, "open": relative, "already": True}
    report = _call(url, "/api/workspace/open", {"path": relative})
    if not report.get("ok"):
        return report
    return _wait_open(url, relative, wait)


def _cell_open(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    start = (args.workspace or Path.cwd()).expanduser().resolve()
    found = _find_editor(start)
    if found is None:
        raise ValueError("no editor is running on this workspace (start `sca edit`)")
    workspace, url = found
    notebook = args.notebook.expanduser().resolve()
    if not notebook.is_relative_to(workspace):
        raise ValueError(f"{args.notebook} is not in the editor's workspace ({workspace})")
    report = _open_notebook(url, notebook.relative_to(workspace).as_posix(), wait=args.wait)
    return report, 0 if report.get("ok") else 1


def _session(args: argparse.Namespace, *, write: bool) -> tuple[str | None, Path | None, str]:
    """``(editor url or None, notebook path or None, relative notebook name)`` for a cell command."""
    start = args.workspace or (args.notebook.parent if args.notebook else Path.cwd())
    try:
        found = _find_editor(start)
    except ValueError as error:
        if write:
            raise
        _warn(f"editor not reached: {error}")
        found = None
    notebook = args.notebook.expanduser().resolve() if args.notebook else None
    if found is None:
        if write:
            raise ValueError(
                "no editor is running on this workspace (start `sca edit`), or edit the notebook file "
                "directly: nothing else holds it"
            )
        if notebook is None:
            raise ValueError("no editor is running here; name the notebook with --notebook")
        _warn(f"no editor is running on this workspace; reading the file: {notebook.name}")
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
        if getattr(args, "open", False):
            report = _open_notebook(url, relative, wait=getattr(args, "wait", None))
            if report.get("ok"):
                return url, workspace / relative, relative
            raise ValueError(report.get("error") or f"could not open {relative} in the editor")
        raise ValueError(
            f"the editor has {open_path} open, not {relative}: run `sca cell open {relative}` "
            f"(or pass --open to switch and write in one step), or edit {relative} directly "
            "— nothing else holds it"
        )
    _warn(f"the editor has {open_path} open; reading {relative} from the file")
    return None, notebook, relative


def _warn(message: str) -> None:
    """Say a fallback out loud: silence once read as "the editor agreed"."""
    import sys

    print(f"warning: {message}", file=sys.stderr)


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
    keep = ("index", "key", "name", "title", "status", "errors", "output", "console", "upstream", "ref", "readonly")
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
    try:
        report = _call(url, f"/api/cells/{op}", body)
    except TimeoutError:
        # The server took the write and reruns on its own; the clock that ran
        # out is this call's, not the editor's.
        return {
            "error": "the edit was applied and the rerun is still going; check "
            "`sca cell ls` (SCA_EDITOR_CALL_TIMEOUT raises the wait)"
        }, 1
    if "error" in report:
        return _slim(report, code=False), 1
    touched = set(report.get("touched", []))
    report = _slim(report, code=False)
    # What the change did: the touched cells with their state, plus any cell
    # that is not healthy after the run — a rerun dependent failing is the
    # feedback the edit was after, hiding it once read as "the edit was fine".
    report["cells"] = [
        c for c in report["cells"] if c.get("index") in touched or c.get("errors") or c.get("blocked")
    ] or report["cells"]
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

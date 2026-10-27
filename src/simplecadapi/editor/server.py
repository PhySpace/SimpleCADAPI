"""The editor server: webui static files + WS hub + the workspace's marimo kernel.

This is the ``sca edit <workspace>`` application.  The workspace is a plain
directory of SimpleCAD notebooks (:mod:`simplecadapi.runtime.workspace`).
The server hosts a marimo kernel for one notebook at a time
(:mod:`.kernel`); the kernel runs the notebook with the same executor
``sca run`` uses.  When the cells settle — whoever ran them — the server
asks the kernel for the product's package (``publish_live``), keeps the
bytes, and tells the webuis.  Commands from the webui are translated into
kernel cell operations; parameter values the webui sets are saved where the
kernel executor applies them (:mod:`simplecadapi.runtime.params`), so
marimo's own dataflow reruns exactly the cells that read them.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import re
import sys
import threading
import time
import webbrowser
from collections import OrderedDict
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from ..runtime.cells import cell_keys
from ..runtime.config import NotebookConfig, read_notebook_config
from ..runtime._marimo import compile_cell
from ..runtime.params import (
    ParamSpec,
    commit_field_value,
    commit_value,
    list_module_parameters,
    parameters_in_cell,
    read_saved_params,
    write_saved_params,
)
from ..runtime.deps import file_digest, input_files
from ..runtime.workspace import features_in_cell, notebook_modules, scan_modules, scan_workspace
from .kernel import MarimoKernel
from .selection import MARKER, selection_cell_code, variable_names
from .templates import create_notebook
from .ws import WsHub


def _webui_dir() -> Path:
    """The built webui: ``editor-web`` builds into the package directory
    (``npm run build``), and the wheel ships it from there."""
    return Path(__file__).resolve().parent / "webui"


DIST_DIR = _webui_dir()


def pick_notebook(workspace: Path, prefer: Path | None = None) -> Path | None:
    """The notebook to open first: the one asked for, else the product.

    Without a request that is the first assembly nothing else uses (the
    top of the product), else the first notebook.
    """
    if prefer is not None and prefer.is_file():
        return prefer.resolve()
    entries = scan_workspace(workspace)
    if not entries:
        return None
    used = {use for entry in entries for use in entry.uses}
    tops = [e for e in entries if e.kind == "assembly" and e.path not in used]
    chosen = (tops or entries)[0]
    return (workspace / chosen.path).resolve()


class WorkspaceState:
    """Shared server state: hub + kernel + workspace info + latest envelopes.

    A webui that connects (or refreshes) later must still see the current
    model, so the latest envelope per type is cached and replayed.

    Parameter bursts collapse: while one rebuild is in flight, newer values
    accumulate in ``_pending_params`` and exactly one follow-up rebuild runs
    with the merged latest values ("latest wins").
    """

    # Envelope types worth replaying, in replay order.  "preview" is a light
    # revision event; the bytes themselves live on /api/package/latest.
    _REPLAYED = (
        "module",
        "notebook.cells",
        "notebook.features",
        "params.schema",
        "params.values",
        "preview",
        "selection",
    )

    def __init__(self, workspace: Path, notebook: Path | None = None) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.hub = WsHub()
        self.kernel: MarimoKernel | None = None
        self.notebook: Path | None = pick_notebook(self.workspace, notebook)
        self.port = 0
        self.lock = threading.Lock()
        self.latest: dict[str, dict] = {}
        self.latest_package_bytes: bytes | None = None  # a full package, made on demand (export)
        self.latest_preview_bytes: bytes | None = None
        self.preview_revision = 0
        self._package_event = threading.Event()
        self.selection: dict = {}
        self.selection_items: list[dict] = []
        self.viewport_png: bytes | None = None
        self.cells: list[dict] = []
        self.specs: dict[str, ParamSpec] = {}
        self._pending_params: dict[str, float | int | bool] = {}
        self._rebuild_inflight = False
        self._rebuild_cond = threading.Condition()
        # One rebuild per interval; later slider batches keep merging.
        self._rebuild_min_interval = 0.35
        self._last_rebuild_at = 0.0
        self._watched: dict[Path, int] = {}
        self.module_path: Path | None = None
        self._pending_modules: dict[tuple[str, str], float | int | bool] = {}
        self._module_dirty: set[Path] = set()
        self._module_busy = False
        self._module_lock = threading.Lock()
        self._packages: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
        self._publish_signature: str | None = None
        self._stopped = False
        self._selection_code: str | None = None
        self._selection_busy = False
        self._selection_lock = threading.Lock()
        self._settle_timer: threading.Timer | None = None
        self._settle_lock = threading.Lock()
        self._settle_dirty = True  # a run ended (or the notebook just opened) since the last settle
        self._last_publish_error = ""
        self._generation = 0
        self._switch_lock = threading.Lock()
        self._booting: MarimoKernel | None = None
        self._setup_code: str | None = None
        self._edited_from: dict[str, set[str]] = {}
        self._shutdown = threading.Event()

    # -- notebook / kernel lifecycle ---------------------------------------------

    @property
    def config(self) -> NotebookConfig | None:
        return read_notebook_config(self.notebook) if self.notebook else None

    def open_notebook(self, rel_path: str, generation: int | None = None) -> None:
        """Switch the active notebook: restart the kernel on it.

        Runs synchronously (the caller wraps it in a thread): marimo boot
        takes seconds.  If nothing the notebook depends on changed since its
        model was last published, that model and the notebook's cells are shown
        at once, while the kernel boots.
        """
        target = self.resolve_notebook(rel_path)
        if generation is None:
            generation = self.reserve_switch()
            self.announce_opening(target)
        if not self._begin_switch(target, generation):
            return  # a later open was asked for meanwhile
        restored = self._restore(target, generation)
        self.start_kernel(target, restored=restored, generation=generation)

    def resolve_notebook(self, rel_path: str) -> Path:
        """The file of the workspace notebook *rel_path*; ``ValueError`` if it is none."""
        target = (self.workspace / rel_path).resolve()
        if not target.is_file() or self.workspace not in target.parents:
            raise ValueError(f"notebook outside workspace: {rel_path}")
        if read_notebook_config(target) is None:
            raise ValueError(f"not a SimpleCAD notebook (no [tool.simplecadapi]): {rel_path}")
        return target

    def announce_opening(self, target: Path) -> None:
        """Tell the webuis a notebook is being opened (they show it at once)."""
        self.hub.broadcast(
            {"type": "opening", "notebook": target.name, "path": target.relative_to(self.workspace).as_posix()}
        )

    def reserve_switch(self) -> int:
        """Take the next place in the order of opens.

        Taken where a request arrives, so that a later click wins however the
        threads that carry the opens out happen to be scheduled.
        """
        with self._switch_lock:
            self._generation += 1
            return self._generation

    def _begin_switch(self, target: Path, generation: int) -> bool:
        """Make *target* the notebook being opened, superseding any open in flight.

        The list of notebooks shows it as the current one from now on, not
        once its kernel is up; whatever an older open is still doing (booting a
        kernel, publishing) is cancelled: it notices it was superseded.
        """
        with self._switch_lock:
            if generation != self._generation:
                return False
            self.notebook = target
            # Let the webuis drop the old model now; commands have no kernel until the new one is up.
            self.latest.clear()
            self.latest_preview_bytes = None
            self._drop_kernel()
        return True

    def _superseded(self, generation: int) -> bool:
        return generation != self._generation

    def _drop_kernel(self) -> None:
        with self.lock:
            old, self.kernel = self.kernel, None
            booting, self._booting = self._booting, None
        for kernel in (old, booting):
            if kernel is not None:
                kernel.stop()

    def start_kernel(self, notebook: Path, *, restored: bool = False, generation: int | None = None) -> None:
        """Boot a marimo kernel for *notebook*, adopt it, and publish its product.

        Shared by server boot, open_notebook, and the auto-heal watch.  With
        *restored* the notebook's last model and cells are already on screen.
        An open that is superseded while it boots (the person opened another
        notebook meanwhile) ends quietly: its kernel is stopped, nothing is shown.
        """
        if generation is None:
            generation = self.reserve_switch()
            if not self._begin_switch(notebook, generation):
                return
            restored = self._restore(notebook, generation)
        kernel = MarimoKernel(
            notebook,
            server_port=self.port,
            on_run_complete=lambda: self._superseded(generation) or self.schedule_settle(),
            on_cell_status=lambda cell_id, status: self._superseded(generation) or self.cell_status(cell_id, status),
        )
        with self.lock:
            if self._superseded(generation):
                return
            self._booting = kernel
        try:
            kernel.start()
            with self.lock:
                if self._superseded(generation):
                    kernel.stop()
                    return
                self._booting = None
                self.kernel = kernel
            # Envelopes from the previous model must not replay.
            self.selection = {}
            self.selection_items = []
            self.viewport_png = None
            self._last_publish_error = ""
            if not restored:
                self.latest.clear()
                self.latest_preview_bytes = None
                self.cells = []
                self.specs = {}
            self._watched = self._watched_files()[0]
            self._setup_code = _setup_code_of(notebook)
            self.hub.broadcast(self.hello())
            kernel.wait_instantiated()
            kernel.wait_idle()
            if self._superseded(generation):
                return
            self.settle()
        except Exception:
            kernel.stop()
            if self._superseded(generation):
                return  # its kernel was stopped under it; not an error
            raise
        threading.Thread(
            target=self._watch_files, args=(kernel,), name="file-watch", daemon=True
        ).start()
        threading.Thread(
            target=self._watch_notebook, args=(kernel,), name="notebook-watch", daemon=True
        ).start()

    # -- remembering what was published -----------------------------------------------

    def _signature(self, notebook: Path) -> str:
        """A digest of everything the notebook's model depends on.

        The notebook, the local modules it imports, the notebooks it runs and what
        they depend on, the data files they list, the values an editor saved, and the
        software versions: if it is the same as when a model was published, that
        model is the model.
        """
        import marimo

        from ..build.keys import generator_profile

        files, _own, _inputs = self._dependency_files(notebook)
        files.add(notebook)
        config = read_notebook_config(notebook)
        payload = {
            "files": {path.as_posix(): file_digest(path) for path in sorted(files)},
            "saved": read_saved_params(config) if config is not None else {},
            "generator": dict(generator_profile()),
            "marimo": marimo.__version__,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def _model_file(self, notebook: Path) -> Path:
        name = notebook.relative_to(self.workspace).as_posix().replace("/", "__")
        return self.snapshot_dir / "models" / f"{name}.scapreview"

    def remember_model(self, notebook: Path, signature: str, data: bytes) -> None:
        """Keep *data* (a preview) as the model of *notebook* for *signature*, in memory and on disk."""
        key = notebook.relative_to(self.workspace).as_posix()
        self._packages[key] = (signature, data)
        self._packages.move_to_end(key)
        while len(self._packages) > 6:
            self._packages.popitem(last=False)
        try:
            target = self._model_file(notebook)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.with_suffix(".sig").write_text(signature, encoding="utf-8")
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(target)
        except OSError as error:
            print(f"[sca edit] could not keep the model: {error}", file=sys.stderr)

    def _recall_model(self, notebook: Path, signature: str) -> bytes | None:
        key = notebook.relative_to(self.workspace).as_posix()
        known = self._packages.get(key)
        if known is not None and known[0] == signature:
            return known[1]
        target = self._model_file(notebook)
        try:
            if target.with_suffix(".sig").read_text(encoding="utf-8") == signature:
                return target.read_bytes()
        except OSError:
            pass
        return None

    def _restore(self, notebook: Path, generation: int | None = None) -> bool:
        """Show *notebook* from its last published model, if nothing it depends on changed.

        Its cells appear too, read from the file (not editable until the kernel is
        up); the kernel's own cells replace them, and its model replaces this one
        only if it differs.
        """
        try:
            data = self._recall_model(notebook, self._signature(notebook))
        except (OSError, ValueError):
            data = None
        if data is None or (generation is not None and self._superseded(generation)):
            return False
        self.notebook = notebook
        self._publish_cells(_static_cells(notebook))
        self.latest_preview_bytes = data
        self.preview_revision += 1
        self.emit(
            {
                "type": "preview",
                "revision": self.preview_revision,
                "step": notebook.stem,
                "name": notebook.stem,
                "size": len(data),
                "cached": True,
            }
        )
        self.hub.broadcast({"type": "status", "info": "restored from the last run; the kernel is starting…"})
        return True

    def watch_kernel(self) -> None:
        """Auto-heal: the marimo python session can die on crashes or
        external file edits while the marimo SERVER process stays alive
        (`kernel.alive` is blind to that).  Ask marimo whether it still has our
        session; two consecutive misses mean it is gone — restart.
        """
        failures = 0
        while True:
            time.sleep(5)
            kernel = self.kernel
            # Between kernels (a notebook is being opened) there is nothing to watch.
            if kernel is None or kernel._stop.is_set():
                failures = 0
                continue
            if not kernel.alive:
                self.hub.broadcast({"type": "status", "error": "marimo server exited — restarting kernel"})
            else:
                # Not a scratch snippet: one queued behind a long cell and given
                # up on interrupts the kernel (see MarimoKernel.execute).
                failures = 0 if kernel.session_exists() else failures + 1
                if failures < 2:
                    continue
                self.hub.broadcast({"type": "status", "error": "kernel session lost — restarting"})
            failures = 0
            try:
                assert self.notebook is not None
                self.start_kernel(self.notebook)
                self.hub.broadcast({"type": "status", "recovered": self.notebook.name})
            except Exception as exc:
                self.hub.broadcast({"type": "status", "error": f"kernel restart failed: {exc}"})

    # -- child notebooks ---------------------------------------------------------

    def _watched_files(self) -> tuple[dict[Path, int], set[Path], set[Path]]:
        """The files whose edit changes the open notebook, with their mtimes.

        Returns ``(mtimes, own_modules, own_inputs)``.  *own_modules* are the
        local modules the notebook itself imports: the kernel has them loaded,
        so a change needs a reload and a rerun of every cell.  *own_inputs* are
        the project files its header lists (``inputs``, data the cells read):
        nothing to reload, but any cell may read them, so every cell reruns.
        The rest are the notebooks it runs with ``use`` (and the modules and data
        those use) and the module open in the module view: ``use`` runs a child
        headless, outside the kernel's dataflow, so marimo never sees an edit to
        it; the editor does and reruns the cells that call ``use`` (the children's
        own cell cache, keyed by their files, decides what is rebuilt).
        """
        files: set[Path] = set()
        own: set[Path] = set()
        inputs: set[Path] = set()
        if self.notebook is not None:
            files, own, inputs = self._dependency_files(self.notebook)
        if self.module_path is not None:
            files.add(self.module_path)
        mtimes: dict[Path, int] = {}
        for path in files:
            try:
                mtimes[path] = path.stat().st_mtime_ns
            except OSError:
                mtimes[path] = 0
        return mtimes, own, inputs

    def _dependency_files(self, notebook: Path) -> tuple[set[Path], set[Path], set[Path]]:
        """What *notebook* depends on: ``(files, own_modules, own_inputs)``."""
        entries = {entry.path: entry for entry in scan_workspace(self.workspace)}
        start = notebook.relative_to(self.workspace).as_posix()
        own = set(notebook_modules(notebook).values())
        config = read_notebook_config(notebook)
        inputs = set(input_files(config)) if config is not None else set()
        files = own | inputs
        seen: set[str] = set()
        pending = list(entries[start].uses) if start in entries else []
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            if path in entries:
                pending.extend(entries[path].uses)
                files.update(self.workspace / module for module in entries[path].modules)
                child = read_notebook_config(self.workspace / path)
                if child is not None:
                    files |= set(input_files(child))
        files |= {self.workspace / path for path in seen}
        return files, own, inputs

    def _watch_files(self, kernel: MarimoKernel) -> None:
        while not kernel._stop.is_set():
            time.sleep(1.0)
            if self.kernel is not kernel:
                return
            try:
                current, _own, _inputs = self._watched_files()
                changed = {path for path, mtime in current.items() if self._watched.get(path) != mtime}
                changed |= {path for path in self._watched if path not in current}
                self._watched = current
                if changed:
                    self._files_changed(changed)
            except Exception as exc:
                self.hub.broadcast({"type": "status", "error": f"refresh failed: {str(exc)[-200:]}"})

    def _files_changed(self, paths: set[Path], *, announce: bool = True) -> None:
        """Files the notebook depends on changed: reload / rerun what reads them."""
        if announce and self.module_path in paths:
            self.emit_module("external")
        with self._module_lock:
            self._module_dirty |= paths
            if self._module_busy:
                return
            self._module_busy = True
        threading.Thread(target=self._propagate, name="propagate", daemon=True).start()

    # -- the notebook file changed under the editor ------------------------------

    def _watch_notebook(self, kernel: MarimoKernel) -> None:
        """Take in edits made to the open notebook's file by someone else (an agent).

        The kernel holds the notebook in memory and writes the file on every edit
        the editor makes, so an outside edit that the kernel never hears of would be
        written over by the editor's next save.  Poll the file; once it has been
        quiet for one tick, compare it with the kernel's cells (a change the editor
        itself made shows no difference) and apply what differs.
        """
        stamp = self._stamp(self.notebook)
        pending: tuple[int, int] | None = None
        while not kernel._stop.is_set():
            time.sleep(0.3)
            if self.kernel is not kernel:
                return
            current = self._stamp(self.notebook)
            if current != stamp:
                stamp, pending = current, current
                continue
            if pending is None:
                continue
            pending = None
            try:
                self.ingest_external(kernel)
            except Exception as exc:
                self.hub.broadcast({"type": "status", "error": f"could not take in the file change: {str(exc)[-200:]}"})

    @staticmethod
    def _stamp(path: Path | None) -> tuple[int, int]:
        try:
            assert path is not None
            info = path.stat()
            return info.st_mtime_ns, info.st_size
        except (OSError, AssertionError):
            return 0, 0

    def ingest_external(self, kernel: MarimoKernel) -> None:
        """Make the kernel's cells equal the notebook file's, changing only what differs.

        Cells that differ are edited, created or deleted in place (the page updates
        without a reload), then the cells that changed are run and what they feed
        turns fresh.  A change the cell commands cannot carry (the setup cell, an
        ``@app.function`` cell) restarts the kernel instead.
        """
        import difflib

        from ..runtime._marimo import parse_notebook

        notebook = self.notebook
        if notebook is None:
            return
        with kernel.write_lock:
            try:
                parsed = parse_notebook(notebook.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                return
            except SyntaxError as exc:
                self.hub.broadcast({"type": "status", "error": f"{notebook.name} has a syntax error ({exc.msg}, line {exc.lineno}); waiting for the next save"})
                return
            if parsed is None:
                return
            setup = next((c.code.strip() for c in parsed.cells if getattr(c, "name", None) == "setup"), "")
            if self._setup_code is not None and setup != self._setup_code:
                self.hub.broadcast({"type": "status", "working": "the setup cell changed on disk: restarting the kernel…"})
                self._in_thread(lambda: self.start_kernel(notebook))
                return
            disk = [
                (getattr(c, "name", None) or None, c.code)
                for c in parsed.cells
                if getattr(c, "name", None) != "setup"
            ]
            live = kernel.list_cells()
            norm = lambda code: code.strip()  # noqa: E731
            matcher = difflib.SequenceMatcher(
                None, [norm(c["code"]) for c in live], [norm(code) for _name, code in disk], autojunk=False
            )
            ops = [op for op in matcher.get_opcodes() if op[0] != "equal"]
            if not ops:
                return
            touched = [live[i]["code"] for _t, i1, i2, _j1, _j2 in ops for i in range(i1, i2)]
            touched += [code for _t, _i1, _i2, j1, j2 in ops for _name, code in disk[j1:j2]]
            if any(_is_function_cell(code) for code in touched):
                self.hub.broadcast({"type": "status", "working": "an @app.function cell changed on disk: restarting the kernel…"})
                self._in_thread(lambda: self.start_kernel(notebook))
                return
            ids = [c["id"] for c in live]
            changed: list[str] = []
            previous: str | None = None
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == "equal":
                    previous = ids[i2 - 1] if i2 > i1 else previous
                    continue
                paired = min(i2 - i1, j2 - j1) if tag == "replace" else 0
                for offset in range(paired):
                    kernel.save_cell(ids[i1 + offset], disk[j1 + offset][1])
                    changed.append(ids[i1 + offset])
                    previous = ids[i1 + offset]
                for index in range(i1 + paired, i2):
                    kernel.delete_cell(ids[index])
                for name, code in disk[j1 + paired : j2]:
                    created = kernel.create_cell_after(previous, code, name, run=False)
                    new_id = _created_id(created)
                    if new_id is None:
                        raise RuntimeError("the kernel did not create a cell for the new code on disk")
                    changed.append(new_id)
                    previous = new_id
        self.hub.broadcast({"type": "status", "info": f"{notebook.name} changed on disk: {len(changed)} cell(s) updated, running them"})
        self.push_cells()
        self._in_thread(lambda: self._rerun_changed(kernel, changed))

    # -- the same cell edits, for an agent (``sca cell``) -------------------------

    def _brief(self, number: int, cell: dict) -> dict:
        brief = {
            "index": number,
            "id": cell["id"],
            "key": cell.get("key"),
            "name": cell.get("name"),
            "title": cell.get("title"),
            "status": cell.get("status"),
            "errors": cell.get("errors") or [],
            "output": cell.get("output"),
            "console": cell.get("console") or [],
            "readonly": bool(cell.get("readonly")),
            "ref": cell.get("ref"),
            "code": cell["code"],
        }
        if cell.get("blocked"):
            # The cell did not itself fail: an ancestor did (its report says which).
            brief["blocked"] = True
        return brief

    def cells_report(self, *, refresh: bool = True) -> dict:
        if refresh and self.kernel is not None:
            self.push_cells()
        upstream = _upstream_of(self.cells)
        place = {cell["id"]: (number, cell) for number, cell in enumerate(self.cells, start=1)}
        briefs = []
        for number, cell in enumerate(self.cells, start=1):
            brief = self._brief(number, cell)
            if brief["errors"] or brief.get("blocked"):
                # The cell the error names is often not the one at fault: say
                # what it reads, the failing ancestors first.
                brief["upstream"] = [
                    {
                        "index": place[dep][0],
                        "name": place[dep][1].get("name"),
                        "failing": bool(place[dep][1].get("errors")),
                    }
                    for dep in sorted(upstream.get(cell["id"], ()), key=lambda cid: place[cid][0])
                ]
            briefs.append(brief)
        return {
            "notebook": self.notebook.relative_to(self.workspace).as_posix() if self.notebook else None,
            # Agents poll this after a switch: the name flips at once, the
            # kernel is what makes a write go through instead of reading
            # "no kernel yet".
            "kernel": self.kernel is not None,
            "cells": briefs,
        }

    def _find_cell(self, ref: Any) -> dict:
        text = str(ref).strip()
        for cell in self.cells:
            if text in (cell["id"], cell.get("key")) or (text == cell.get("name") and text != "_"):
                return cell
        if text.isdigit() and 1 <= int(text) <= len(self.cells):
            return self.cells[int(text) - 1]
        raise KeyError(f"no cell {text!r} in {self.notebook.name if self.notebook else 'the notebook'}; run `sca cell ls`")

    def cell_command(self, op: str, body: dict) -> dict:
        """Run one cell operation for the CLI; returns the report or ``{"error": ...}``.

        The edit goes through the kernel exactly as one made in the page does, so the
        page shows it live and the file is written by the one writer that holds it.
        """
        kernel = self.kernel
        if kernel is None:
            return {"error": "the editor has no kernel yet; wait for it to start"}
        self._begin_run()
        self.push_cells()
        touched: list[str] = []
        try:
            if op == "edit":
                cell = self._find_cell(body.get("cell"))
                code = _module_code(str(body.get("code", "")))
                if _is_function_cell(cell["code"]):
                    return {"error": "this cell is an @app.function; edit it in the file (the editor takes the change in)"}
                if body.get("base") is not None and _module_code(str(body["base"])).strip() != _module_code(cell["code"]).strip():
                    return {"error": "conflict: the cell changed since you read it", "theirs": cell["code"]}
                if code.strip() != _module_code(cell["code"]).strip():
                    run = bool(body.get("run", True))
                    (kernel.edit_cell if run else kernel.save_cell)(cell["id"], code)
                    if run:
                        # The edit runs the cell itself; the sweep adds the
                        # dependents it made stale — their state is the
                        # feedback the caller asked for.
                        kernel.wait_idle()
                        kernel.run_until_settled([])
                elif body.get("run", True):
                    kernel.run_until_settled([cell["id"]])
                touched = [cell["id"]]
            elif op == "insert":
                after = body.get("after")
                if after in (None, "end"):
                    anchor = self.cells[-1]["id"] if self.cells else None
                elif after == "start":
                    anchor = None
                else:
                    anchor = self._find_cell(after)["id"]
                code = _module_code(str(body.get("code", ""))) or "# new cell"
                name = str(body["name"]) if body.get("name") else None
                created = _created_id(kernel.create_cell_after(anchor, code, name, run=False))
                if created is None:
                    return {"error": "the kernel did not create the cell"}
                if body.get("run", True):
                    kernel.run_until_settled([created])
                touched = [created]
            elif op == "delete":
                cell = self._find_cell(body.get("cell"))
                kernel.delete_cell(cell["id"])
            elif op == "run":
                refs = body.get("cells") or []
                ids = [self._find_cell(ref)["id"] for ref in refs] or [c["id"] for c in self.cells]
                kernel.run_until_settled(ids)
                touched = ids
            else:
                return {"error": f"unknown cell operation {op!r}"}
        except KeyError as exc:
            return {"error": str(exc.args[0])}
        kernel.wait_idle()
        self.push_cells()
        self.schedule_settle()
        report = self.cells_report(refresh=False)
        report["touched"] = [c["index"] for c in report["cells"] if c["id"] in touched]
        return report

    def _rerun_changed(self, kernel: MarimoKernel, changed: list[str]) -> None:
        self._begin_run()
        kernel.run_until_settled(changed)
        self.schedule_settle()

    def _watch_workspace(self) -> None:
        """Tell the pages when notebooks appear or disappear under the workspace."""
        known = self._workspace_stamps()
        while not self._shutdown.is_set():
            time.sleep(0.7)
            try:
                current = self._workspace_stamps()
            except OSError:
                continue
            # The open notebook is rewritten by the editor on every edit; only its
            # appearing or vanishing counts.
            open_path = self.notebook
            changed = set(current) ^ set(known)
            changed |= {p for p in current if p in known and current[p] != known[p] and p != open_path}
            known = current
            if changed:
                self.hub.broadcast({"type": "workspace.changed"})

    def _workspace_stamps(self) -> dict[Path, int]:
        import os

        stamps: dict[Path, int] = {}
        for directory, subdirectories, files in os.walk(self.workspace):
            subdirectories[:] = [
                name for name in subdirectories
                if not name.startswith((".", "_")) and name not in _SKIPPED_DIRS
            ]
            for name in files:
                if name.endswith(".py") and not name.startswith("_"):
                    path = Path(directory) / name
                    try:
                        stamps[path] = path.stat().st_mtime_ns
                    except OSError:
                        continue
        return stamps

    def _propagate(self) -> None:
        """Serialized, coalescing: one reload covers every change that arrived meanwhile."""
        try:
            while True:
                with self._module_lock:
                    paths, self._module_dirty = self._module_dirty, set()
                    if not paths:
                        self._module_busy = False
                        return
                kernel = self.kernel
                if kernel is None:
                    continue
                own_names = self._own_module_names()
                _mtimes, _own, own_inputs = self._watched_files()
                if any(file in paths for file in own_names.values()):
                    shown = ", ".join(Path(path).name for path in sorted(paths))
                    self.hub.broadcast({"type": "status", "working": f"reloading {shown}…"})
                    kernel.reload_modules(list(own_names))
                    kernel.wait_idle(300)
                elif any(file in paths for file in own_inputs):
                    shown = ", ".join(Path(path).name for path in sorted(paths & own_inputs))
                    self.hub.broadcast({"type": "status", "working": f"{shown} changed: rerunning…"})
                    kernel.run_until_settled([cell["id"] for cell in self.cells])
                else:
                    uses = [cell["id"] for cell in self.cells if "use(" in cell["code"]]
                    if not uses:
                        continue
                    kernel.run_until_settled(uses)
                self._begin_run()
                self.schedule_settle()
        except Exception as exc:
            with self._module_lock:
                self._module_busy = False
            self.hub.broadcast({"type": "status", "error": f"reload failed: {str(exc)[-300:]}"})

    def _own_module_names(self) -> dict[str, Path]:
        return notebook_modules(self.notebook) if self.notebook else {}

    # -- the module view -----------------------------------------------------------

    def modules(self) -> list[dict]:
        return [module.to_dict() for module in scan_modules(self.workspace)]

    def emit_module(self, origin: str) -> None:
        """Tell the webuis about the module open in the module view."""
        path = self.module_path
        if path is None or not path.is_file():
            self.emit({"type": "module", "path": None})
            return
        try:
            code = path.read_text(encoding="utf-8")
        except OSError:
            return
        relative = path.relative_to(self.workspace).as_posix()
        used_by = next((m["used_by"] for m in self.modules() if m["path"] == relative), [])
        params = []
        for spec in list_module_parameters(path):
            row = spec.to_dict()
            row["id"] = spec.name
            row["value"] = spec.default
            row["modified"] = False
            params.append(row)
        self.emit(
            {
                "type": "module",
                "origin": origin,
                "path": relative,
                "name": path.name,
                "code": code,
                "used_by": used_by,
                "params": params,
            }
        )

    def open_module(self, rel_path: str) -> None:
        target = (self.workspace / rel_path).resolve()
        if self.workspace not in target.parents or not target.is_file() or target.suffix != ".py":
            raise ValueError(f"not a module of this workspace: {rel_path}")
        self.module_path = target
        self._watched = self._watched_files()[0]
        self.emit_module("open")

    def save_module(self, rel_path: str, code: str) -> None:
        """Autosave from the module view; the dependents follow."""
        target = self._module_file(rel_path)
        if target.read_text(encoding="utf-8") == code:
            return
        target.write_text(code, encoding="utf-8")
        self._after_module_write(target, "save")

    def set_module_params(self, rel_path: str, values: dict[str, float | int | bool]) -> None:
        """Write parameter values into the dataclass defaults of the module."""
        target = self._module_file(rel_path)
        code = target.read_text(encoding="utf-8")
        for name, value in values.items():
            class_name, dot, field = name.partition(".")
            changed = (
                commit_field_value(code, class_name, field, value) if dot else commit_value(code, name, value)
            )
            if changed is None:
                self.hub.broadcast({"type": "status", "error": f"cannot write {name} into {target.name}"})
                continue
            code = changed
        if code != target.read_text(encoding="utf-8"):
            target.write_text(code, encoding="utf-8")
            self._after_module_write(target, "param")

    def _module_file(self, rel_path: str) -> Path:
        target = (self.workspace / rel_path).resolve()
        if self.workspace not in target.parents or not target.is_file() or target.suffix != ".py":
            raise ValueError(f"not a module of this workspace: {rel_path}")
        return target

    def _after_module_write(self, target: Path, origin: str) -> None:
        # Our own write: the watcher must not fire a second reload for it.
        try:
            self._watched[target] = target.stat().st_mtime_ns
        except OSError:
            pass
        self.emit_module(origin)
        self._files_changed({target}, announce=False)

    def cell_status(self, cell_id: str, status: str) -> None:
        """A cell's state changed in the kernel: tell the webuis (its run button shows it)."""
        title = None
        for cell in self.cells:
            if cell["id"] == cell_id:
                cell["status"] = status
                title = cell.get("title")
        self.hub.broadcast({"type": "cell.status", "id": cell_id, "status": status, "title": title})

    def remember(self, envelope: dict) -> None:
        if envelope.get("type") in self._REPLAYED:
            self.latest[envelope["type"]] = envelope

    def emit(self, envelope: dict) -> None:
        self.remember(envelope)
        self.hub.broadcast(envelope)

    def replay(self) -> list[dict]:
        return [self.latest[key] for key in self._REPLAYED if key in self.latest]

    def hello(self) -> dict:
        return {
            "type": "hello",
            "workspace": str(self.workspace),
            "notebook": self.notebook.name if self.notebook else None,
            "path": self.notebook.relative_to(self.workspace).as_posix() if self.notebook else None,
            "kernel": self.kernel is not None and self.kernel.alive,
            "marimo_url": self.kernel.marimo_url if self.kernel else None,
        }

    def settled_error(self) -> dict | None:
        """The publish error of the last settle, for a page that connects late.

        ``status`` envelopes are momentary and not replayed, but a page that
        refreshes after a failed publish must still learn why no model is
        coming — its veil only lifts on a ``preview`` or an error.
        """
        if not self._last_publish_error:
            return None
        return {"type": "status", "error": self._last_publish_error[-300:]}

    # -- settling: the cells ran; publish what they made -----------------------

    def schedule_settle(self) -> None:
        """A batch of cell runs ended: settle once the activity calms down."""
        with self._settle_lock:
            if self._settle_timer is not None:
                self._settle_timer.cancel()
            self._settle_dirty = True
            self._settle_timer = threading.Timer(0.12, self._settle_in_thread)
            self._settle_timer.daemon = True
            self._settle_timer.start()

    def _settle_in_thread(self) -> None:
        try:
            with self._settle_lock:
                if not self._settle_dirty:
                    # The settle that ran meanwhile (a boot's own, which the run it ended with also asked for)
                    # already published what these runs made.
                    return
            self.settle()
        except Exception as exc:  # never let a timer thread die silently
            self.hub.broadcast({"type": "status", "error": str(exc)[-300:]})

    def settle(self) -> None:
        """Push the cells, features and parameters, then the product package."""
        kernel = self.kernel
        if kernel is None:
            return
        with self._settle_lock:
            self._settle_dirty = False
            # The signature of what is published is taken before it is built.
            try:
                self._publish_signature = self._signature(self.notebook) if self.notebook else None
            except (OSError, ValueError):
                self._publish_signature = None
            # One round trip into the kernel: it lists the cells in the same call that publishes the preview
            # (the kernel keeps what it listed for the push below).
            result = kernel.publish_preview(self.preview_url, step=self.notebook.stem if self.notebook else "")
            self.push_cells()
            if result.get("ok"):
                self._last_publish_error = ""
                self._stopped = False
                return
            message = str(result.get("error", ""))
            if kernel.setup_errors:
                # No product because the notebook's setup failed (a module it imports
                # does not compile): that is the cause, not the missing product.
                message = f"setup failed — {kernel.setup_errors[0]}"
            if self._stopped:
                # The person stopped the run: its cells have no product, and that is no fault.
                self._stopped = False
                self._last_publish_error = ""
                self.hub.broadcast({"type": "status", "info": "stopped"})
                return
            # A notebook mid-edit has no product yet; say so once, not per run.
            if message != self._last_publish_error:
                self._last_publish_error = message
                self.hub.broadcast({"type": "status", "error": message[-300:]})

    def _begin_run(self) -> None:
        """Cells are about to run because someone asked for it: report afresh.

        The dedup above is for the parameter burst, where a product-less
        notebook would repeat the same line on every slider tick.  A discrete
        run (a page command, an agent edit, a file change) is a new question:
        its failure must be told even if it repeats the last error word for
        word, or the page waits out its whole veil for an answer that never
        comes.
        """
        self._last_publish_error = ""

    @property
    def preview_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/runtime/preview"

    @property
    def package_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/runtime/package"

    def push_cells(self) -> None:
        """Broadcast the cells, their feature headers and the parameters."""
        kernel = self.kernel
        if kernel is None:
            return
        self._publish_cells(kernel.list_cells())

    def _publish_cells(self, cells: list[dict]) -> None:
        keys = cell_keys(cell["code"] for cell in cells)
        features: list[dict] = []
        specs: list[ParamSpec] = []
        for cell, key in zip(cells, keys):
            cell["key"] = key
            found = features_in_cell(cell["code"], key)
            cell["feature"] = found[0].slug if found else None
            cell["title"] = cell_title(cell["code"], cell["feature"])
            # code mode would turn an @app.function into a plain cell
            cell["readonly"] = cell.get("readonly", False) or _is_function_cell(cell["code"])
            features.extend(
                {"cell": cell["id"], "label": feature.slug, "kind": feature.role or "feature"}
                for feature in found
            )
            specs.extend(
                ParamSpec(**{**spec.__dict__, "cell": cell["id"]})
                for spec in parameters_in_cell(cell["code"], key)
            )
        try:
            text = self.notebook.read_text(encoding="utf-8") if self.notebook else ""
        except OSError:
            text = ""
        for number, (cell, lines) in enumerate(zip(cells, file_line_ranges(text, [c["code"] for c in cells])), start=1):
            where = f"{self.notebook}:L{lines[0]}-L{lines[1]}" if lines and self.notebook else str(self.notebook)
            cell["lines"] = list(lines) if lines else None
            cell["ref"] = f"{where} (cell {number:02d} `{cell['title']}`)"
        self.cells = cells
        self.specs = {spec.name: spec for spec in specs}
        self.emit({"type": "notebook.cells", "cells": cells})
        self.emit({"type": "notebook.features", "features": features})
        self.emit_params()
        self.write_snapshot()

    def emit_params(self) -> None:
        config = self.config
        saved = read_saved_params(config) if config is not None else {}
        variables = []
        for spec in self.specs.values():
            row = spec.to_dict()
            row["id"] = spec.name
            row["value"] = saved.get(spec.name, spec.default)
            row["modified"] = spec.name in saved and saved[spec.name] != spec.default
            variables.append(row)
        self.emit({"type": "params.schema", "vars": variables})
        self.emit({"type": "params.values", "values": {row["id"]: row["value"] for row in variables}})

    # -- webui command -> kernel operation ---------------------------------------

    def dispatch_command(self, message: dict) -> dict:
        """Translate one ui command into kernel operations. Returns an ack."""
        kind = message.get("type")
        if kind == "module.open":
            try:
                self.open_module(str(message.get("path", "")))
            except ValueError as error:
                return {"type": "error", "message": str(error)}
            return {"type": "ack", "command": kind}
        if kind == "module.close":
            self.module_path = None
            self.emit_module("close")
            return {"type": "ack", "command": kind}
        if kind == "module.save":
            self._in_thread(lambda: self.save_module(str(message.get("path", "")), str(message.get("code", ""))))
            return {"type": "ack", "command": kind}
        if kind == "module.param":
            path = str(message.get("path", ""))
            values = {str(k): v for k, v in dict(message.get("values", {})).items() if isinstance(v, (int, float, bool))}
            self._in_thread(lambda: self.set_module_params(path, values))
            return {"type": "ack", "command": kind}
        kernel = self.kernel
        if kernel is None:
            return {"type": "error", "message": "no kernel"}
        if kind == "entity.info":
            entity_id = str(message.get("entity_id", ""))
            node_id = message.get("node_id")

            def lookup() -> None:
                info = kernel.entity_info(entity_id)
                self.hub.broadcast(
                    {"type": "entity.info", "entity_id": entity_id, "node_id": node_id, "entity": info}
                )

            self._in_thread(lookup)
            return {"type": "ack", "command": kind}
        if kind == "interrupt.request":
            self._stopped = True
            self._in_thread(kernel.interrupt)
            return {"type": "ack", "command": kind}
        if kind == "param.set":
            self._enqueue_params(kernel, dict(message.get("values", {})))
            return {"type": "ack", "command": kind}
        if kind == "export.request":
            self._export()
            return {"type": "ack", "command": kind}
        if kind in ("param.commit", "param.revert"):
            names = [str(name) for name in message.get("names", [])] or list(self.specs)
            self._in_thread(lambda: self._commit(kernel, names, revert=kind == "param.revert"))
            return {"type": "ack", "command": kind}

        if kind == "selection.set":
            items = [item for item in message.get("items", []) if isinstance(item, dict)]
            self._in_thread(lambda: self._set_selection(kernel, items))
            return {"type": "ack", "command": kind}

        cell = str(message.get("cell") or "")
        if kind == "cell.save":
            # Autosave: write the edit to the notebook file, do not run it.
            code = _module_code(str(message.get("code", "")))
            current = next((c["code"] for c in self.cells if c["id"] == cell), None)
            if current is None or code.strip() == _module_code(current).strip():
                return {"type": "ack", "command": kind}
            if self._conflicts(message, cell, code, current):
                return {"type": "ack", "command": kind}
            if _is_function_cell(current):
                return {
                    "type": "error",
                    "message": "this cell is an @app.function; edit it in the file or in the marimo editor",
                }

            def save() -> None:
                kernel.save_cell(cell, code)
                self.push_cells()

            self._in_thread(save)
            return {"type": "ack", "command": kind}
        if kind == "rerun.request":
            # Header rerun (no cell) refreshes the whole notebook; a per-cell
            # rerun runs that cell and leaves its dependents stale.
            ids = [cell] if cell else [c["id"] for c in self.cells]
            if message.get("above"):
                # Every cell above this one, in notebook order (not itself).
                order = [c["id"] for c in self.cells]
                ids = order[: order.index(cell)] if cell in order else []
                if not ids:
                    return {"type": "ack", "command": kind}
            action = lambda: kernel.run_cells(ids)  # noqa: E731
        elif kind == "insert.request":
            after = message.get("after")
            action = lambda: kernel.insert_cell(str(after) if after else None)  # noqa: E731
        elif kind == "rollback.request":
            # Delete the cell (persisted to the file); marimo marks what read
            # its variables stale.
            action = lambda: kernel.delete_cell(cell)  # noqa: E731
        elif kind == "code.edit":
            code = _module_code(str(message.get("code", "")))
            current = next((c["code"] for c in self.cells if c["id"] == cell), None)
            if current is not None and code.strip() != _module_code(current).strip() and self._conflicts(message, cell, code, current):
                return {"type": "ack", "command": kind}
            if current is not None and code.strip() != _module_code(current).strip() and _is_function_cell(current):
                # marimo's code mode would turn an @app.function into a plain
                # cell; edit those in the file or in marimo's own editor.
                return {
                    "type": "error",
                    "message": "this cell is an @app.function; edit it in the file or in the marimo editor",
                }
            if current is not None and code.strip() == _module_code(current).strip():
                # Nothing to change: run the cell, never rewrite the notebook file.
                action = lambda: kernel.run_cells([cell])  # noqa: E731
            else:
                action = lambda: kernel.edit_cell(cell, code)  # noqa: E731
        else:
            return {"type": "error", "message": f"unknown command: {kind}"}

        def run() -> None:
            self._begin_run()
            result = action()
            if result.get("success") is False:
                self.hub.broadcast(
                    {"type": "status", "error": (result.get("log") or "kernel command failed")[-400:]}
                )
            kernel.wait_idle()
            # The kernel reports a completed run for these too, but settle
            # even when it reported failure: the edit may have applied and
            # the error state is what the notebook UI must show.
            self.schedule_settle()

        self._in_thread(run)
        return {"type": "ack", "command": kind}

    def _conflicts(self, message: dict, cell: str, mine: str, current: str) -> bool:
        """The page edited a cell that changed under it: keep what is on disk.

        The page says which code its edit started from (``base``).  If the cell
        is something else now (an agent edited the file and the editor took the
        change in), writing the page's version would erase that edit, so the
        write is dropped and the page is told both versions; it shows the file's
        version and keeps its own in the log.
        """
        base = message.get("base")
        now = _module_code(current).strip()
        # A page types on: its second save still names the text it started from, which
        # its own first save has replaced since.  Only a text the editor did not write
        # over is a change made by someone else.
        mine_before = self._edited_from.setdefault(cell, set())
        if base is None or _module_code(str(base)).strip() in (now, *mine_before):
            mine_before.add(now)
            return False
        self.hub.broadcast({"type": "cell.conflict", "cell": cell, "mine": mine, "theirs": current})
        return True

    def _in_thread(self, work: Any) -> None:
        def run() -> None:
            try:
                work()
            except Exception as exc:  # surface, never crash the WS handler
                self.hub.broadcast({"type": "status", "error": str(exc)[-400:]})

        threading.Thread(target=run, name="kernel-command", daemon=True).start()

    # -- parameters --------------------------------------------------------------

    def _clean_params(self, values: dict) -> dict[str, float | int | bool]:
        """Keep the values that name a parameter, clamped and typed to it."""
        clean: dict[str, float | int | bool] = {}
        for name, raw in values.items():
            spec = self.specs.get(str(name))
            if spec is None or isinstance(raw, str):
                continue
            if spec.kind == "bool":
                clean[spec.name] = bool(raw)
                continue
            if isinstance(raw, bool):
                continue
            number = float(raw)
            if spec.min is not None:
                number = max(spec.min, number)
            if spec.max is not None:
                number = min(spec.max, number)
            clean[spec.name] = int(round(number)) if spec.kind == "int" else number
        return clean

    def _enqueue_params(self, kernel: MarimoKernel, values: dict) -> None:
        """Coalesce slider bursts: at most one rebuild in flight; newer values
        always win; one follow-up rebuild per settled gesture."""
        clean = self._clean_params(values)
        if not clean:
            return
        with self._rebuild_cond:
            self._pending_params.update(clean)
        threading.Thread(target=self._rebuild_loop, args=(kernel,), name="param-rebuild", daemon=True).start()

    def _rebuild_loop(self, kernel: MarimoKernel) -> None:
        with self._rebuild_cond:
            if self._rebuild_inflight:
                return  # the running loop will pick up our pending values
            self._rebuild_inflight = True
        try:
            while True:
                with self._rebuild_cond:
                    if not self._pending_params:
                        return
                    partial = dict(self._pending_params)
                    self._pending_params.clear()
                since = time.monotonic() - self._last_rebuild_at
                if since < self._rebuild_min_interval:
                    time.sleep(self._rebuild_min_interval - since)
                self._last_rebuild_at = time.monotonic()
                try:
                    self._apply_params(kernel, partial)
                except Exception as exc:
                    self.hub.broadcast({"type": "status", "error": str(exc)[-400:]})
        finally:
            with self._rebuild_cond:
                self._rebuild_inflight = False

    def _apply_params(self, kernel: MarimoKernel, values: dict[str, float | int | bool]) -> None:
        """Save the values, then run the cells that declare them.

        The kernel executor puts the saved values in place as those cells
        finish; marimo's dataflow marks what reads them stale, and
        ``run_until_settled`` runs exactly that.
        """
        config = self.config
        if config is None:
            raise RuntimeError("no SimpleCAD notebook is open")
        saved = read_saved_params(config)
        cells: list[str] = []
        for name, value in values.items():
            spec = self.specs[name]
            if value == spec.default:
                saved.pop(name, None)  # back at the source value
            else:
                saved[name] = value
            if spec.cell not in cells:
                cells.append(spec.cell)
        write_saved_params(config, saved)
        self.emit_params()
        kernel.run_until_settled(cells)
        self.schedule_settle()

    def _commit(self, kernel: MarimoKernel, names: list[str], *, revert: bool) -> None:
        """Write saved values into the notebook source, or drop them."""
        config = self.config
        if config is None:
            return
        saved = read_saved_params(config)
        names = [name for name in names if name in saved]
        if not names:
            return
        if not revert:
            codes = {cell["id"]: cell["code"] for cell in self.cells}
            changed: dict[str, str] = {}
            for name in names:
                spec = self.specs.get(name)
                if spec is None:
                    continue
                code = commit_value(changed.get(spec.cell, codes[spec.cell]), name, saved[name])
                if code is None:
                    self.hub.broadcast({"type": "status", "error": f"cannot write {name} into the source"})
                    return
                changed[spec.cell] = code
            for cell_id, code in changed.items():
                kernel.edit_cell(cell_id, code)
            kernel.wait_idle()
        for name in names:
            saved.pop(name, None)
        write_saved_params(config, saved)
        if revert:
            kernel.run_until_settled([self.specs[name].cell for name in names if name in self.specs])
        self._begin_run()
        self.schedule_settle()

    # -- selection and the agent snapshot ----------------------------------------

    def _set_selection(self, kernel: MarimoKernel, items: list[dict]) -> None:
        """Write the viewport selection into the notebook's selection cell.

        The webuis are told at once, from here: the kernel runs scratch code
        one piece at a time, so a write that queues behind a long run (a
        publish of a big assembly takes seconds) must not hold the picture
        back.  The write itself is coalesced: while one is in flight only the
        latest selection waits, and it is the one written.
        """
        if kernel is not self.kernel:
            return  # the notebook was switched under this pick
        keep = ("kind", "entity_id", "node_id", "definition_id", "properties", "geometry")
        self.selection_items = [{key: item.get(key) for key in keep if key in item} for item in items]
        cell = next((c for c in self.cells if c["code"].lstrip().startswith(MARKER)), None)
        if cell is None and not items:
            self.write_snapshot()
            return
        code = selection_cell_code(self.selection_items)
        if cell is not None and code.strip() == cell["code"].strip():
            self.write_snapshot()
            return
        if cell is not None:
            cell["code"] = code
        else:
            self.cells.append(
                {
                    "id": PENDING_SELECTION_ID,
                    "name": "_",
                    "code": code,
                    "status": "idle",
                    "errors": [],
                    "output": None,
                    "console": [],
                    "key": "",
                    "feature": None,
                    "title": "selection",
                    "readonly": False,
                    "lines": None,
                    "ref": f"{self.notebook} (cell {len(self.cells) + 1:02d} `selection`)",
                }
            )
        self.emit({"type": "notebook.cells", "cells": self.cells})
        self.emit({"type": "selection", "items": self._selection_summary(), "variables": variable_names(self.selection_items)})
        self.write_snapshot()
        with self._selection_lock:
            self._selection_code = code
            if self._selection_busy:
                return
            self._selection_busy = True
        self._write_selection(kernel)

    def _write_selection(self, kernel: MarimoKernel) -> None:
        """Write the newest selection code into the kernel's cell; repeat while a newer one arrived."""
        try:
            while True:
                with self._selection_lock:
                    code, self._selection_code = self._selection_code, None
                    if code is None or kernel is not self.kernel:
                        # nothing (more) to write, or the notebook was switched meanwhile:
                        # a stale write must not land in the new notebook's cells
                        self._selection_code = None
                        self._selection_busy = False
                        return
                cell = next(
                    (c for c in self.cells if c["code"].lstrip().startswith(MARKER) and c["id"] != PENDING_SELECTION_ID),
                    None,
                )
                kernel.put_cell(code, cell_id=cell["id"] if cell else None)
                kernel.wait_idle(10)
                if kernel is not self.kernel:
                    continue
                self.push_cells()
        except Exception:
            with self._selection_lock:
                self._selection_busy = False
            raise

    def _selection_summary(self) -> list[dict]:
        names = variable_names(self.selection_items)
        return [
            {
                "variable": name,
                "kind": item.get("kind"),
                "entity_id": item.get("entity_id"),
                "node_id": item.get("node_id"),
                "definition_id": item.get("definition_id"),
            }
            for name, item in zip(names, self.selection_items)
        ]

    @property
    def snapshot_dir(self) -> Path:
        return self.workspace / ".sca-editor"

    def snapshot(self) -> dict:
        """What the person is looking at, as plain data for a coding agent."""
        selection_cell = next((c for c in self.cells if c["code"].lstrip().startswith(MARKER)), None)
        config = self.config
        saved = read_saved_params(config) if config is not None else {}
        png = self.snapshot_dir / "viewport.png"
        return {
            "workspace": str(self.workspace),
            "notebook": str(self.notebook) if self.notebook else None,
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "selection": {
                "items": self._selection_summary(),
                "cell": {"id": selection_cell["id"], "code": selection_cell["code"]} if selection_cell else None,
                "note": "the selection cell is saved in the notebook file; read it there",
            },
            "viewport_png": str(png) if png.is_file() else None,
            "cells": [
                {
                    "id": c["id"],
                    "title": c.get("title"),
                    "status": c.get("status"),
                    "errors": c.get("errors") or [],
                }
                for c in self.cells
            ],
            "parameters": {
                name: saved.get(name, spec.default) for name, spec in self.specs.items()
            },
            "modified_parameters": sorted(saved),
            "model_revision": self.preview_revision,
        }

    def write_endpoint(self, host: str) -> None:
        """Say where this editor listens, so ``sca cell`` and other tools find it."""
        try:
            directory = self.snapshot_dir
            directory.mkdir(parents=True, exist_ok=True)
            import os

            # The record is read on this machine, so the url is always the
            # loopback: a 0.0.0.0 url is no address (and walks into proxies).
            (directory / "server.json").write_text(
                json.dumps({"url": f"http://127.0.0.1:{self.port}", "pid": os.getpid(), "workspace": str(self.workspace)}),
                encoding="utf-8",
            )
        except OSError:
            pass

    def remove_endpoint(self) -> None:
        try:
            (self.snapshot_dir / "server.json").unlink()
        except OSError:
            pass

    def write_snapshot(self) -> None:
        """Keep ``.sca-editor/snapshot.json`` current; ``sca snapshot`` reads it."""
        try:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            (self.snapshot_dir / "snapshot.json").write_text(
                json.dumps(self.snapshot(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError as error:
            print(f"[sca edit] could not write the snapshot: {error}", file=sys.stderr)

    def save_viewport(self, png: bytes) -> None:
        self.viewport_png = png
        try:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            (self.snapshot_dir / "viewport.png").write_bytes(png)
        except OSError as error:
            print(f"[sca edit] could not write the viewport image: {error}", file=sys.stderr)
        self.write_snapshot()

    # -- export ------------------------------------------------------------------

    def _export(self) -> None:
        """Write a product package next to the notebook: ``out/<stem>.scadpkg``.

        The editor shows previews; a package (the durable form, with the definition
        and the feature graph) takes seconds to make, so it is made when asked for.
        """
        kernel = self.kernel
        if kernel is None or self.notebook is None:
            self.hub.broadcast({"type": "status", "error": "nothing to export yet"})
            return
        self.hub.broadcast({"type": "status", "working": "building the package"})
        self._package_event.clear()
        result = kernel.publish(self.package_url, step=self.notebook.stem)
        if not result.get("ok") or not self._package_event.wait(30) or self.latest_package_bytes is None:
            self.hub.broadcast({"type": "status", "error": str(result.get("error", "the package was not made"))[-300:]})
            return
        target = self.notebook.parent / "out" / f"{self.notebook.stem}.scadpkg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.latest_package_bytes)
        self.hub.broadcast({"type": "status", "exported": str(target)})


def _upstream_of(cells: list[dict]) -> dict[str, set[str]]:
    """Per cell id: the ids of the cells it (transitively) reads.

    Compiled with marimo's own cell compiler, so a name is a dependency
    exactly when marimo's dataflow says so; a cell mid-edit (its code does
    not compile) contributes no edges rather than wrong ones.
    """
    owner: dict[str, str] = {}
    refs: dict[str, frozenset[str]] = {}
    for cell in cells:
        try:
            impl = compile_cell(_module_code(cell["code"]), cell["id"])
        except Exception:
            refs[cell["id"]] = frozenset()
            continue
        refs[cell["id"]] = impl.refs
        for name in impl.defs:
            owner.setdefault(name, cell["id"])
    direct = {cid: {owner[name] for name in names if name in owner and owner[name] != cid} for cid, names in refs.items()}
    closure: dict[str, set[str]] = {}

    def walk(cid: str) -> set[str]:
        if cid not in closure:
            closure[cid] = set()  # marimo forbids cycles; the placeholder guards one anyway
            closure[cid] = set().union(*(walk(dep) | {dep} for dep in direct.get(cid, ()))) if direct.get(cid) else set()
        return closure[cid]

    return {cid: walk(cid) for cid in refs}


def _module_code(code: str) -> str:
    """marimo's code_mode compiles cell code as a MODULE: a ``return`` in the
    cell's own scope (normal in marimo's file format) is a SyntaxError there.
    Strip those — the returned expression stays in place and becomes the cell
    output — and nothing else: a ``return`` inside a function or class the
    cell defines (an ``@app.function`` cell is one) is code, not syntax.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return code
    returns: list[ast.Return] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue  # their returns are their own
            if isinstance(child, ast.Return):
                returns.append(child)
            visit(child)

    visit(tree)
    lines = code.splitlines()
    for node in sorted(returns, key=lambda r: (r.lineno, r.col_offset), reverse=True):
        line = lines[node.lineno - 1]
        before, after = line[: node.col_offset], line[node.col_offset + len("return"):]
        lines[node.lineno - 1] = before + ("pass" if node.value is None else after.lstrip())
    return "\n".join(lines)


_SKIPPED_DIRS = frozenset({"node_modules", "venv", "site-packages", "build", "dist"})


def _setup_code_of(notebook: Path) -> str | None:
    from ..runtime._marimo import parse_notebook

    try:
        parsed = parse_notebook(notebook.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return None
    if parsed is None:
        return None
    return next((c.code.strip() for c in parsed.cells if getattr(c, "name", None) == "setup"), "")


def _created_id(result: dict) -> str | None:
    for line in (result.get("log") or "").splitlines():
        if line.startswith("SCA-CELL "):
            return line[len("SCA-CELL "):].strip()
    return None


def _static_cells(notebook: Path) -> list[dict]:
    """The notebook's cells as the file has them, for showing before a kernel runs them."""
    from ..runtime._marimo import parse_notebook

    try:
        parsed = parse_notebook(notebook.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return []
    if parsed is None:
        return []
    cells = []
    for index, cell in enumerate(parsed.cells):
        if getattr(cell, "name", None) == "setup":
            continue
        cells.append(
            {
                "id": f"static-{index}",
                "name": getattr(cell, "name", None) or "_",
                "code": cell.code,
                "status": "idle",
                "errors": [],
                "output": None,
                "console": [],
                "readonly": True,  # not editable until the kernel has the cell
            }
        )
    return cells


PENDING_SELECTION_ID = "selection-pending"
"""Id of the selection cell the webuis see before the kernel has created it."""


def file_line_ranges(text: str, codes: list[str]) -> list[tuple[int, int] | None]:
    """Where each cell's code is in the notebook file (1-based, inclusive).

    *codes* are the cells' code in notebook order; they are matched to the
    cells of the file in order, so a cell whose edit is not saved yet (or a
    function cell the file spells differently) gets ``None``.
    """
    from ..runtime._marimo import parse_notebook

    try:
        notebook = parse_notebook(text)
    except SyntaxError:
        return [None] * len(codes)
    if notebook is None:
        return [None] * len(codes)
    saved = [(cell.code.strip(), cell.lineno + 1, cell.lineno + max(1, len(cell.code.splitlines()))) for cell in notebook.cells]
    ranges: list[tuple[int, int] | None] = []
    cursor = 0
    for code in codes:
        found = None
        for index in range(cursor, len(saved)):
            if saved[index][0] == code.strip():
                found = (saved[index][1], saved[index][2])
                cursor = index + 1
                break
        ranges.append(found)
    return ranges


_PARAMS_HEADER = re.compile(r"^#\s*-{2,}\s*params(?::\s*(.*?))?\s*-*\s*$", re.MULTILINE)


def cell_title(code: str, feature: str | None) -> str:
    """The step's name: its feature slug, its params header, else what it defines."""
    if feature:
        return feature
    if code.lstrip().startswith(MARKER):
        return "selection"
    header = _PARAMS_HEADER.search(code)
    if header:
        return f"params: {header.group(1)}" if header.group(1) else "params"
    try:
        body = ast.parse(code).body
    except (SyntaxError, ValueError):
        body = []
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return statement.name
        targets = (
            statement.targets if isinstance(statement, ast.Assign)
            else [statement.target] if isinstance(statement, ast.AnnAssign) else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and not target.id.startswith("_"):
                return target.id
    for line in code.splitlines():
        if line.strip().startswith("#"):
            text = line.strip().lstrip("#").strip(" -")
            if text:
                return text[:40]
    return "cell"


def _is_function_cell(code: str) -> bool:
    """Whether the cell is one ``def``/``class`` (an ``@app.function`` cell)."""
    try:
        body = ast.parse(code).body
    except (SyntaxError, ValueError):
        return False
    return len(body) == 1 and isinstance(body[0], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))


def create_app(state: WorkspaceState) -> Starlette:
    hub = state.hub

    async def health(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "workspace": str(state.workspace),
                "notebook": state.notebook.name if state.notebook else None,
                "kernel": state.kernel is not None and state.kernel.alive,
            }
        )

    async def push_preview(request: Request) -> JSONResponse:
        """The kernel hands over the preview of the model it just built.

        The bytes are cached for late webuis; webuis only get a lightweight
        revision event and fetch the bytes on demand.
        """
        body = await request.body()
        if not body:
            return JSONResponse({"ok": False, "error": "empty preview"}, status_code=400)
        unchanged = state.latest_preview_bytes == body
        state.latest_preview_bytes = bytes(body)
        state.preview_revision += 1
        state.emit(
            {
                "type": "preview",
                "revision": state.preview_revision,
                "step": request.headers.get("X-Live-Step", ""),
                "name": state.notebook.stem if state.notebook else None,
                "size": len(body),
                # The model on screen is this model: nothing to reload.
                "unchanged": unchanged,
            }
        )
        if state.notebook is not None and state._publish_signature is not None:
            await asyncio.to_thread(state.remember_model, state.notebook, state._publish_signature, bytes(body))
        # The model is fine again: clear a stale "no product yet" message.
        hub.broadcast({"type": "status", "error": ""})
        await asyncio.to_thread(state.write_snapshot)
        return JSONResponse({"ok": True, "revision": state.preview_revision})

    async def latest_preview(request: Request) -> Response:
        """The freshest preview bytes."""
        if state.latest_preview_bytes:
            return Response(content=state.latest_preview_bytes, media_type="application/vnd.simplecad.preview")
        return JSONResponse({"error": "no preview published yet"}, status_code=404)

    async def push_package(request: Request) -> JSONResponse:
        """The kernel hands over a full package, made because an export asked for it."""
        body = await request.body()
        if not body:
            return JSONResponse({"ok": False, "error": "empty package"}, status_code=400)
        state.latest_package_bytes = bytes(body)
        state._package_event.set()
        return JSONResponse({"ok": True})

    async def latest_package(request: Request) -> Response:
        """The package last made for an export."""
        if state.latest_package_bytes:
            return Response(
                content=state.latest_package_bytes,
                media_type="application/vnd.simplecad.scadpkg",
                headers={"Content-Disposition": 'inline; filename="latest.scadpkg"'},
            )
        return JSONResponse({"error": "no package made yet"}, status_code=404)

    async def api_cells(request: Request) -> JSONResponse:
        """The open notebook's cells, with their state (for ``sca cell ls``)."""
        report = await asyncio.to_thread(state.cells_report)
        return JSONResponse(report)

    async def api_cell_command(request: Request) -> JSONResponse:
        op = request.path_params["op"]
        try:
            body = json.loads(await request.body() or b"{}")
        except json.JSONDecodeError:
            return JSONResponse({"error": "body is not JSON"}, status_code=400)
        report = await asyncio.to_thread(state.cell_command, op, body if isinstance(body, dict) else {})
        status = 409 if str(report.get("error", "")).startswith("conflict") else 400 if "error" in report else 200
        return JSONResponse(report, status_code=status)

    async def sdk_index(request: Request) -> JSONResponse:
        """The SDK's public API (names and parameters), for the cell editor's completion."""
        from .apiindex import build_index

        return JSONResponse(build_index(), headers={"Cache-Control": "max-age=3600"})

    async def workspace_list(request: Request) -> JSONResponse:
        """The SimpleCAD notebooks of the workspace."""
        current = state.notebook.relative_to(state.workspace).as_posix() if state.notebook else None
        rows = [
            {
                "name": Path(entry.path).stem,
                "path": entry.path,
                "entry": True,
                "kind": entry.kind,
                "id": entry.id,
                "uses": list(entry.uses),
                "current": entry.path == current,
                "error": entry.error,
            }
            for entry in scan_workspace(state.workspace)
        ]
        return JSONResponse({"notebooks": rows, "modules": state.modules()})

    async def workspace_open(request: Request) -> JSONResponse:
        """Switch the active notebook (restarts the kernel)."""
        try:
            message = json.loads(await request.body())
            rel_path = str(message["path"])
        except Exception:
            return JSONResponse({"ok": False, "error": "body must be {path}"}, status_code=400)

        try:
            target = state.resolve_notebook(rel_path)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        generation = state.reserve_switch()
        state.announce_opening(target)

        def run() -> None:
            try:
                state.open_notebook(rel_path, generation)
            except Exception as exc:
                hub.broadcast({"type": "status", "error": f"open failed: {exc}"})

        threading.Thread(target=run, name="notebook-open", daemon=True).start()
        return JSONResponse({"ok": True, "opening": rel_path})

    async def workspace_new(request: Request) -> JSONResponse:
        """Write a new notebook from a template, then open it."""
        try:
            message = json.loads(await request.body())
            path = create_notebook(
                state.workspace, str(message["name"]), str(message.get("kind", "part"))
            )
        except (FileExistsError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        rel_path = path.relative_to(state.workspace).as_posix()

        generation = state.reserve_switch()
        state.announce_opening(path)

        def run() -> None:
            try:
                state.open_notebook(rel_path, generation)
                hub.broadcast({"type": "status", "created": rel_path})
            except Exception as exc:
                hub.broadcast({"type": "status", "error": f"open failed: {exc}"})

        threading.Thread(target=run, name="notebook-new", daemon=True).start()
        return JSONResponse({"ok": True, "created": rel_path})

    async def studio_select(request: Request) -> JSONResponse:
        """Webui reports the viewport selection; agents read it back."""
        try:
            message = json.loads(await request.body())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)
        state.selection = message if isinstance(message, dict) else {"value": message}
        state.emit({"type": "selection", **state.selection})
        return JSONResponse({"ok": True})

    async def viewport_image(request: Request) -> JSONResponse:
        """The webui posts what the viewport shows (PNG) when the selection changes."""
        body = await request.body()
        if not body.startswith(b"\x89PNG"):
            return JSONResponse({"ok": False, "error": "body must be a PNG"}, status_code=400)
        await asyncio.to_thread(state.save_viewport, bytes(body))
        return JSONResponse({"ok": True})

    async def snapshot(request: Request) -> JSONResponse:
        """Agent-facing: the selection (as ql code in the notebook), the cells' state, the viewport image path."""
        return JSONResponse(state.snapshot())

    async def studio_selected(request: Request) -> JSONResponse:
        """Agent-facing read: what does the human have selected right now?"""
        return JSONResponse({"selected": state.selection, "notebook": state.notebook.name if state.notebook else None})

    async def ws_endpoint(websocket) -> None:
        await hub.connect(websocket)
        await websocket.send_json(state.hello())
        for envelope in state.replay():
            await websocket.send_json(envelope)
        settled = state.settled_error()
        if settled is not None:
            await websocket.send_json(settled)
        try:
            while True:
                message = await websocket.receive_json()
                try:
                    if isinstance(message, dict) and str(message.get("type", "")).endswith(
                        (".set", ".request", ".edit", ".commit", ".revert", ".save", ".open", ".close", ".param", ".info")
                    ):
                        ack = await asyncio.to_thread(state.dispatch_command, message)
                        await websocket.send_json(ack)
                    else:
                        await websocket.send_json({"type": "echo", "message": message})
                except Exception as exc:  # one bad command must not kill the socket
                    await websocket.send_json({"type": "error", "message": str(exc)[-300:]})
        except WebSocketDisconnect:
            hub.disconnect(websocket)

    routes = [
        Route("/api/health", health),
        Route("/api/runtime/preview", push_preview, methods=["POST"]),
        Route("/api/preview/latest", latest_preview, methods=["GET"]),
        Route("/api/runtime/package", push_package, methods=["POST"]),
        Route("/api/package/latest", latest_package, methods=["GET"]),
        Route("/api/sdk", sdk_index, methods=["GET"]),
        Route("/api/cells", api_cells, methods=["GET"]),
        Route("/api/cells/{op}", api_cell_command, methods=["POST"]),
        Route("/api/workspace", workspace_list, methods=["GET"]),
        Route("/api/workspace/open", workspace_open, methods=["POST"]),
        Route("/api/workspace/new", workspace_new, methods=["POST"]),
        Route("/api/studio/select", studio_select, methods=["POST"]),
        Route("/api/studio/selected", studio_selected, methods=["GET"]),
        Route("/api/studio/viewport", viewport_image, methods=["POST"]),
        Route("/api/snapshot", snapshot, methods=["GET"]),
        WebSocketRoute("/ws", ws_endpoint),
    ]
    app = Starlette(routes=routes)
    if DIST_DIR.is_dir():
        app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="webui")
    return app


def serve_workspace(
    workspace: Path,
    *,
    host: str,
    port: int,
    open_browser: bool,
    notebook: Path | None = None,
) -> int:
    workspace = workspace.expanduser().resolve()
    if not workspace.is_dir():
        print(f"[sca edit] workspace directory does not exist: {workspace}", file=sys.stderr)
        return 2

    state = WorkspaceState(workspace, notebook)
    state.port = port
    app = create_app(state)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    original_startup = server.startup

    async def startup(sockets=None):
        await original_startup(sockets)
        hub = state.hub
        hub.attach_loop(asyncio.get_running_loop())
        print(f"[sca edit] workspace {state.workspace}")
        state.write_endpoint(host)
        threading.Thread(target=state._watch_workspace, name="workspace-watch", daemon=True).start()

        if state.notebook is None:
            print("[sca edit] no SimpleCAD notebook found in the workspace", file=sys.stderr)
            hub.broadcast({"type": "status", "error": "no SimpleCAD notebook in the workspace; create one"})
        else:
            def boot() -> None:
                try:
                    assert state.notebook is not None
                    state.start_kernel(state.notebook)
                except Exception as exc:
                    print(f"[sca edit] kernel boot failed: {exc}", file=sys.stderr)
                    hub.broadcast({"type": "status", "error": f"kernel boot failed: {exc}"})
                    return
                kernel = state.kernel
                if kernel is not None:  # None: a notebook was opened meanwhile
                    print(f"[sca edit] marimo kernel ready on {kernel.marimo_url}")
                state.watch_kernel()

            threading.Thread(target=boot, name="kernel-boot", daemon=True).start()

        print(f"[sca edit] serving http://{host}:{port}/")
        if open_browser:
            threading.Thread(
                target=webbrowser.open, args=(f"http://127.0.0.1:{port}/",), daemon=True
            ).start()

    server.startup = startup

    original_shutdown = server.shutdown

    async def shutdown(sockets=None):
        state._shutdown.set()
        state.remove_endpoint()
        if state.kernel is not None:
            state.kernel.stop()
        await original_shutdown(sockets=sockets)

    server.shutdown = shutdown
    server.run()
    return 0

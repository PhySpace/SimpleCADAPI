"""Host the workspace's marimo kernel as a subprocess and drive it.

The bridge owns exactly one headless ``marimo edit`` server per workspace.
It creates the kernel session by holding one WebSocket connection (the same
thing a browser tab does) and drives everything else through marimo's HTTP
API:

- ``POST /api/kernel/execute`` runs driver snippets in the kernel's scratch
  cell (deliberately auth-exempt for agents);
- ``marimo._code_mode`` edits, runs and deletes notebook cells;
- the kernel runs the notebook with the SimpleCAD cell executor
  (:mod:`simplecadapi.runtime.executor`), exactly as ``sca run`` does; the
  bridge asks it for the product with
  :func:`simplecadapi.runtime.live.publish_live` once the cells settle.

The held WebSocket also carries marimo's own messages; ``completed-run`` ends
every batch of cell runs, whoever started it (this bridge, or a person
typing in the embedded marimo editor), and is what the server reacts to.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import websockets

SESSION_ID = "sca-runtime"


class KernelError(RuntimeError):
    pass


class MarimoKernel:
    def __init__(
        self,
        notebook: Path,
        *,
        server_port: int,
        on_run_complete: Callable[[], None] | None = None,
    ) -> None:
        self.notebook = notebook.expanduser().resolve()
        self.on_run_complete = on_run_complete
        self._own_calls = 0
        self._own_ended = 0.0
        self.workspace = self.notebook.parent
        self.marimo_port = _free_port(server_port + 1)
        self.marimo_url = f"http://127.0.0.1:{self.marimo_port}"
        self._process: subprocess.Popen[bytes] | None = None
        self._token: str | None = None
        self._ws_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------------

    def _ensure_lazy_config(self) -> None:
        """Provision marimo's lazy reactive mode for the workspace.

        The editor's execution semantics (cell rollback, differential
        re-runs, stale suffixes) are marimo's lazy mode:
        runtime.on_cell_change="lazy". marimo discovers config by walking up
        from its cwd (the workspace), so when NO .marimo.toml exists on that
        path this writes one at the workspace root — workspaces may live
        anywhere on disk. An existing config anywhere up the tree always
        wins (the user's choice).
        """
        probe = self.workspace
        while True:
            if (probe / ".marimo.toml").is_file():
                return
            parent = probe.parent
            if parent == probe:
                break
            probe = parent
        try:
            (self.workspace / ".marimo.toml").write_text(
                "# Provisioned by sca edit: rollback / differential rerun\n"
                "# semantics need marimo's lazy reactive mode.\n"
                '[runtime]\non_cell_change = "lazy"\n',
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[sca edit] could not write lazy-mode config: {exc}", file=sys.stderr)

    def start(self, timeout: float = 60.0) -> None:
        """Spawn marimo, wait for readiness, create the kernel session and
        instantiate the notebook (runs all cells top-to-bottom)."""
        self._ensure_lazy_config()
        env = dict(os.environ)
        log_path = self.workspace / ".sca-editor" / "marimo-kernel.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = log_path.open("ab")
        self._process = subprocess.Popen(
            [
                sys.executable, "-m", "marimo", "edit", str(self.notebook),
                "--headless", "--no-token", "--port", str(self.marimo_port),
            ],
            cwd=str(self.workspace),
            env=env,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise KernelError(f"marimo exited with code {self._process.returncode}")
            try:
                with urllib.request.urlopen(f"{self.marimo_url}/api/sessions", timeout=2) as resp:
                    resp.read()
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.3)
        else:
            self.stop()
            raise KernelError(f"marimo not ready after {timeout:.0f}s")

        self._token = self._fetch_token()
        self._hold_session()
        self.instantiate()

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop(self) -> None:
        self._stop.set()
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        if getattr(self, "_log_file", None) is not None:
            try:
                self._log_file.close()
            except OSError:
                pass

    # -- session plumbing ----------------------------------------------------------

    def _fetch_token(self) -> str:
        """The skew-protection token ships in the marimo homepage HTML."""
        with urllib.request.urlopen(f"{self.marimo_url}/", timeout=5) as resp:
            html = resp.read().decode("utf-8", "replace")
        match = re.search(r'"serverToken":\s*"([^"]+)"', html)
        if match is None:
            raise KernelError("could not read marimo server token from homepage")
        return match.group(1)

    def _hold_session(self) -> None:
        """Hold one WS connection to marimo — this creates and keeps the
        kernel session alive (a headless browser tab, effectively).

        marimo restarts its websocket service whenever the notebook file
        changes on disk (code.edit persists) — the connection dies with
        1012/service-restart. The holder must reconnect, or the session
        silently dies and every later edit/run becomes a no-op.
        """

        def run() -> None:
            import asyncio

            async def main() -> None:
                uri = (
                    f"ws://127.0.0.1:{self.marimo_port}/ws"
                    f"?session_id={SESSION_ID}&file_key={self.notebook}"
                )
                while not self._stop.is_set():
                    try:
                        async with websockets.connect(uri, max_size=None) as ws:
                            async for message in ws:
                                self._on_message(message)
                    except Exception:
                        if self._stop.is_set():
                            return
                        # marimo restarted; re-hold the same session id.
                        await asyncio.sleep(1.0)

            asyncio.run(main())

        self._ws_thread = threading.Thread(target=run, name="marimo-bridge-ws", daemon=True)
        self._ws_thread.start()
        time.sleep(1.0)

    def _on_message(self, message: str | bytes) -> None:
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        if not isinstance(data, dict) or data.get("op") != "completed-run":
            return
        # Runs this bridge asked for (scratch snippets, publishing) end in a
        # completed-run too; only the cell runs of someone else count.
        if self._own_calls or time.monotonic() - self._own_ended < 0.5:
            return
        if self.on_run_complete is not None:
            self.on_run_complete()

    def instantiate(self) -> None:
        """Run all notebook cells (what the marimo frontend does on load)."""
        self._post("/api/kernel/instantiate", {"objectIds": [], "values": []})

    def list_cells(self) -> list[dict]:
        """Notebook cells as [{id, name, code, status, output, console}].

        Mirrors the marimo reading experience: each cell carries its last
        execution status, main output text, and buffered console output so
        the studio can render code → output interleaved. Infrastructure
        cells (the setup cell) are hidden; every other cell, anonymous ones
        included, is one block of the notebook. Cells are addressed by id.
        """
        hidden = {"setup"}
        result = self.execute(
            "import json as _json\n"
            "import marimo._code_mode as _cm\n"
            "def _text(_o):\n"
            "    if _o is None:\n"
            "        return None\n"
            "    # CellOutput.data is str | list[Error] | dict[str, Any] — render\n"
            "    # each shape as plain text instead of its repr.\n"
            "    _d = getattr(_o, 'data', None)\n"
            "    if isinstance(_d, str):\n"
            "        _v = _d\n"
            "    elif isinstance(_d, dict):\n"
            "        _v = _d.get('text/plain') or str(_d)\n"
            "    elif isinstance(_d, (list, tuple)):\n"
            "        _parts = []\n"
            "        for _item in _d:\n"
            "            _m = getattr(_item, 'message', None)\n"
            "            _parts.append(_m if isinstance(_m, str) else str(_item))\n"
            "        _v = '\\n'.join(_parts)\n"
            "    else:\n"
            "        _v = str(_d) if _d is not None else None\n"
            "    if isinstance(_v, str):\n"
            "        if _v.lstrip().startswith('['):\n"
            "            # marimo serialises mimebundle outputs as a JSON array of\n"
            "            # '<mimetype>:<text>' strings — prefer the text/plain entry.\n"
            "            try:\n"
            "                import json as _json\n"
            "                _arr = _json.loads(_v)\n"
            "            except Exception:\n"
            "                _arr = None\n"
            "            if isinstance(_arr, list):\n"
            "                _plain = [str(_x)[len('text/plain:'):] for _x in _arr if isinstance(_x, str) and _x.startswith('text/plain:')]\n"
            "                _v = _plain[0] if _plain else '\\n'.join(str(_x) for _x in _arr)\n"
            "        if _v.startswith('text/plain:'):\n"
            "            _v = _v[len('text/plain:'):]\n"
            "        if _v.lstrip().startswith('<'):\n"
            "            import html as _html, re as _re\n"
            "            _v = _html.unescape(_re.sub(r'<[^>]+>', '', _v)).strip()\n"
            "        return _v\n"
            "    return str(_v) if _v is not None else None\n"
            "_ctx = _cm.get_context()\n"
            "_rows = []\n"
            "for _c in _ctx.cells:\n"
            "    _st = getattr(_c, 'status', None)\n"
            "    _rows.append({\n"
            "        'id': _c.id, 'name': _c.name, 'code': _c.code,\n"
            "        'status': getattr(_st, 'value', None) if _st is not None else None,\n"
            "        'errors': [str(getattr(_e, 'msg', _e))[:300] for _e in (getattr(_c, 'errors', None) or [])][:4],\n"
            "        'output': (_text(_c.output) or '')[:400] if getattr(_c, 'output', None) is not None else None,\n"
            "        'console': [t for t in ((_text(_o) or '')[-4000:] for _o in (getattr(_c, 'console_outputs', None) or [])[-4:]) if t],\n"
            "    })\n"
            "print(_json.dumps(_rows))\n"
        )
        for line in (result.get("log") or "").splitlines():
            line = line.strip()
            if line.startswith("["):
                try:
                    cells = json.loads(line)
                    if isinstance(cells, list):
                        return [c for c in cells if isinstance(c, dict) and str(c.get("name", "")) not in hidden]
                except json.JSONDecodeError:
                    continue
        return []

    # -- cell commands ----------------------------------------------------------

    def run_cells(self, cell_ids: list[str]) -> dict:
        """Queue cells to run (lazy mode: their dependents turn stale)."""
        return self.execute(_driver("\n".join(f"    ctx.run_cell({cell_id!r})" for cell_id in cell_ids)))

    def edit_cell(self, cell_id: str, code: str) -> dict:
        """Replace a cell's code (persisted to the file) and run it."""
        return self.execute(
            "import json as _json\n"
            f"__code = _json.loads({json.dumps(json.dumps(code))})\n"
            + _driver(f"    ctx.edit_cell({cell_id!r}, code=__code)\n    ctx.run_cell({cell_id!r})")
        )

    def save_cell(self, cell_id: str, code: str) -> dict:
        """Replace a cell's code (persisted to the file) without running it."""
        return self.execute(
            "import json as _json\n"
            f"__code = _json.loads({json.dumps(json.dumps(code))})\n"
            + _driver(f"    ctx.edit_cell({cell_id!r}, code=__code)")
        )

    def put_cell(self, code: str, *, cell_id: str | None, run: bool = True) -> str | None:
        """Write *code* into cell *cell_id*, or append a new cell holding it.

        Returns the id of the cell, or ``None`` if the kernel did not answer.
        The cell is run unless *run* is false.
        """
        run_line = "    ctx.run_cell(__id)\n" if run else ""
        if cell_id is not None:
            body = f"    __id = {cell_id!r}\n    ctx.edit_cell(__id, code=__code)\n" + run_line
        else:
            body = (
                "    __last = [c.id for c in ctx.cells]\n"
                "    if __last:\n"
                "        __id = ctx.create_cell(__code, after=__last[-1])\n"
                "    else:\n"
                "        __id = ctx.create_cell(__code)\n" + run_line
            )
        result = self.execute(
            "import json as _json\n"
            f"__code = _json.loads({json.dumps(json.dumps(code))})\n"
            + _driver(body)
            + "print('SCA-CELL', __id)\n"
        )
        for line in (result.get("log") or "").splitlines():
            if line.startswith("SCA-CELL "):
                return line[len("SCA-CELL "):].strip()
        return None

    def delete_cell(self, cell_id: str) -> dict:
        return self.execute(_driver(f"    ctx.delete_cell({cell_id!r})"))

    def insert_cell(self, after: str | None) -> dict:
        """Insert one empty, named cell after *after* (at the top if None).

        The cell carries a comment placeholder — marimo's create_cell drops
        trailing cells when saving an EMPTY-code insertion — and is not
        executed.
        """
        if after:
            create = f"    ctx.create_cell('# new cell', after={after!r}, name=__name)\n"
        else:
            create = (
                "    if __names:\n"
                "        ctx.create_cell('# new cell', before=__names[0], name=__name)\n"
                "    else:\n"
                "        ctx.create_cell('# new cell', name=__name)\n"
            )
        return self.execute(
            _driver(
                "    __names = [c.name for c in ctx.cells]\n"
                "    __name = 'new_cell'\n"
                "    __i = 1\n"
                "    while __name in __names:\n"
                "        __i += 1\n"
                "        __name = f'new_cell_{__i}'\n" + create
            )
        )

    def reload_modules(self, names: list[str]) -> dict:
        """Forget the local modules *names* and run every cell again.

        The notebook's setup cell imported them once; a changed file is seen
        only by a fresh import, so the modules (and their bytecode, which
        Python checks by size and whole-second mtime only) are dropped and
        every cell, the setup cell included, runs against the new files.
        """
        self.execute(
            "import importlib, os, sys\n"
            f"__names = {names!r}\n"
            "for __n in [m for m in sys.modules if m in __names or any(m.startswith(x + '.') for x in __names)]:\n"
            "    __cached = getattr(sys.modules.pop(__n), '__cached__', None)\n"
            "    if isinstance(__cached, str):\n"
            "        try:\n"
            "            os.unlink(__cached)\n"
            "        except OSError:\n"
            "            pass\n"
            "importlib.invalidate_caches()\n"
        )
        return self.execute(
            _driver("    for __c in ctx.cells:\n        ctx.run_cell(__c.id)\n    ctx.run_cell('setup')"),
            timeout=300,
        )

    def stale_cells(self) -> list[str]:
        """Ids of the cells that need a run (inputs changed, code edited)."""
        result = self.execute(
            "import json as _json\n"
            "import marimo._code_mode as _cm\n"
            "_ids = []\n"
            "for _c in _cm.get_context().cells:\n"
            "    _st = getattr(_c, 'status', None)\n"
            "    if _c.name != 'setup' and getattr(_st, 'value', _st) == 'stale':\n"
            "        _ids.append(_c.id)\n"
            "print('SCA-STALE', _json.dumps(_ids))\n"
        )
        for line in (result.get("log") or "").splitlines():
            if line.startswith("SCA-STALE "):
                try:
                    return [str(item) for item in json.loads(line[len("SCA-STALE "):])]
                except json.JSONDecodeError:
                    break
        return []

    def wait_idle(self, timeout: float = 120.0) -> bool:
        """Wait until no cell is queued or running; False on timeout.

        ``run_cell`` only awaits submission; the cells' state is final once
        the kernel goes idle. Poll with short scratch executes (never sleep
        inside the kernel itself).
        """
        probe = (
            "import marimo._code_mode as _cm\n"
            "_busy = [c.name for c in _cm.get_context().cells"
            " if str(getattr(getattr(c, 'status', ''), 'value', getattr(c, 'status', ''))) in ('queued', 'running')]\n"
            "print('SCA-BUSY' if _busy else 'SCA-IDLE')\n"
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "SCA-IDLE" in (self.execute(probe, timeout=15).get("log") or ""):
                return True
            time.sleep(0.2)
        return False

    def run_until_settled(self, cell_ids: list[str], *, rounds: int = 8) -> None:
        """Run *cell_ids*, then every cell that turned stale, until none is.

        Lazy mode marks a run cell's dependents stale instead of running
        them; a parameter change wants the whole chain, so follow up.
        """
        if cell_ids:
            self.run_cells(cell_ids)
            self.wait_idle()
        for _ in range(rounds):
            stale = self.stale_cells()
            if not stale:
                return
            self.run_cells(stale)
            self.wait_idle()

    def publish(self, url: str, step: str = "") -> dict:
        """Have the kernel project its product and POST the package to *url*.

        Returns ``{"ok": True, "id", "kind"}`` or ``{"ok": False, "error"}``;
        a notebook that has not produced its product yet is an error value,
        not an exception.
        """
        result = self.execute(
            "from simplecadapi.runtime.live import publish_live as _publish\n"
            "try:\n"
            f"    _p = _publish({url!r}, step={step!r})\n"
            "    print('SCA-PUBLISHED', _p.definition_id, _p.definition_kind)\n"
            "except Exception as _e:\n"
            "    print('SCA-PUBLISH-ERROR', type(_e).__name__ + ':', str(_e).splitlines()[0] if str(_e) else '')\n",
            timeout=180,
        )
        for line in (result.get("log") or "").splitlines():
            if line.startswith("SCA-PUBLISHED "):
                _, definition_id, kind = line.split(" ", 2)
                return {"ok": True, "id": definition_id, "kind": kind}
            if line.startswith("SCA-PUBLISH-ERROR "):
                return {"ok": False, "error": line[len("SCA-PUBLISH-ERROR "):]}
        return {"ok": False, "error": (result.get("log") or "publishing failed").strip()[-300:]}

    # -- driving --------------------------------------------------------------------

    def execute(self, code: str, timeout: float = 120.0) -> dict:
        """Run a scratch snippet in the kernel; returns {success, output, log}."""
        self._own_calls += 1
        try:
            return self._execute(code, timeout)
        finally:
            self._own_ended = time.monotonic()
            self._own_calls -= 1

    def _execute(self, code: str, timeout: float) -> dict:
        body = json.dumps({"code": code}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.marimo_url}/api/kernel/execute",
            data=body,
            headers={"Content-Type": "application/json", "Marimo-Session-Id": SESSION_ID},
            method="POST",
        )
        result: dict = {"success": None, "output": "", "log": ""}
        with urllib.request.urlopen(request, timeout=timeout) as response:
            event = ""
            for raw in response:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[len("event:"):].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[len("data:"):].strip())
                except json.JSONDecodeError:
                    continue
                if event == "stdout" and isinstance(payload.get("data"), str):
                    result["log"] += payload["data"]
                elif event == "stderr" and isinstance(payload.get("data"), str):
                    result["log"] += payload["data"]
                elif event == "done":
                    result["success"] = bool(payload.get("success", False))
                    output = (payload.get("output") or {}).get("data")
                    if isinstance(output, str):
                        result["output"] = output
        return result

    # -- helpers ----------------------------------------------------------------------

    def _post(self, path: str, payload: dict, timeout: float = 30.0) -> dict:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Marimo-Session-Id": SESSION_ID}
        if self._token is not None:
            headers["Marimo-Server-Token"] = self._token
        request = urllib.request.Request(
            f"{self.marimo_url}{path}", data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
        return json.loads(data) if data else {}


def _driver(inner: str) -> str:
    """A scratch snippet running *inner* (indented lines) in a code-mode batch."""
    return "import marimo._code_mode as cm\nasync with cm.get_context() as ctx:\n" + inner + "\n"


def _free_port(start: int) -> int:
    for port in range(start, start + 32):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise KernelError(f"no free port at or above {start}")

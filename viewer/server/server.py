"""Local HTTP server and agent-handshake CLI for the reverse-engineering studio.

Browser side (human):
    open http://127.0.0.1:<port>/re.html, annotate the STEP target, submit.

Agent side (ZCode / any Bash-capable agent):
    uv run python -m viewer.server <case_dir> --daemon --wait
    ... read re_work/submission.json, reconstruct, write artifacts ...
    uv run python -m viewer.server <case_dir> --wait-only
    uv run python -m viewer.server <case_dir> --shutdown

The handshake mirrors the ppt-master confirm UI: the server is spawned
detached, the agent blocks inside one Bash call polling the submission
counter (budget stays under the Bash tool timeout), and only the human's
browser may write a submission.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .operation_tips import operation_payload
from .runtime import (
    ARTIFACT_NAMES,
    ReCase,
    compose_submission,
    resolve_region,
    write_json_atomic,
)

DEFAULT_PORT = 7170
WAIT_TIMEOUT_DEFAULT = 590
LOCK_NAME = ".re_server.lock"
LOCK_POLL_SECONDS = 0.5
HEALTH_PROBE_TIMEOUT = 15.0

_DIST_DIR = Path(__file__).resolve().parents[1] / "dist"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".map": "application/json",
    ".woff2": "font/woff2",
}


class StudioState:
    """Shared server state; geometry work is serialized on OCP_LOCK."""

    def __init__(self, case: ReCase) -> None:
        self.case = case
        self.started_at = time.time()
        self.ocp_lock = threading.RLock()
        self.scene_state = "idle"
        self.scene_error: str | None = None
        self.scene: Any = None
        self._last_artifact_mtimes: dict[str, float] = {}

    def artifact_snapshot(self) -> dict[str, Any]:
        artifacts: dict[str, Any] = {}
        changed: list[tuple[str, float]] = []
        for name in ARTIFACT_NAMES:
            path = self.case.work / name
            if path.is_file():
                mtime = path.stat().st_mtime
                artifacts[name] = {
                    "present": True,
                    "mtime": mtime,
                    "size": path.stat().st_size,
                }
                if self._last_artifact_mtimes.get(name) != mtime:
                    changed.append((name, mtime))
            else:
                artifacts[name] = {"present": False}
        for name, mtime in changed:
            self._last_artifact_mtimes[name] = mtime
            self.case.append_ndjson("artifact_update", {"artifact": name, "mtime": mtime})
        return artifacts


class StudioHandler(BaseHTTPRequestHandler):
    server: "StudioServer"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write(f"[re-studio] {self.address_string()} {format % args}\n")

    # -- plumbing ---------------------------------------------------------

    def _send_json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        return payload if isinstance(payload, dict) else {}

    # -- routes ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        state = self.server.state
        case = state.case
        if path == "/api/health":
            self._send_json(200, {"ok": True, "pid": os.getpid()})
        elif path == "/api/session":
            self._send_session()
        elif path == "/api/operations":
            self._send_json(200, operation_payload())
        elif path == "/api/scene/original":
            self._send_scene()
        elif path.startswith("/api/entity"):
            self._send_entity(path)
        elif path == "/api/submission":
            if case.submission_path.is_file():
                self._send_bytes(
                    200,
                    case.submission_path.read_bytes(),
                    "application/json; charset=utf-8",
                )
            else:
                self._send_json(404, {"error": "no submission yet"})
        elif path.startswith("/api/artifacts/"):
            self._send_artifact(path.removeprefix("/api/artifacts/"))
        elif path.startswith("/api/"):
            self._send_json(404, {"error": f"unknown endpoint: {path}"})
        else:
            self._send_static(path)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        state = self.server.state
        case = state.case
        if path == "/api/annotate":
            payload = self._read_json()
            raw_events = payload.get("events")
            events: list[Any] = raw_events if isinstance(raw_events, list) else [payload]
            clean: list[dict[str, Any]] = []
            for event in events:
                if isinstance(event, dict) and isinstance(event.get("annotation"), dict):
                    clean.append(
                        {"action": str(event.get("action") or "add"), "annotation": event["annotation"]}
                    )
            case.append_annotations(clean)
            for event in clean:
                case.annotation_event(event["action"], event["annotation"])
            self._send_json(200, {"recorded": len(clean)})
        elif path == "/api/event":
            payload = self._read_json()
            case.append_ndjson(str(payload.pop("type", "ui")), payload)
            self._send_json(200, {"ok": True})
        elif path == "/api/region/resolve":
            self._resolve_region()
        elif path == "/api/submit":
            self._submit()
        elif path == "/api/shutdown":
            self._send_json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send_json(404, {"error": f"unknown endpoint: {path}"})

    # -- handlers ----------------------------------------------------------

    def _send_session(self) -> None:
        state = self.server.state
        case = state.case
        target = case.target_path
        submission: dict[str, Any] | None = None
        if case.submission_path.is_file():
            try:
                record = json.loads(case.submission_path.read_text(encoding="utf-8"))
                submission = {
                    "seq": record.get("submission_seq"),
                    "submitted_at": record.get("submitted_at"),
                }
            except (OSError, ValueError):
                submission = None
        scene: dict[str, Any] = {"state": state.scene_state, "error": state.scene_error}
        if state.scene is not None:
            model = state.scene.model
            scene.update(
                {
                    "face_count": len(model.faces),
                    "edge_count": len(model.edges),
                    "vertex_count": len(model.vertices),
                    "body_count": len(model.bodies),
                }
            )
        self._send_json(
            200,
            {
                "server": {
                    "pid": os.getpid(),
                    "port": self.server.server_address[1],
                    "started_at": state.started_at,
                },
                "target": {
                    "name": target.name if target else None,
                    "path": str(target) if target else None,
                    "present": target is not None,
                },
                "scene": scene,
                "annotations": case.annotation_count(),
                "submission": submission,
                "artifacts": state.artifact_snapshot(),
            },
        )

    def _send_scene(self) -> None:
        import base64

        state = self.server.state
        with state.ocp_lock:
            if state.scene_state == "building":
                self._send_json(503, {"error": "scene is still building"})
                return
            if state.scene_state == "ready" and state.scene is not None:
                scene = state.scene
            else:
                target = state.case.target_path
                if target is None:
                    self._send_json(409, {"error": "case has no STEP target"})
                    return
                state.scene_state = "building"
                state.scene_error = None
                try:
                    from .scene_build import build_step_scene

                    scene = build_step_scene(target)
                    state.scene = scene
                    state.scene_state = "ready"
                    state.case.append_ndjson(
                        "scene_built",
                        {
                            "target": str(target),
                            "faces": len(scene.model.faces),
                            "edges": len(scene.model.edges),
                            "vertices": len(scene.model.vertices),
                        },
                    )
                except Exception as exc:
                    state.scene_state = "error"
                    state.scene_error = str(exc)
                    self._send_json(500, {"error": str(exc)})
                    return
        self._send_json(
            200,
            {
                "schema_version": "2.0",
                "summary": scene.summary,
                "files": {
                    uri: base64.b64encode(payload).decode("ascii")
                    for uri, payload in scene.files.items()
                },
            },
        )

    def _send_entity(self, path: str) -> None:
        from urllib.parse import parse_qs, urlparse

        state = self.server.state
        query = parse_qs(urlparse(self.path).query)
        entity_id = (query.get("id") or [""])[0]
        if not entity_id:
            self._send_json(400, {"error": "missing ?id=<canonical entity id>"})
            return
        with state.ocp_lock:
            if state.scene is None:
                self._send_json(409, {"error": "scene is not built yet"})
                return
            try:
                descriptor = state.scene.model.describe_entity(entity_id)
            except Exception as exc:
                self._send_json(404, {"error": str(exc)})
                return
        self._send_json(200, descriptor)

    def _resolve_region(self) -> None:
        payload = self._read_json()
        camera = payload.get("camera")
        polygon = payload.get("polygon")
        state = self.server.state
        with state.ocp_lock:
            if state.scene is None:
                self._send_json(409, {"error": "scene is not built yet"})
                return
            if (
                not isinstance(camera, dict)
                or not isinstance(polygon, list)
                or len(polygon) < 3
            ):
                self._send_json(400, {"error": "camera and polygon (>=3 points) are required"})
                return
            try:
                result = resolve_region(state.scene.anchors, camera, polygon)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
        state.case.append_ndjson(
            "region_resolve",
            {"entity_ids": result["entity_ids"][:32], "count": result["count"]},
        )
        self._send_json(200, result)

    def _submit(self) -> None:
        payload = self._read_json()
        state = self.server.state
        with state.ocp_lock:
            if state.scene is None:
                self._send_json(409, {"error": "scene is not built yet"})
                return
            try:
                submission = compose_submission(
                    state.case,
                    state.scene.model.describe_entity,
                    state.scene.summary,
                    payload,
                    adjacency=state.scene.model.adjacency_details,
                )
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
                return
        self._send_json(
            200,
            {
                "seq": submission["submission_seq"],
                "submitted_at": submission["submitted_at"],
                "annotation_count": len(submission["annotations"]),
                "path": str(state.case.submission_path),
            },
        )

    def _send_artifact(self, name: str) -> None:
        if name not in ARTIFACT_NAMES:
            self._send_json(404, {"error": f"unknown artifact: {name}"})
            return
        path = self.server.state.case.work / name
        if not path.is_file():
            self._send_json(404, {"error": f"artifact not produced yet: {name}"})
            return
        content_type = _CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        if path.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        self._send_bytes(200, path.read_bytes(), content_type)

    def _send_static(self, path: str) -> None:
        if not _DIST_DIR.is_dir():
            self._send_bytes(
                200,
                (
                    "<html><body style='font-family: sans-serif; background: #0b0e12; "
                    "color: #dfe7f1; padding: 2rem'><h2>re-studio server is running</h2>"
                    "<p>No built frontend found. Either <code>npm run build</code> in "
                    "<code>viewer/</code>, or use the vite dev server "
                    "(<code>npm run dev</code>) which proxies <code>/api</code> to this port.</p>"
                    "</body></html>"
                ).encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return
        relative = path.lstrip("/") or "index.html"
        if relative == "re":
            relative = "re.html"
        target = (_DIST_DIR / relative).resolve()
        if not str(target).startswith(str(_DIST_DIR.resolve())) or not target.is_file():
            self._send_json(404, {"error": f"not found: {path}"})
            return
        content_type = _CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send_bytes(200, target.read_bytes(), content_type)


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: StudioState) -> None:
        super().__init__(address, StudioHandler)
        self.state = state


# -- CLI handshake -----------------------------------------------------------


def _lock_path(case: ReCase) -> Path:
    return case.root / LOCK_NAME


def _read_lock(case: ReCase) -> dict[str, Any] | None:
    try:
        return json.loads(_lock_path(case).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _probe_health(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=timeout
        ) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _build_scene_background(state: "StudioState") -> None:
    target = state.case.target_path
    if target is None:
        return
    with state.ocp_lock:
        if state.scene_state != "idle":
            return
        state.scene_state = "building"
        try:
            from .scene_build import build_step_scene

            scene = build_step_scene(target)
            state.scene = scene
            state.scene_state = "ready"
            state.case.append_ndjson(
                "scene_built",
                {
                    "target": str(target),
                    "faces": len(scene.model.faces),
                    "edges": len(scene.model.edges),
                    "vertices": len(scene.model.vertices),
                },
            )
        except Exception as exc:
            state.scene_state = "error"
            state.scene_error = str(exc)
            state.case.append_ndjson("scene_error", {"error": str(exc)})


def _serve(case: ReCase, port: int) -> int:
    state = StudioState(case)
    server = StudioServer(("127.0.0.1", port), state)
    write_json_atomic(
        _lock_path(case), {"pid": os.getpid(), "port": server.server_address[1]}
    )
    case.append_ndjson(
        "server_start",
        {"pid": os.getpid(), "port": server.server_address[1], "target": str(case.target_path)},
    )
    threading.Thread(target=_build_scene_background, args=(state,), daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        case.append_ndjson("server_stop", {"pid": os.getpid()})
    return 0


def _daemon(case: ReCase, port: int, open_browser: bool) -> int:
    lock = _read_lock(case)
    if (
        lock
        and _pid_alive(int(lock.get("pid", 0)))
        and _probe_health(int(lock.get("port", port)))
    ):
        print(f"[re-studio] server already running: http://127.0.0.1:{lock['port']}/re.html")
        return 0
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "viewer.server",
            str(case.root),
            "--serve",
            "--port",
            str(port),
        ],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + HEALTH_PROBE_TIMEOUT
    while time.monotonic() < deadline:
        if _probe_health(port):
            break
        if child.poll() is not None:
            print("[re-studio] server child exited during startup", file=sys.stderr)
            return 1
        time.sleep(0.25)
    else:
        print("[re-studio] server did not become healthy in time", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{port}/re.html"
    print(f"[re-studio] serving {url} (case: {case.root})")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return 0


def _wait_for_submission(case: ReCase, port: int, timeout: float) -> int:
    baseline = case.read_submission_seq()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(LOCK_POLL_SECONDS)
        if not _probe_health(port):
            print("[re-studio] server died while waiting", file=sys.stderr)
            return 1
        if case.read_submission_seq() > baseline:
            print(f"[re-studio] submission ready: {case.submission_path}")
            return 0
    print(
        f"[re-studio] timed out after {timeout:.0f}s waiting for a submission",
        file=sys.stderr,
    )
    return 124


def _shutdown(case: ReCase, port: int) -> int:
    lock = _read_lock(case)
    port = int(lock.get("port", port)) if lock else port
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/shutdown", data=b"{}", method="POST"
    )
    try:
        urllib.request.urlopen(request, timeout=2.0)
    except (urllib.error.URLError, OSError):
        pass
    pid = int(lock.get("pid", 0)) if lock else 0
    if _pid_alive(pid):
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(0.2)
        if _pid_alive(pid):
            try:
                os.kill(pid, 15)
            except OSError:
                pass
    try:
        _lock_path(case).unlink()
    except OSError:
        pass
    print("[re-studio] server shut down")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="viewer.server", description=__doc__)
    parser.add_argument("case_dir", help="case directory containing the STEP target")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--serve", action="store_true", help="run the HTTP server in the foreground")
    parser.add_argument("--daemon", action="store_true", help="spawn the detached server and open the UI")
    parser.add_argument("--wait", action="store_true", help="block until a fresh submission lands")
    parser.add_argument("--wait-only", action="store_true", help="re-attach and wait without spawning")
    parser.add_argument("--timeout", type=float, default=WAIT_TIMEOUT_DEFAULT)
    parser.add_argument("--shutdown", action="store_true", help="stop a running server")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    try:
        case = ReCase.open_case(args.case_dir)
    except FileNotFoundError as exc:
        print(f"[re-studio] {exc}", file=sys.stderr)
        return 2

    if args.shutdown:
        return _shutdown(case, args.port)
    if args.serve:
        return _serve(case, args.port)
    if args.daemon:
        code = _daemon(case, args.port, not args.no_browser)
        if code != 0:
            return code
        if args.wait:
            return _wait_for_submission(case, args.port, args.timeout)
        return 0
    if args.wait_only:
        lock = _read_lock(case)
        port = int(lock.get("port", args.port)) if lock else args.port
        if not _probe_health(port):
            print(
                "[re-studio] server is not running; start it with --daemon first",
                file=sys.stderr,
            )
            return 1
        return _wait_for_submission(case, port, args.timeout)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

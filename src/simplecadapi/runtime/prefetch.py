"""Run the notebooks a cell uses side by side.

OpenCASCADE does not let go of the interpreter lock (two threads building
the same kind of model are no faster than one), so the parallelism is in
processes.  When a cell is about to run, the ``use`` calls it is going to make
that can be told beforehand (:func:`plan_uses`: literal paths, arguments made
of values the cell reads) are handed to worker processes.  A worker runs the
notebook headlessly, which fills its cell cache; the cell then makes its
``use`` calls as it always did, waits for the worker of each (:func:`wait`),
and finds the notebook built.  Nothing about the result depends on the
workers: a failed or missing one only means the call runs the notebook itself.

``SCA_JOBS`` sets how many workers (default: the smaller of 4 and the number
of cores; 1 turns this off).  A notebook that has not changed since it last
ran, with the same overrides, is not started: it is in the cache already.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import pickle
import struct
import subprocess
import sys
import threading
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..artifacts.canonical import validate_logical_id
from .children import notebook_digest
from .config import read_notebook_config
from .deps import state_dir, use_calls

# ---------------------------------------------------------------------------
# What a cell is going to use
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UseRequest:
    path: Path
    id: str | None
    overrides: Mapping[str, Any]

    @property
    def key(self) -> tuple[str, str | None, str]:
        return request_key(self.path, self.id, self.overrides)


def request_key(path: Path, id: str | None, overrides: Mapping[str, Any]) -> tuple[str, str | None, str]:
    return (str(Path(path).resolve()), id, repr(sorted(overrides.items(), key=lambda item: item[0])))


class _Unknown(Exception):
    """An expression the plan cannot evaluate before the cell runs."""


_CALLS = {"float": float, "int": int, "str": str, "bool": bool, "round": round, "abs": abs, "min": min, "max": max}
_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}
_COMPARE = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}
_NOT_RUN_HERE = (
    ast.IfExp, ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.FunctionDef,
    ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda, ast.ListComp, ast.SetComp,
    ast.DictComp, ast.GeneratorExp, ast.Match,
)  # fmt: skip


def _evaluate(node: ast.expr, scope: Mapping[str, Any], notebook_id: str | None = None) -> Any:
    """The value of *node*, for the few expression forms a plan can trust."""

    if isinstance(node, ast.Constant):
        return node.value
    if (
        isinstance(node, ast.Call)
        and not node.args
        and not node.keywords
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "notebook_id")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "notebook_id")
        )
    ):
        if notebook_id is None:
            raise _Unknown
        return notebook_id
    if isinstance(node, ast.Name):
        if node.id in scope:
            return scope[node.id]
        raise _Unknown
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
        value = _evaluate(node.operand, scope, notebook_id)
        return {ast.USub: lambda: -value, ast.UAdd: lambda: +value, ast.Not: lambda: not value}[type(node.op)]()
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _BINARY[type(node.op)](_evaluate(node.left, scope, notebook_id), _evaluate(node.right, scope, notebook_id))
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
        return _COMPARE[type(node.ops[0])](_evaluate(node.left, scope, notebook_id), _evaluate(node.comparators[0], scope, notebook_id))
    if isinstance(node, ast.IfExp):
        return _evaluate(node.body if _evaluate(node.test, scope, notebook_id) else node.orelse, scope, notebook_id)
    if isinstance(node, (ast.Tuple, ast.List)):
        items = [_evaluate(item, scope, notebook_id) for item in node.elts]
        return tuple(items) if isinstance(node, ast.Tuple) else items
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _CALLS
        and node.func.id not in scope
        and not node.keywords
    ):
        return _CALLS[node.func.id](*[_evaluate(arg, scope, notebook_id) for arg in node.args])
    raise _Unknown


def plan_uses(
    code: str, scope: Mapping[str, Any], directory: Path, notebook_id: str | None = None
) -> list[UseRequest]:
    """The ``use`` calls *code* will make that are known before it runs.

    A call counts when its path is a literal and every argument can be worked
    out from *scope* (the values the cell reads) with arithmetic and
    ``float(...)``-like calls; and when the cell is certain to make it (not
    under a condition, in a loop or in a function).
    """

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    requests: dict[tuple[str, str | None, str], UseRequest] = {}

    def visit(node: ast.AST) -> None:
        if isinstance(node, _NOT_RUN_HERE):
            return
        if isinstance(node, ast.Call) and _is_use(node):
            request = _request(node, scope, directory, notebook_id)
            if request is not None:
                requests.setdefault(request.key, request)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return list(requests.values())


def _is_use(node: ast.Call) -> bool:
    function = node.func
    return (isinstance(function, ast.Name) and function.id == "use") or (
        isinstance(function, ast.Attribute) and function.attr == "use"
    )


def _request(
    node: ast.Call, scope: Mapping[str, Any], directory: Path, notebook_id: str | None
) -> UseRequest | None:
    if not node.args or not (isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
        return None
    if len(node.args) != 1 or any(keyword.arg is None for keyword in node.keywords):
        return None
    try:
        values = {keyword.arg: _evaluate(keyword.value, scope, notebook_id) for keyword in node.keywords}
    except Exception:  # noqa: BLE001 - anything wrong here only means "not planned"
        return None
    child_id = values.pop("id", None)
    if child_id is not None and not isinstance(child_id, str):
        return None
    path = Path(node.args[0].value)
    return UseRequest((path if path.is_absolute() else directory / path).resolve(), child_id, values)


# ---------------------------------------------------------------------------
# Has the notebook changed since it last ran?
# ---------------------------------------------------------------------------


def _signature(path: Path, config_id: str, overrides: Mapping[str, Any]) -> str | None:
    digest = notebook_digest(path)
    if digest is None:
        return None
    payload = repr((digest, config_id, sorted(overrides.items(), key=lambda item: item[0])))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _stamp_file(config: Any) -> Path:
    return state_dir(config) / "stamp.json"


def _read_stamp(config: Any) -> dict[str, Any]:
    try:
        data = json.loads(_stamp_file(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_stamp(config: Any, overrides: Mapping[str, Any], seconds: float | None = None) -> None:
    """Record that *config*'s notebook has just run to the end with *overrides*.

    *seconds* is how long the run took when it built something; a run that
    only restored keeps the figure of the last build (it says what the
    notebook costs, which is what decides whether a worker is worth it).
    """

    signature = _signature(config.path, config.id, overrides)
    target = _stamp_file(config)
    try:
        if signature is None:
            target.unlink(missing_ok=True)
            return
        previous = _read_stamp(config)
        if seconds is None:
            seconds = previous.get("seconds")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"signature": signature, "seconds": seconds}), encoding="utf-8")
    except OSError:
        pass  # the stamp only saves work


def _expected_seconds(request: UseRequest) -> float | None:
    """How long the notebook has to be built, if it has to be: ``None`` when it
    does not (it is in the cache), ``inf`` when nobody knows how long."""

    config = read_notebook_config(request.path)
    if config is None:
        return None  # the call itself will say what is wrong with it
    try:
        if request.id is not None:
            config = replace(config, id=validate_logical_id(request.id, "/run/id"))
    except Exception:  # noqa: BLE001
        return None
    signature = _signature(config.path, config.id, request.overrides)
    stamp = _read_stamp(config)
    if signature is not None and stamp.get("signature") == signature:
        return None
    seconds = stamp.get("seconds")
    return float(seconds) if isinstance(seconds, (int, float)) else float("inf")


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

_COLD_WORTH = 4.0
"""Seconds a start of the workers has to save to be done (a worker imports the
kernel libraries: a few seconds)."""
_WARM_WORTH = 0.5
"""...and once they are running."""

_stats: dict[str, list[str]] = {"submitted": []}
_pending: dict[tuple[str, str | None, str], Future[None]] = {}
_lock = threading.Lock()
_pool: _Pool | None = None


def jobs() -> int:
    raw = os.environ.get("SCA_JOBS")
    if raw is not None:
        try:
            return max(1, int(raw))
        except ValueError:
            return 1
    return max(1, min(4, os.cpu_count() or 1))


def stats() -> dict[str, list[str]]:
    return {"submitted": list(_stats["submitted"])}


def reset_stats() -> None:
    _stats["submitted"].clear()


def start(directory: Path, code: str, scope: Mapping[str, Any], notebook_id: str | None = None) -> None:
    """Hand the ``use`` calls of a cell about to run to the workers."""

    global _pool
    size = jobs()
    if size < 2 or "use" not in code:
        return
    if not use_calls(code):
        return
    planned = [(request, _expected_seconds(request)) for request in plan_uses(code, scope, directory, notebook_id)]
    wanted = [(request, seconds) for request, seconds in planned if seconds is not None]
    if len(wanted) < 2:
        return  # nothing to do beside the cell's own first call
    # The longest build goes on in this process; what the workers take off its
    # hands has to be worth more than starting them.
    seconds = sorted((value for _, value in wanted), reverse=True)
    saved = sum(seconds[1:])
    if saved < (_WARM_WORTH if _pool is not None and _pool.size == size else _COLD_WORTH):
        return
    requests = [request for request, _ in wanted]
    with _lock:
        if _pool is None or _pool.size != size:
            _pool = _Pool(size)
        for request in requests:
            existing = _pending.get(request.key)
            if existing is not None and not existing.done():
                continue
            _pending[request.key] = _pool.submit(request)
            _stats["submitted"].append(str(request.path))


def wait(path: Path, id: str | None, overrides: Mapping[str, Any]) -> None:
    """Wait for the worker that is building this notebook, if one is."""

    with _lock:
        future = _pending.pop(request_key(path, id, overrides), None)
    if future is not None:
        try:
            future.result()
        except Exception:  # noqa: BLE001 - the call runs the notebook and reports for itself
            pass


def shutdown() -> None:
    global _pool
    with _lock:
        pool, _pool = _pool, None
        _pending.clear()
    if pool is not None:
        pool.close()


class _Pool:
    """Threads that each own a worker process, started when first needed."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._executor = ThreadPoolExecutor(size, thread_name_prefix="sca-prefetch")
        self._local = threading.local()
        self._workers: list[subprocess.Popen[bytes]] = []
        self._workers_lock = threading.Lock()

    def submit(self, request: UseRequest) -> Future[None]:
        return self._executor.submit(self._run, request)

    def _run(self, request: UseRequest) -> None:
        worker = getattr(self._local, "worker", None)
        if worker is None or worker.poll() is not None:
            worker = self._local.worker = self._spawn()
        try:
            _send(worker.stdin, (str(request.path), request.id, dict(request.overrides)))  # type: ignore[arg-type]
            reply = _receive(worker.stdout)  # type: ignore[arg-type]
        except Exception:
            self._local.worker = None
            worker.kill()
            raise
        if reply[0] != "ok":
            raise RuntimeError(reply[1])

    def _spawn(self) -> subprocess.Popen[bytes]:
        worker = subprocess.Popen(
            [sys.executable, "-m", "simplecadapi.runtime._prefetch_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SCA_JOBS": "1"},  # a worker does not start workers
        )
        with self._workers_lock:
            self._workers.append(worker)
        return worker

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        with self._workers_lock:
            workers, self._workers = self._workers, []
        for worker in workers:
            try:
                worker.kill()
            except OSError:
                pass


def _send(stream: Any, value: Any) -> None:
    data = pickle.dumps(value)
    stream.write(struct.pack(">Q", len(data)) + data)
    stream.flush()


def _receive(stream: Any) -> Any:
    header = stream.read(8)
    if len(header) < 8:
        raise EOFError("the worker ended")
    (size,) = struct.unpack(">Q", header)
    return pickle.loads(stream.read(size))


__all__ = [
    "UseRequest",
    "jobs",
    "plan_uses",
    "request_key",
    "reset_stats",
    "shutdown",
    "start",
    "stats",
    "wait",
    "write_stamp",
]

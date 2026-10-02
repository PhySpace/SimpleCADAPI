"""What a notebook depends on outside its cells, and the digest *D* of it.

marimo keys a cell's cache entry by the cell's code and the values it
reads.  It cannot see three kinds of dependency a SimpleCAD notebook has:

* local modules — Python files under the notebook's directory that the
  cells import (library parts, shared helpers), and the local modules
  those import in turn.  They are found statically, from the ``import``
  statements (:func:`local_modules`), so the answer does not depend on
  what else the process has imported, nor on which cells ran.  Imports
  made through ``importlib`` or ``__import__`` are not seen;
* child notebooks run with :func:`simplecadapi.runtime.use`, together with
  everything they depend on in turn.  Only a run can tell which (the path
  is an argument), so a run records them for the next one, in
  ``deps.json`` in the notebook's :func:`state_dir`;
* the project files listed in ``[tool.simplecadapi] inputs``.

*D* digests the current content of all these files, together with the
versions of the software that writes the cache, and a run uses the cell
cache stored under *D* only.  Any change to any of these files therefore
invalidates the notebook's whole cache: coarse, but never stale.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType

import marimo

from ..artifacts.canonical import canonical_bytes
from ..build.keys import generator_profile
from ._marimo import notebook_output_dir
from .config import NotebookConfig

_SCHEMA = 1

_recorded_var: ContextVar[set[Path] | None] = ContextVar(
    "simplecadapi_runtime_dependencies", default=None
)


# ---------------------------------------------------------------------------
# Files a run reports (child notebooks)
# ---------------------------------------------------------------------------


@contextmanager
def recording_dependencies() -> Iterator[set[Path]]:
    """Collect the files :func:`record_dependencies` reports in this block."""

    recorded: set[Path] = set()
    token = _recorded_var.set(recorded)
    try:
        yield recorded
    finally:
        _recorded_var.reset(token)


def record_dependencies(paths: Iterable[Path]) -> None:
    """Report files the running notebook depends on (``use`` does this)."""

    recorded = _recorded_var.get()
    if recorded is not None:
        recorded.update(path.resolve() for path in paths)


def state_dir(config: NotebookConfig) -> Path:
    """Where the runtime keeps the notebook's state between runs.

    That is ``__marimo__/simplecad/<notebook file name>/<id>``: notebooks in
    one directory share marimo's output directory, not their state, and the
    members of a part family (one notebook run under several ids, which
    cells read through :func:`~simplecadapi.runtime.notebook_id`) keep
    theirs apart.
    """

    return notebook_output_dir(config.path) / "simplecad" / config.path.name / config.id


def deps_file(config: NotebookConfig) -> Path:
    return state_dir(config) / "deps.json"


def read_dependencies(config: NotebookConfig) -> frozenset[Path]:
    """Return the files the last run recorded; none if it left no record."""

    try:
        data = json.loads(deps_file(config).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return frozenset()
    if not isinstance(data, dict) or data.get("schema") != _SCHEMA:
        return frozenset()
    files = data.get("files")
    if not isinstance(files, list):
        return frozenset()
    return frozenset(
        (config.directory / item).resolve() for item in files if isinstance(item, str)
    )


def write_dependencies(config: NotebookConfig, files: Iterable[Path]) -> None:
    path = deps_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": _SCHEMA, "files": sorted(_display(config, item) for item in files)}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Local modules
# ---------------------------------------------------------------------------


def local_modules(config: NotebookConfig, codes: Iterable[str]) -> dict[str, Path]:
    """Return the local modules that cells with *codes* import, name → file.

    A module is local when Python, with the notebook's directory first on
    ``sys.path`` (as the notebook runs), finds it in a file under that
    directory.  The packages an import executes count too, and so, however
    deep, do the local modules local modules import.  The notebook itself
    and marimo's output directory never count.
    """

    root = config.directory
    output = notebook_output_dir(config.path)
    found: dict[str, Path] = {}
    # (source, package its relative imports resolve against)
    pending: list[tuple[str, str]] = [(code, "") for code in codes]
    while pending:
        source, package = pending.pop()
        for imported in _imported_names(source, package):
            for name, path in _module_files(root, imported):
                if name in found or path == config.path or path.is_relative_to(output):
                    continue
                found[name] = path
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue  # still a dependency; its imports are unknown
                is_package = path.name == "__init__.py"
                pending.append((text, name if is_package else name.rpartition(".")[0]))
    return found


_loaded: dict[str, tuple[Path, str | None]] = {}
"""Local modules (file, digest) as a run last imported them, by name."""

_loaded_lock = threading.Lock()


def refresh_local_modules(modules: Mapping[str, Path]) -> None:
    """Make the notebook's imports see its local *modules* as they are now.

    Python imports a module once per process, so a notebook run again in
    the same process (by an agent, or through ``use``) would get a local
    module as it was the first time, or a module of the same name from
    another project.  Such modules, and their submodules, are dropped from
    ``sys.modules`` so the run imports them afresh.  A module whose file is
    unchanged since the last run stays, so a nested run and its parent
    share its classes.  Standard-library and installed modules are never
    dropped, even when a local file shadows their name.

    A dropped module's bytecode goes too: Python checks a ``.pyc`` against
    its source's size and whole-second mtime only, so an edit that keeps
    the size, made within the second, would otherwise import the old code.
    """

    with _loaded_lock:
        for name, path in modules.items():
            state = (path, _file_digest(path))
            module = sys.modules.get(name)
            if module is not None and _loaded.get(name) != state and _replaceable(name, module):
                for loaded in [item for item in sys.modules if item == name or item.startswith(name + ".")]:
                    _drop_bytecode(sys.modules.pop(loaded))
            _loaded[name] = state


def _drop_bytecode(module: ModuleType) -> None:
    cached = getattr(module, "__cached__", None)
    if isinstance(cached, str):
        try:
            os.unlink(cached)
        except OSError:
            pass  # never written, or already gone


def _replaceable(name: str, module: ModuleType) -> bool:
    if name.partition(".")[0] in sys.stdlib_module_names:
        return False
    filename = getattr(module, "__file__", None)
    if not isinstance(filename, str):
        return False  # built in, or a namespace package: nothing to reload
    installed = {sys.prefix, sys.base_prefix, sys.exec_prefix}
    return not any(Path(filename).resolve().is_relative_to(Path(prefix).resolve()) for prefix in installed)


def _imported_names(source: str, package: str) -> Iterator[str]:
    """Yield the absolute dotted names the imports in *source* load.

    ``from a import b`` yields ``a`` and ``a.b``, since ``b`` may be a
    submodule.  Relative imports resolve against *package*.
    """

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node.module, node.level, package)
            if base is None:
                continue
            yield base
            for alias in node.names:
                if alias.name != "*":
                    yield f"{base}.{alias.name}"


def _absolute(module: str | None, level: int, package: str) -> str | None:
    """The absolute name of ``from <level dots><module> import ...``."""

    if level == 0:
        return module
    parts = package.split(".") if package else []
    if level - 1 > len(parts):
        return None  # beyond the top-level package: Python rejects it too
    base = parts[: len(parts) - (level - 1)]
    if module:
        base.append(module)
    return ".".join(base) or None


def _module_files(root: Path, name: str) -> list[tuple[str, Path]]:
    """The modules under *root* that importing module *name* executes: the
    packages on the way, then the module itself."""

    files: list[tuple[str, Path]] = []
    directory = root
    *packages, last = name.split(".")
    for index, part in enumerate(packages):
        directory = directory / part
        if not directory.is_dir():
            return files
        init = directory / "__init__.py"
        if init.is_file():
            files.append((".".join(packages[: index + 1]), init.resolve()))
    for candidate in (directory / f"{last}.py", directory / last / "__init__.py"):
        if candidate.is_file():
            files.append((name, candidate.resolve()))
            break
    return files


# ---------------------------------------------------------------------------
# The digest
# ---------------------------------------------------------------------------


def input_files(config: NotebookConfig) -> frozenset[Path]:
    return frozenset((config.directory / item.path).resolve() for item in config.inputs)


def dependency_digest(config: NotebookConfig, files: Iterable[Path]) -> str:
    """Return *D* for *files* and the inputs as they are now: 16 hex digits.

    A missing file digests as missing, so deleting one invalidates too.
    """

    contents = {
        _display(config, path): _file_digest(path)
        for path in set(files) | input_files(config)
    }
    payload = {
        "schema": _SCHEMA,
        "generator": dict(generator_profile()),
        "marimo": marimo.__version__,
        "files": contents,
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()[:16]


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _display(config: NotebookConfig, path: Path) -> str:
    """*path* relative to the notebook, so a moved project keeps its cache."""

    try:
        return Path(os.path.relpath(path, config.directory)).as_posix()
    except ValueError:  # another drive on Windows
        return path.as_posix()


__all__ = [
    "dependency_digest",
    "deps_file",
    "input_files",
    "local_modules",
    "read_dependencies",
    "record_dependencies",
    "recording_dependencies",
    "refresh_local_modules",
    "state_dir",
    "write_dependencies",
]

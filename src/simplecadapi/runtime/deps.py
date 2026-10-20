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
invalidates the cache of the cells that depend on it: coarse, but never
stale.  A name a cell imports with ``from m import x`` is the exception: it
is a dependency on the definition of ``x`` (:mod:`.names`), and falls back
to the file when that cannot be digested.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import threading
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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

    found: dict[str, Path] = {}
    # (source, package its relative imports resolve against)
    _follow_imports(config, [(code, "") for code in codes], found)
    return found


def _follow_imports(
    config: NotebookConfig, pending: list[tuple[str, str]], found: dict[str, Path]
) -> None:
    """Add to *found* every local module the imports in *pending* sources reach."""

    root = config.directory
    output = notebook_output_dir(config.path)
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
            state = (path, file_digest(path))
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
# What each cell depends on
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CellSource:
    """A cell as the dependency analysis needs it."""

    key: str
    code: str
    refs: frozenset[str]
    """The names the cell reads (marimo's ``cell.refs``)."""
    defs: frozenset[str]
    """The names the cell defines (marimo's ``cell.defs``)."""


@dataclass(frozen=True)
class NameDep:
    """A dependency on one name a cell imports from a local module.

    ``from lib.dims import A`` depends on the definition of ``A`` (see
    :mod:`.names`), not on the file; *fallback* is the files it depends on
    instead when that definition cannot be digested.
    """

    module: str
    name: str
    fallback: frozenset[Path]


@dataclass(frozen=True)
class CellDeps:
    """What a cell depends on outside its code."""

    files: frozenset[Path]
    names: frozenset[NameDep] = frozenset()

    def __or__(self, other: CellDeps) -> CellDeps:
        return CellDeps(self.files | other.files, self.names | other.names)


def cell_module_files(
    config: NotebookConfig,
    setup: str | None,
    cells: Sequence[CellSource],
    recorded: Iterable[Path] = (),
) -> dict[str, CellDeps]:
    """Return, per cell key, what its result depends on in local files.

    Names imported with ``from m import x`` from a local module are
    dependencies on that name (:class:`NameDep`); every other dependency is
    on whole files.  What follows describes the files.

    A cell depends on a local module when it reads a name that an ``import``
    in the notebook (the setup cell, or any cell) bound to that module, or
    calls a function the notebook defines (an ``@app.function`` cell, a
    ``def`` in the setup cell) that reads such a name; and on every local
    module that module imports in turn.  It also depends on whatever the cells
    it reads from depend on: marimo keys a cell that reads an object (a solid,
    a part) by the code of the cells that made it, not by its value, so it
    cannot see a module that changed upstream.  A cell that calls ``use`` also
    depends on everything the last run recorded (the child notebooks, which
    only a run can name, and what they depend on): *recorded*.

    Reading a name never imported (a standard-library or installed module) adds
    nothing: those are pinned by the software versions in the digest.
    """

    root = config.directory
    sources = ([setup] if setup else []) + [cell.code for cell in cells]
    bound: dict[str, set[tuple[str, Path]]] = {}
    for source in sources:
        for name, modules in _import_bindings(root, source).items():
            bound.setdefault(name, set()).update(modules)
    star = bound.pop("*", set())
    fine = _from_imports(root, sources)

    closures: dict[tuple[str, Path], frozenset[Path]] = {}

    def closure(module: tuple[str, Path]) -> frozenset[Path]:
        if module not in closures:
            name, path = module
            found: dict[str, Path] = {name: path}
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                text = ""
            package = name if path.name == "__init__.py" else name.rpartition(".")[0]
            _follow_imports(config, [(text, package)], found)
            closures[module] = frozenset(found.values())
        return closures[module]

    # Names each function or class of the notebook reads.
    reads: dict[str, set[str]] = {}
    for source in sources:
        for name, loaded in _definitions(source).items():
            reads.setdefault(name, set()).update(loaded)

    def reach(name: str, seen: set[str]) -> set[str]:
        """The imported names the notebook function *name* reads, through other functions too."""
        if name in seen:
            return set()
        seen.add(name)
        imported: set[str] = set()
        for read in reads.get(name, ()):
            if read in bound:
                imported.add(read)
            elif read in reads:
                imported |= reach(read, seen)
        return imported

    star_files = frozenset(path for module in star for path in closure(module))
    recorded_files = frozenset(recorded)
    result: dict[str, CellDeps] = {}
    for cell in cells:
        names = set(cell.refs) | (cell.defs & bound.keys()) | _loaded_names(cell.code)
        needed: set[str] = set()
        for name in names:
            if name in bound:
                needed.add(name)
            if name in reads:
                needed |= reach(name, set())
        for name in cell.defs & reads.keys():
            needed |= reach(name, set())
        files: set[Path] = set(star_files)
        named: set[NameDep] = set()
        for name in needed:
            coarse: set[Path] = set()
            for module in bound.get(name, ()):
                coarse |= closure(module)
            if name in fine:
                module_name, original = fine[name]
                named.add(NameDep(module_name, original, frozenset(coarse)))
            else:
                files |= coarse
        if calls_use(cell.code):
            files |= recorded_files
        result[cell.key] = CellDeps(frozenset(files), frozenset(named))

    # marimo keys a cell that reads an object (a solid, a part) by the code of
    # the cells that made it, not by its value: a file an ancestor depends on
    # is one this cell depends on.
    reached = ancestors(cells)
    merged: dict[str, CellDeps] = {}
    for cell in cells:
        deps = result[cell.key]
        for key in reached[cell.key]:
            deps = deps | result[key]
        merged[cell.key] = deps
    return merged


def ancestors(cells: Sequence[CellSource]) -> dict[str, frozenset[str]]:
    """Per cell key, the keys of every cell it reads from, directly or not."""

    producers = {name: cell.key for cell in cells for name in cell.defs}
    parents = {
        cell.key: {producers[name] for name in cell.refs if name in producers} - {cell.key}
        for cell in cells
    }
    found: dict[str, frozenset[str]] = {}

    def of(key: str, stack: frozenset[str] = frozenset()) -> frozenset[str]:
        if key not in found:
            reached: set[str] = set()
            for parent in parents[key] - stack - {key}:
                reached.add(parent)
                reached |= of(parent, stack | {key})
            found[key] = frozenset(reached)
        return found[key]

    return {cell.key: of(cell.key) for cell in cells}


def recorded_dependents(cells: Sequence[CellSource]) -> frozenset[str]:
    """The keys of the cells that depend on the files a run records.

    Those are the cells that call ``use`` and every cell that reads, however
    indirectly, what such a cell makes (see :func:`cell_module_files`).
    """

    direct = {cell.key for cell in cells if calls_use(cell.code)}
    reached = ancestors(cells)
    return frozenset(key for key in reached if key in direct or reached[key] & direct)


def _import_bindings(root: Path, source: str) -> dict[str, set[tuple[str, Path]]]:
    """The local modules each name an ``import`` in *source* binds comes from.

    ``from m import a`` binds ``a`` to ``m`` (and to ``m.a`` when that is a
    submodule); ``import m.n`` binds ``m``; a star import binds an unknown set
    of names, recorded under ``"*"``.
    """

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    bindings: dict[str, set[tuple[str, Path]]] = {}

    def bind(name: str, modules: Iterable[tuple[str, Path]]) -> None:
        found = set(modules)
        if found:
            bindings.setdefault(name, set()).update(found)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bind(alias.asname or alias.name.split(".")[0], _module_files(root, alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node.module, node.level, "")
            if base is None:
                continue
            for alias in node.names:
                modules = list(_module_files(root, base))
                if alias.name == "*":
                    bind("*", modules)
                else:
                    modules += _module_files(root, f"{base}.{alias.name}")
                    bind(alias.asname or alias.name, modules)
    return bindings


def _from_imports(root: Path, sources: Sequence[str]) -> dict[str, tuple[str, str]]:
    """The names bound exactly once, by ``from m import x`` of a local module.

    Name -> (m, x).  A name bound any other way, or to two things, or to a
    submodule, is left out: it is a dependency on whole files.
    """

    found: dict[str, tuple[str, str] | None] = {}
    for source in sources:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found[alias.asname or alias.name.split(".")[0]] = None
            elif isinstance(node, ast.ImportFrom):
                base = _absolute(node.module, node.level, "")
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if base is None or alias.name == "*" or not _is_local_module(root, base):
                        found[bound] = None
                    elif _is_local_module(root, f"{base}.{alias.name}"):
                        found[bound] = None  # a submodule, not a name
                    elif found.get(bound, (base, alias.name)) != (base, alias.name):
                        found[bound] = None
                    else:
                        found[bound] = (base, alias.name)
    return {name: target for name, target in found.items() if target is not None}


def _is_local_module(root: Path, module: str) -> bool:
    files = _module_files(root, module)
    return bool(files) and files[-1][0] == module


def _definitions(source: str) -> dict[str, set[str]]:
    """The names each top-level function and class in *source* reads."""

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    return {
        node.name: _loaded_names_of(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _loaded_names(source: str) -> set[str]:
    try:
        return _loaded_names_of(ast.parse(source))
    except (SyntaxError, ValueError):
        return set()


def _loaded_names_of(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def calls_use(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return True  # cannot tell: depend on everything
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            if (isinstance(function, ast.Name) and function.id == "use") or (
                isinstance(function, ast.Attribute) and function.attr == "use"
            ):
                return True
    return False


# ---------------------------------------------------------------------------
# The digest
# ---------------------------------------------------------------------------


def input_files(config: NotebookConfig) -> frozenset[Path]:
    return frozenset((config.directory / item.path).resolve() for item in config.inputs)


def dependency_digest(config: NotebookConfig, files: Iterable[Path], *, tag: str = "") -> str:
    """Return *D* for *files* and the inputs as they are now: 16 hex digits.

    A missing file digests as missing, so deleting one invalidates too.  A
    *tag* keeps digests of different kinds of cell apart.
    """

    contents = {
        _display(config, path): file_digest(path)
        for path in set(files) | input_files(config)
    }
    payload = {
        "schema": _SCHEMA,
        "generator": dict(generator_profile()),
        "marimo": marimo.__version__,
        "files": contents,
    }
    if tag:
        payload["tag"] = tag
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()[:16]


def cell_digest(config: NotebookConfig, files: Iterable[Path], *, tag: str = "") -> str:
    """The digest a cell's cache entries are stored under: 16 hex digits.

    Like :func:`dependency_digest`, but over the files one cell depends on (see
    :func:`cell_module_files`); the project inputs are every cell's.
    """

    return dependency_digest(config, files, tag=tag)


_digests: dict[Path, tuple[int, int, str | None]] = {}
_digests_lock = threading.Lock()


def file_digest(path: Path) -> str | None:
    """The content digest of *path*; ``None`` if it cannot be read.

    Remembered per (mtime, size): the editor kernel asks for the digests of
    the same few files for every cell it runs.
    """

    try:
        stat = path.stat()
    except OSError:
        return None
    signature = (stat.st_mtime_ns, stat.st_size)
    # A file touched a moment ago may be edited again within the clock's
    # resolution without its (mtime, size) changing: read those every time.
    settled = time.time_ns() - stat.st_mtime_ns > 2_000_000_000
    with _digests_lock:
        known = _digests.get(path)
        if settled and known is not None and known[:2] == signature:
            return known[2]
    try:
        digest: str | None = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        digest = None
    with _digests_lock:
        _digests[path] = (*signature, digest)
    return digest


def _display(config: NotebookConfig, path: Path) -> str:
    """*path* relative to the notebook, so a moved project keeps its cache."""

    try:
        return Path(os.path.relpath(path, config.directory)).as_posix()
    except ValueError:  # another drive on Windows
        return path.as_posix()


__all__ = [
    "CellDeps",
    "CellSource",
    "NameDep",
    "ancestors",
    "calls_use",
    "cell_digest",
    "cell_module_files",
    "dependency_digest",
    "file_digest",
    "recorded_dependents",
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

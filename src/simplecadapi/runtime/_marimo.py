"""Every marimo interface the notebook runtime uses, in one place.

Most of these are private to marimo and come with no stability promise.
Keeping them here means a marimo upgrade is reviewed against this one
file; the rest of :mod:`simplecadapi.runtime` imports from it only.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import marimo
from marimo._ast.app import App, InternalApp
from marimo._ast.cell import CellImpl
from marimo._ast.cell_manager import CellManager
from marimo._ast.compiler import get_filename, solve_source_position
from marimo._ast.parse import (
    NonMarimoPythonScriptError,
    is_non_marimo_python_script,
    parse_notebook,
)
from marimo._schemas.serialization import UnparsableCell
from marimo._session.notebook.serializer import get_notebook_serializer
from marimo._runtime.app.script_runner import AppScriptRunner
from marimo._runtime.context.types import (
    runtime_context_installed,
    safe_get_context,
)
from marimo._runtime.dataflow import DirectedGraph
from marimo._runtime.exceptions import MarimoRescheduleError, MarimoRuntimeException
from marimo._runtime.executor import Evaluator
from marimo._runtime.executor.executor import DefaultExecutor, Executor
from marimo._runtime.executor.lifecycles import ExecutionLifecycle, Skip
from marimo._runtime.executor.lifecycles.cached import CachedLifecycle
from marimo._runtime.runner.result import RunResult
from marimo._save.loaders.lazy import LazyLoader, LazyStore
from marimo._save.stores.file import FileStore
from marimo._types.globals import MutableGlobals
from marimo._types.ids import CellId_t
from marimo._utils.paths import notebook_output_dir
from marimo._utils.scripts import read_pyproject_from_script

__all__ = [
    "AppScriptRunner",
    "CachedLifecycle",
    "CellId_t",
    "CellImpl",
    "DefaultExecutor",
    "DirectedGraph",
    "Evaluator",
    "ExecutionLifecycle",
    "Executor",
    "FileStore",
    "App",
    "InternalApp",
    "LazyLoader",
    "LazyStore",
    "MarimoRescheduleError",
    "MarimoRuntimeException",
    "MutableGlobals",
    "RunResult",
    "Skip",
    "get_filename",
    "is_unhashable_stub",
    "load_notebook",
    "notebook_output_dir",
    "parse_notebook",
    "read_pyproject_from_script",
    "runtime_context_installed",
    "safe_get_context",
    "solve_source_position",
]

def load_notebook(path: Path, *, cell_prefix: str) -> App | None:
    """``marimo._ast.load.load_app``, with cell ids starting *cell_prefix*.

    marimo compiles each cell under a file name made of its cell id, and
    registers the cell's source in :mod:`linecache` under that name.  Cell
    ids come from a fixed seed, so every notebook has the same ones: two
    notebooks loaded into one process (a ``use``\ d child, or a headless
    run inside the editor kernel) would show each other's source in
    tracebacks, source positions and restored functions.  A prefix per
    notebook keeps them apart, as marimo's own prefix for nested apps does.

    Returns ``None`` for an empty file.
    """

    contents = path.read_text(encoding="utf-8", errors="replace").strip()
    if not contents:
        return None
    notebook = get_notebook_serializer(path).deserialize(contents, filepath=str(path))
    if is_non_marimo_python_script(notebook):
        raise NonMarimoPythonScriptError(f"{path} is not a marimo notebook")
    app = App(**notebook.app.options, _filename=str(path))
    app._cell_manager = CellManager(prefix=cell_prefix)
    for cell in notebook.cells:
        if isinstance(cell, UnparsableCell):
            app._unparsable_cell(cell.code, **cell.options)
        else:
            app._cell_manager.register_ir_cell(cell, InternalApp(app))
    if notebook.header and notebook.header.value:
        app._header = notebook.header.value
    app._cell_manager.ensure_one_cell()
    return app


def is_unhashable_stub(value: object) -> bool:
    """Whether *value* is the stub the cell cache restores for a value it
    could not pickle (marimo's ``__marimo_unhashable__`` protocol)."""

    return getattr(type(value), "__marimo_unhashable__", False) is True


TESTED_MARIMO = (0, 25)
"""The marimo minor release these interfaces were checked against."""


def _minor(version: str) -> tuple[int, int] | None:
    parts = version.split(".")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None


if _minor(marimo.__version__) != TESTED_MARIMO:
    warnings.warn(
        f"simplecadapi's notebook runtime was checked against marimo "
        f"{TESTED_MARIMO[0]}.{TESTED_MARIMO[1]}, found {marimo.__version__}; "
        "cell caching or source positions may misbehave.",
        RuntimeWarning,
        stacklevel=2,
    )

"""The marimo cell executor: one recording session per notebook cell.

marimo loads a single ``marimo.cell.executor`` entry point for every
notebook it runs, the web editor's included.  The editor keeps a session of
its own, so a cell session there would record operations the editor never
sees.  :class:`SimpleCadExecutor` therefore only steps in for notebooks
that declare ``[tool.simplecadapi]``; any other notebook runs exactly as
under marimo's default executor.

For a SimpleCAD notebook each cell runs inside a fresh
:class:`~simplecadapi.recording.graph.GraphSession` that

* is namespaced by the cell's key, so ids stay unique across cells and
  across cache restores;
* accepts values from other cells' sessions (``shared_lineage``) and built
  ``@part``/``@assemble`` values (``allow_external_definitions``);
* records source positions relative to the cell (see :mod:`.cells`).

After the cell body runs, every tolerance requirement it declared must be
held by one of its variables; see :func:`.cells.bound_requirements`.

While a cell runs, :func:`notebook_id` returns the id of the run: the
header's id, or the one a caller passed to ``run_notebook``/``use``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from ..recording.graph import GraphSession
from ..recording.source_mapping import cell_sources
from ._marimo import (
    CellImpl,
    DefaultExecutor,
    Executor,
    MarimoRuntimeException,
    MutableGlobals,
    safe_get_context,
)
from .cells import NotebookCells, bound_requirements
from .config import NotebookConfig, read_notebook_config


class UnboundRequirementError(RuntimeError):
    """A cell declared a tolerance requirement no variable holds.

    The cell cache stores variables only; an unbound requirement would be
    silently lost the next time the cell is restored from the cache.
    """


@dataclass(frozen=True)
class NotebookScope:
    """The notebook a cell belongs to, as the executor needs it."""

    config: NotebookConfig
    cells: NotebookCells


_running: ContextVar[NotebookScope | None] = ContextVar(
    "simplecadapi_running_notebook", default=None
)
"""The scope of the cell running in this context, if any."""


def notebook_id() -> str:
    """Return the id of the notebook run the calling cell belongs to.

    It is the header's ``id`` unless the run was started with another
    (``run_notebook(path, id=...)``, ``use(path, id=...)``), so a notebook
    that names its product with it describes a part family: each id is one
    member, with a definition of its own.
    """

    scope = _running.get()
    if scope is None:
        raise RuntimeError("notebook_id() is only available while a SimpleCAD notebook cell runs")
    return scope.config.id


class SimpleCadExecutor:
    """Run cells like marimo's default executor, recording per cell.

    Pass *scope* when the caller knows the notebook (a headless run, which
    may be nested inside another notebook's kernel).  Without it the
    executor looks the notebook up from marimo's runtime context for each
    cell, which is what the editor kernel needs.
    """

    name = "simplecadapi"

    def __init__(self, scope: NotebookScope | None = None) -> None:
        self._scope = scope
        self._delegate = DefaultExecutor()

    def execute_cell(self, cell: CellImpl, glbls: MutableGlobals) -> Any:
        scope = self._scope or _context_scope()
        if scope is None:
            return self._delegate.execute_cell(cell, glbls)
        with _cell_recording(scope, cell, glbls):
            return self._delegate.execute_cell(cell, glbls)

    async def execute_cell_async(self, cell: CellImpl, glbls: MutableGlobals) -> Any:
        scope = self._scope or _context_scope()
        if scope is None:
            return await self._delegate.execute_cell_async(cell, glbls)
        with _cell_recording(scope, cell, glbls):
            return await self._delegate.execute_cell_async(cell, glbls)


def executor_factory() -> Executor:
    """The ``marimo.cell.executor`` entry point."""

    return SimpleCadExecutor()


def _context_scope() -> NotebookScope | None:
    """Return the scope of the notebook marimo is running, if it is ours."""

    context = safe_get_context()
    if context is None or context.filename is None:
        return None
    config = read_notebook_config(context.filename)
    if config is None:
        return None
    return NotebookScope(config, NotebookCells(config.path, context.graph.cells.values()))


@contextmanager
def _cell_recording(
    scope: NotebookScope, cell: CellImpl, glbls: MutableGlobals
) -> Iterator[None]:
    session = GraphSession(
        graph_id=scope.config.id,
        allow_external_definitions=True,
        namespace=scope.cells.key(cell.cell_id),
        shared_lineage=True,
    )
    token = _running.set(scope)
    try:
        with cell_sources(scope.cells), session:
            yield
    finally:
        _running.reset(token)
    # Reached only when the body succeeded; failures propagate untouched.
    _check_bound(session, cell, glbls)


def _check_bound(session: GraphSession, cell: CellImpl, glbls: MutableGlobals) -> None:
    held = {
        id(requirement)
        for requirement in bound_requirements(
            glbls[name] for name in cell.defs if name in glbls
        )
    }
    unbound = [
        requirement.name
        for requirement in session.tolerance_graph.requirements
        if id(requirement) not in held
    ]
    if unbound:
        error = UnboundRequirementError(
            f"tolerance requirements {unbound} are not held by any variable "
            "this cell defines; assign each one, e.g. "
            "`req = scad.get_active_session().require_tolerance(...)`, so the "
            "cell cache keeps it"
        )
        # Raised like a failing cell body, so marimo reports it as one.
        raise MarimoRuntimeException from error


__all__ = [
    "NotebookScope",
    "SimpleCadExecutor",
    "UnboundRequirementError",
    "executor_factory",
    "notebook_id",
]

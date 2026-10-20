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

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..recording.graph import GraphSession
from ..recording.source_mapping import cell_sources
from ._marimo import (
    CellImpl,
    DefaultExecutor,
    Executor,
    MarimoRescheduleError,
    MarimoRuntimeException,
    MutableGlobals,
    RunResult,
    safe_get_context,
)
from . import prefetch
from .cache import CellCache, CellDigests, cache_root, prune
from .cells import NotebookCells, bound_requirements
from .config import NotebookConfig, read_notebook_config
from .params import apply_saved_params, read_saved_params


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
    graph: Any = None
    """marimo's dataflow graph of the notebook, known when marimo itself runs it."""


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
    cell, which is what the editor kernel needs.  The kernel's cells go
    through the same cell cache a headless run uses (:mod:`.cache`); a headless
    run has its own lifecycle for that.
    """

    name = "simplecadapi"

    def __init__(self, scope: NotebookScope | None = None) -> None:
        self._scope = scope
        self._delegate = DefaultExecutor()

    def execute_cell(self, cell: CellImpl, glbls: MutableGlobals) -> Any:
        scope = self._scope or _context_scope()
        if scope is None or cell.cell_id not in scope.cells:
            return self._delegate.execute_cell(cell, glbls)
        cache = self._cache_for(scope, cell)
        restored = _restore(cache, cell, glbls)
        if restored is not _MISS:
            return restored
        cache = cache if restored is _MISS else None
        _prefetch(scope, cell, glbls)
        try:
            with _cell_recording(scope, cell, glbls):
                result = self._delegate.execute_cell(cell, glbls)
                self._apply_saved(scope, cell, glbls)
        except BaseException as error:
            _store(cache, cell, glbls, None, error)
            raise
        _store(cache, cell, glbls, result, None)
        return result

    async def execute_cell_async(self, cell: CellImpl, glbls: MutableGlobals) -> Any:
        scope = self._scope or _context_scope()
        if scope is None or cell.cell_id not in scope.cells:
            return await self._delegate.execute_cell_async(cell, glbls)
        cache = self._cache_for(scope, cell)
        restored = _restore(cache, cell, glbls)
        if restored is not _MISS:
            return restored
        _prefetch(scope, cell, glbls)
        try:
            with _cell_recording(scope, cell, glbls):
                result = await self._delegate.execute_cell_async(cell, glbls)
                self._apply_saved(scope, cell, glbls)
        except BaseException as error:
            _store(cache, cell, glbls, None, error)
            raise
        _store(cache, cell, glbls, result, None)
        return result

    def _apply_saved(
        self, scope: NotebookScope, cell: CellImpl, glbls: MutableGlobals
    ) -> None:
        # Only the editor kernel (no scope given) takes the values an editor
        # saved; a headless run takes the overrides it is passed (see params).
        if self._scope is None:
            apply_saved_params(scope.config, set(cell.defs), glbls)

    def _cache_for(self, scope: NotebookScope, cell: CellImpl) -> CellCache | None:
        """The cell cache of the editor kernel's notebook; ``None`` where there is none."""

        if self._scope is not None or scope.graph is None or os.environ.get("SCA_NO_KERNEL_CACHE"):
            return None
        return _kernel_cache(scope, cell)


def _prefetch(scope: NotebookScope, cell: CellImpl, glbls: MutableGlobals) -> None:
    """Start the notebooks the cell is about to ``use`` in worker processes."""

    try:
        prefetch.start(scope.config.directory, cell.code, glbls, scope.config.id)
    except Exception:  # noqa: BLE001 - an optimisation, never a reason for a cell to fail
        pass


_MISS = object()
"""Returned by :func:`_restore` when the cell must run."""


def _restore(cache: CellCache | None, cell: CellImpl, glbls: MutableGlobals) -> Any:
    """Restore *cell* from the cache: its output, or ``_MISS`` if it has to run."""

    if cache is None:
        return _MISS
    try:
        skip = cache.setup(cell, glbls)
    except MarimoRescheduleError:
        # A value the cache could not restore: run the cell live, store nothing.
        cache._active.pop(cell.cell_id, None)
        return _MISS
    if skip is None:
        return _MISS
    return skip.result.output


def _store(
    cache: CellCache | None,
    cell: CellImpl,
    glbls: MutableGlobals,
    output: Any,
    error: BaseException | None,
) -> None:
    if cache is not None:
        cache.teardown(cell, glbls, RunResult(output=output, exception=error))


@dataclass
class _KernelCache:
    graph: Any
    signature: tuple
    digests: CellDigests
    lifecycle: CellCache


_kernel_caches: dict[Path, _KernelCache] = {}
_KEEP_DIGESTS = 64
"""How many of the most recently used digests the kernel keeps on disk."""


def _kernel_cache(scope: NotebookScope, cell: CellImpl) -> CellCache | None:
    """The cell cache for the notebook marimo is running; rebuilt when its cells change."""

    if cell.cell_id == "setup":
        return None  # like marimo, never cache the setup cell
    config = scope.config
    graph = scope.graph
    cells = list(graph.cells.values())
    saved = read_saved_params(config)
    signature = (
        tuple((item.cell_id, item.code) for item in cells),
        tuple(sorted(saved.items())),
    )
    entry = _kernel_caches.get(config.path)
    if entry is not None and entry.graph is graph and entry.signature == signature:
        return entry.lifecycle
    digests = CellDigests(config, cells, graph.cells.get("setup"), saved=saved, kernel=True)
    if entry is not None and entry.graph is graph:
        entry.signature, entry.digests = signature, digests
        return entry.lifecycle
    entry = _KernelCache(graph=graph, signature=signature, digests=digests, lifecycle=None)  # type: ignore[arg-type]
    entry.lifecycle = CellCache(
        graph, cache_root(config), lambda item: entry.digests.digest(item.cell_id)
    )
    _kernel_caches[config.path] = entry
    return entry.lifecycle


def finish_kernel_cache(config: NotebookConfig) -> None:
    """Write out the kernel's pending cache entries and drop the old ones.

    The cache pickles values on background threads, and projecting the product
    modifies it: flush first.  Called by :func:`.live.live_package`.
    """

    entry = _kernel_caches.get(config.path)
    if entry is None:
        return
    entry.lifecycle.flush()
    prune(cache_root(config), entry.lifecycle.recent(_KEEP_DIGESTS))


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
    return NotebookScope(
        config, NotebookCells(config.path, context.graph.cells.values()), graph=context.graph
    )


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
    "finish_kernel_cache",
    "notebook_id",
]

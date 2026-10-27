"""Run a SimpleCAD notebook without the editor.

:func:`run_notebook` is what ``sca run`` and agents use.  It runs the
notebook with marimo's own script runner, differing from ``python nb.py``
in three ways:

* cells run through :class:`~.executor.SimpleCadExecutor`, so each records
  into a session of its own;
* cells are cached with marimo's cell cache, each under a digest of the
  local modules, child notebooks and input files *it* depends on
  (:mod:`.cache`), so a changed file recomputes only the cells that read it;
* after the last cell the product is projected onto its definition
  (:mod:`.projection`).

:func:`use` runs one notebook from a cell of another and returns the
child's product, ready to be placed in an assembly.

Both take an optional ``id`` that replaces the header's id for the run.  A
notebook that names its product with :func:`~.executor.notebook_id` is then
a part family: one notebook, one definition per id.
"""

from __future__ import annotations

import hashlib
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, TypeVar

from ..artifacts.assembly_io import attached_definition
from ..artifacts.canonical import validate_logical_id
from ..build.definition import Definition
from simplecadapi._cpp import isolated_recording
from ._marimo import (
    AppScriptRunner,
    CellId_t,
    CellImpl,
    Evaluator,
    ExecutionLifecycle,
    InternalApp,
    MarimoRescheduleError,
    MarimoRuntimeException,
    MutableGlobals,
    RunResult,
    Skip,
    is_unhashable_stub,
    load_notebook,
    runtime_context_installed,
    safe_get_context,
    suppress_warnings_logs,
)
from . import prefetch, usememo
from .cache import CellCache, CellDigests, cache_root, prune
from .cells import NotebookCells
from .config import NotebookConfig, NotebookConfigError, read_notebook_config
from .deps import (
    local_modules,
    exclusive,
    read_dependencies,
    record_dependencies,
    recording_dependencies,
    refresh_local_modules,
    write_dependencies,
)
from .executor import NotebookScope, SimpleCadExecutor
from .projection import Product, find_product, project_product

_T = TypeVar("_T")

CellStatus = Literal["ran", "cached", "skipped"]
"""``ran``: executed; ``cached``: restored from the cell cache; ``skipped``:
not run, because overrides replace its variables or the cell is disabled."""

@dataclass(frozen=True)
class CellReport:
    """What happened to one cell during a run.

    ``status`` is ``"ran"`` (executed), ``"cached"`` (restored from the
    cell cache) or ``"skipped"`` (not run: overrides replace its variables,
    or the cell is disabled).
    """

    name: str
    """The cell's function name in the notebook (often ``_``)."""
    key: str
    """The cell's key: the namespace of its ids (see :mod:`.cells`)."""
    status: CellStatus


@dataclass(frozen=True)
class NotebookRun:
    """The outcome of :func:`run_notebook`.

    ``product`` is the notebook's product and ``definition`` its durable
    definition (``None`` for a partial run — see ``through``/``product``);
    ``values`` holds every top-level variable, ``cells`` one report per cell
    in notebook order, and ``dependencies`` the files outside the cells the
    run depends on.
    """

    config: NotebookConfig
    product: Product | None
    """The product, carrying its definition; ``None`` when none was asked for."""
    values: Mapping[str, Any]
    """Every top-level variable, overrides included."""
    cells: tuple[CellReport, ...]
    """One report per cell, in notebook order."""
    dependencies: frozenset[Path]
    """Files outside the cells this run depends on (see :mod:`.deps`)."""

    @property
    def definition(self) -> Definition:
        if self.product is None:
            raise ValueError("this run produced no product (a partial run: through= or product=False)")
        definition = attached_definition(self.product)
        # project_product attaches one to every product it returns.
        assert definition is not None
        return definition


def run_notebook(
    path: str | Path,
    *,
    id: str | None = None,
    overrides: Mapping[str, Any] | None = None,
    cache: bool = True,
    through: int | None = None,
    product: bool = True,
    timeout: float | None = None,
) -> NotebookRun:
    """Run the notebook at *path* and project its product.

    *id* replaces the header's id for this run: the product is then the
    value with that id, and cells read it with ``notebook_id()``.
    *overrides* replace top-level variables: the cells that define them do
    not run (marimo requires such a cell's variables to be overridden all
    together).  ``cache=False`` neither reads nor writes the cell cache.
    Errors raised by a cell propagate unchanged.

    *through* runs only the first *through* cells, in notebook order — the
    validation of a stage the tail does not have to exist for.  With
    ``product=False`` the run does not look for the notebook's product at
    all.  *timeout* (seconds) fails the run with :class:`TimeoutError` when
    it takes longer; ``None`` (the default) runs unbounded.
    """

    config = read_notebook_config(path)
    if config is None:
        raise NotebookConfigError(
            f"{path}: not a SimpleCAD notebook (its script header has no "
            "[tool.simplecadapi] table)"
        )
    if id is not None:
        config = replace(config, id=validate_logical_id(id, "/run/id"))
    values = dict(overrides or {})

    def run() -> NotebookRun:
        # The cache loaders warn about the degraded states they heal
        # themselves out of (unsigned entries for missing cryptography, a
        # value restored as a stub); at WARNING they read as run failures.
        # Errors still come through.  "marimo" is the logger every marimo
        # module shares (lazy.py's record shows its file name, "lazy", which
        # is not the logger's name).
        with suppress_warnings_logs("marimo"), exclusive(config):
            return _run(config, values, cache=cache, through=through, product=product)

    # marimo keeps its runtime context per thread, and a notebook run needs
    # one of its own; a run started from a cell (``use``) gets a thread.
    if runtime_context_installed():
        return _on_own_thread(run)
    if timeout is None:
        return run()
    return _with_timeout(run, timeout)


def use(path: str | Path, /, *, id: str | None = None, **overrides: Any) -> Product:
    """Run the notebook at *path* and return its product.

    A relative *path* is relative to the notebook calling ``use``.  *id*
    replaces the child's header id (see :func:`run_notebook`); the other
    keyword arguments override the child's top-level variables.  The product
    carries its definition, so it can be a component of an assembly
    directly; the calling notebook's cache now depends on the child.
    """

    target = Path(path)
    if not target.is_absolute():
        target = _calling_directory() / target
    kept = usememo.recall(target, id, overrides)
    if kept is not None:  # this process ran it already and nothing it depends on changed
        record_dependencies({kept.path, *kept.dependencies})
        return kept.product
    prefetch.wait(target, id, overrides)  # a worker may be building it
    child = run_notebook(target, id=id, overrides=overrides)
    # use() never asks for a partial run, so the product is always there.
    if child.product is None:
        raise RuntimeError(f"{child.config.path}: the child run produced no product")
    record_dependencies({child.config.path, *child.dependencies})
    usememo.keep(target, id, overrides, usememo.Kept(child.product, child.config.path, frozenset(child.dependencies)))
    return child.product


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def _run(
    config: NotebookConfig,
    overrides: dict[str, Any],
    *,
    cache: bool,
    through: int | None = None,
    product: bool = True,
) -> NotebookRun:
    started = time.perf_counter()
    given = dict(overrides)  # (``overrides`` becomes the run's values below)
    app = load_notebook(config.path, cell_prefix=_cell_prefix(config))
    if app is None:
        raise NotebookConfigError(f"{config.path}: the notebook has no cells")
    internal = InternalApp(app)
    ordered = [
        internal.graph.cells[cell_id]
        for cell_id in internal.cell_manager.cell_ids()
        if cell_id in internal.graph.cells
    ]
    if through is not None:
        if through < 1:
            raise ValueError(f"through must be at least 1, got {through}")
        # Counted the way the editor numbers cells: the setup cell is
        # infrastructure and takes no number.  Disabled is what the script
        # runner filters on (graph.disable_cell only sets a runtime status);
        # a cell before the cut that reads one behind it fails with its own
        # NameError, which is the honest report.
        setup_id = internal.cell_manager.setup_cell_id
        visible = [cell for cell in ordered if cell.cell_id != setup_id]
        for cell in visible[through:]:
            cell.config.disabled = True
    _check_overrides(config, internal, ordered, overrides)
    cells = NotebookCells(config.path, ordered)
    scope = NotebookScope(config, cells)

    modules = local_modules(config, (cell.code for cell in ordered))
    module_files = frozenset(modules.values())
    previous = read_dependencies(config)
    setup_cell = internal.graph.cells.get(internal.cell_manager.setup_cell_id)
    digests = CellDigests(config, ordered, setup_cell)
    root = cache_root(config)
    progress = _Progress()
    cell_cache = (
        CellCache(internal.graph, root, lambda cell: digests.digest(cell.cell_id)) if cache else None
    )

    refresh_local_modules(modules)
    with isolated_recording(), _importable(config.directory), recording_dependencies() as used:
        glbls: MutableGlobals | None = None
        try:
            glbls = _execute(internal, scope, overrides, progress, cell_cache)
        except MarimoRescheduleError:
            # A cell reads a value the cache could not restore, and the
            # script runner cannot reschedule the cell that makes it.
            pass
        finally:
            if cell_cache is not None:
                # The cache pickles values on background threads, and the
                # projection below modifies the product.
                cell_cache.flush()
        restored = cell_cache.restored if cell_cache is not None else set()
        if glbls is None or _holds_stub(glbls, ordered):
            # marimo restores a value it could not unpickle as a stub (and has
            # logged why): an entry written by an older build names classes
            # that are no longer there.  Drop the entries that could not be
            # restored and run again with the cache, which writes them anew.
            # (Running without it, as this used to, left the entries as they
            # were: every later run found the same stubs and ran every cell.)
            if cell_cache is not None and glbls is not None and _stubs_are_gone_classes(glbls, ordered):
                for cell in ordered:
                    if any(is_unhashable_stub(glbls.get(name)) for name in cell.defs):
                        cell_cache.discard(cell)
                cell_cache = CellCache(internal.graph, root, lambda cell: digests.digest(cell.cell_id))
                progress = _Progress()
                try:
                    glbls = _execute(internal, scope, overrides, progress, cell_cache)
                except MarimoRescheduleError:
                    glbls = None
                finally:
                    cell_cache.flush()
                restored = cell_cache.restored
            if glbls is None or _holds_stub(glbls, ordered):
                # Still unusable: run every cell again, without the cache.
                progress = _Progress()
                glbls = _execute(internal, scope, overrides, progress)
                restored = set()

    values = {
        name: glbls[name] for cell in ordered for name in cell.defs if name in glbls
    }
    read = frozenset().union(*(cell.refs for cell in ordered))
    product_value: Product | None = None
    if product:
        product_value = project_product(
            find_product(config, values, read),
            config=config,
            cells=cells,
            values=values.values(),
        )

    # Cells restored from the cache ran no ``use`` this time; the files they
    # depend on are among those the previous run recorded.
    recorded = frozenset(used) | (previous if restored else frozenset())
    write_dependencies(config, recorded)
    dependencies = module_files | recorded
    if cache and cell_cache is not None:
        # A cell that runs a child notebook depends on the record just written:
        # its entries move to the digest of what it now depends on.
        after = CellDigests(config, ordered, setup_cell)
        used_digests = set(cell_cache.used)
        for cell in ordered:
            old, new = digests.digest(cell.cell_id), after.digest(cell.cell_id)
            if old is not None and new is not None and old != new and old in used_digests:
                cell_cache.move(old, new)
                used_digests.discard(old)
                used_digests.add(new)
        prune(root, used_digests)

    reports = tuple(
        CellReport(
            name=internal.cell_manager.cell_name(cell.cell_id),
            key=cells.key(cell.cell_id),
            status=(
                "cached"
                if cell.cell_id in restored
                else "ran" if cell.cell_id in progress.ran else "skipped"
            ),
        )
        for cell in ordered
    )
    if product and through is None and cache:
        built = any(report.status == "ran" and report.name != "setup" for report in reports)
        prefetch.write_stamp(config, given, time.perf_counter() - started if built else None)
    return NotebookRun(
        config=config,
        product=product_value,
        values=values,
        cells=reports,
        dependencies=dependencies,
    )


def _with_timeout(run: Callable[[], NotebookRun], timeout: float) -> NotebookRun:
    """Put a wall clock around *run*.

    The worker thread is a daemon: a run that ignores the deadline (native
    code deep in a fillet) cannot keep the process alive past it.
    """
    import threading

    outcome: list[NotebookRun] = []
    failure: list[BaseException] = []

    def work() -> None:
        try:
            outcome.append(run())
        except BaseException as error:  # re-raised on the caller's thread
            failure.append(error)

    worker = threading.Thread(target=work, daemon=True, name="notebook-run")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(
            f"the notebook did not finish in {timeout:g}s (pass a larger "
            "timeout; heavy features can take minutes)"
        )
    if failure:
        raise failure[0]
    return outcome[0]


def _execute(
    internal: InternalApp,
    scope: NotebookScope,
    overrides: dict[str, Any],
    progress: _Progress,
    cell_cache: CellCache | None = None,
) -> MutableGlobals:
    glbls = {**_run_setup(internal, scope, progress), **overrides}
    runner = AppScriptRunner(internal, str(scope.config.path), glbls)
    # The runner takes neither an executor nor lifecycles; its evaluator is
    # built in __init__ and first used by run().  The progress lifecycle
    # goes last, so that it sees only the cells the cache did not restore.
    lifecycles: list[ExecutionLifecycle] = [progress]
    if cell_cache is not None:
        lifecycles.insert(0, cell_cache)
    runner._evaluator = Evaluator(SimpleCadExecutor(scope), lifecycles)
    _, glbls = runner.run()
    return glbls


def _run_setup(
    internal: InternalApp, scope: NotebookScope, progress: _Progress
) -> dict[str, Any]:
    """Run the setup cell (``with app.setup:``) and return its variables.

    The script runner expects them as globals, because ``app.run()`` runs
    the setup cell as plain code when the notebook file is executed.  Like
    marimo, the setup cell is never cached.
    """

    setup = internal.graph.cells.get(internal.cell_manager.setup_cell_id)
    if setup is None:
        return {}
    glbls: dict[str, Any] = {"__name__": "__main__"}
    result = Evaluator(SimpleCadExecutor(scope), [progress]).evaluate_sync(setup, glbls)
    error = result.exception
    if isinstance(error, MarimoRuntimeException) and error.__cause__ is not None:
        # As the script runner does: raise the cell's own exception.
        raise error.__cause__ from None
    if isinstance(error, BaseException):
        raise error
    if error is not None:  # a marimo error record, not an exception
        raise RuntimeError(f"the setup cell failed: {error}")
    return {name: glbls[name] for name in setup.defs if name in glbls}


def _check_overrides(
    config: NotebookConfig,
    internal: InternalApp,
    cells: list[CellImpl],
    overrides: Mapping[str, Any],
) -> None:
    defined = {name for cell in cells for name in cell.defs}
    unknown = sorted(set(overrides) - defined)
    if unknown:
        raise ValueError(f"{config.path.name}: no cell defines {', '.join(unknown)}")
    setup = internal.graph.cells.get(internal.cell_manager.setup_cell_id)
    fixed = sorted(set(overrides) & setup.defs) if setup is not None else []
    if fixed:
        # app.run(defs=...) refuses these too.
        raise ValueError(
            f"{config.path.name}: the setup cell's variables cannot be "
            f"overridden: {', '.join(fixed)}"
        )
    for cell in cells:
        given = cell.defs & overrides.keys()
        missing = sorted(cell.defs - given)
        if given and missing:
            # An overridden cell does not run, so it cannot supply the rest.
            raise ValueError(
                f"{config.path.name}: the cell defining {', '.join(sorted(given))} "
                f"also defines {', '.join(missing)}; override them together, or "
                "define them in cells of their own"
            )


def _stubs_are_gone_classes(glbls: MutableGlobals, cells: list[CellImpl]) -> bool:
    """Whether every stub the run restored is an entry whose classes no longer exist (``No module named ...``).

    That entry is stale: it is deleted and written again.  A stub for any other reason (a value that cannot be
    pickled at all, a lock) stays what it was: the notebook runs again without the cache.
    """

    reasons = [
        str(getattr(glbls.get(name), "error_msg", ""))
        for cell in cells
        for name in cell.defs
        if is_unhashable_stub(glbls.get(name))
    ]
    return bool(reasons) and all(reason.startswith("No module named") for reason in reasons)


def _holds_stub(glbls: MutableGlobals, cells: list[CellImpl]) -> bool:
    return any(is_unhashable_stub(glbls.get(name)) for cell in cells for name in cell.defs)


class _Progress:
    """Records the cells whose body runs.

    Placed after the cell cache, its ``setup`` is reached only when the
    cache did not restore the cell.
    """

    name = "simplecadapi-progress"

    def __init__(self) -> None:
        self.ran: set[CellId_t] = set()

    def setup(self, cell: CellImpl, glbls: MutableGlobals) -> Skip | None:
        self.ran.add(cell.cell_id)
        return None

    def teardown(self, cell: CellImpl, glbls: MutableGlobals, run_result: RunResult) -> None:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cell_prefix(config: NotebookConfig) -> str:
    """A cell id prefix of the notebook's own (see ``load_notebook``)."""

    return hashlib.sha256(str(config.path).encode()).hexdigest()[:8] + "-"


@contextmanager
def _importable(directory: Path) -> Iterator[None]:
    """Let the cells import modules next to the notebook, as marimo does."""

    entry = str(directory)
    sys.path.insert(0, entry)
    try:
        yield
    finally:
        try:
            sys.path.remove(entry)
        except ValueError:
            pass


def _on_own_thread(function: Callable[[], _T]) -> _T:
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="simplecadapi-run") as pool:
        return pool.submit(function).result()


def _calling_directory() -> Path:
    """The directory of the notebook whose cell is running, else the cwd."""

    context = safe_get_context()
    if context is not None and context.filename is not None:
        return Path(context.filename).resolve().parent
    return Path.cwd()


__all__ = ["CellReport", "CellStatus", "NotebookRun", "run_notebook", "use"]

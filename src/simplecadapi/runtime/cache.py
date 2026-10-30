"""The cell cache: marimo's, kept per cell.

marimo keys a cell's cache entry by the cell's code and the values it reads.
It cannot see what a SimpleCAD notebook also depends on — local modules, child
notebooks, project input files — so an entry is also stored under a digest of
those files (:mod:`.deps`).  The digest used to be one for the whole notebook:
any change to any such file discarded every cell's entries.  It is now one
per cell, over only the files that cell depends on (:func:`.deps.cell_module_files`),
so editing ``dimensions.py`` recomputes the cells that read the dimensions and
restores the rest, and a cell downstream of a recomputed one is restored again
if the values it reads came out the same.

The same cache serves a headless run (:func:`~.runner.run_notebook`, ``sca
run``) and the editor kernel (:mod:`.executor`), so what one computed the
other restores.

Layout: ``<state dir>/cache/<digest>/`` holds the entries of every cell whose
digest it is.  :func:`prune` removes the directories the last two runs did not
use, so going back to a previous value is still instant.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import threading
import time
import zlib
from collections import OrderedDict
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from simplecadapi._cpp import Assembly, Part

from .._glue.notice import say
from ._marimo import (
    CachedLifecycle,
    CellId_t,
    CellImpl,
    DirectedGraph,
    FileStore,
    LazyLoader,
    LazyStore,
    MutableGlobals,
    RunResult,
    Skip,
    BlockHasher,
    MarimoCache,
    is_unhashable_stub,
    marimo_cached as _marimo_cached,
)
from .children import notebook_digest
from .config import NotebookConfig
from .names import names_tag
from .stubs import register_scalar_stubs  # noqa: F401  (registers on import)
from .deps import (
    CellSource,
    ancestors,
    cell_digest,
    cell_module_files,
    read_dependencies,
    state_dir,
)

_CELLS = "cells"
"""The cell cache's loader name, fixed so a cache directory can be renamed:
its entries reference their values by paths starting with this name."""

_RUNS = "_runs.json"


def cache_root(config: NotebookConfig) -> Path:
    """The notebook's cell caches: one directory per dependency digest."""

    return state_dir(config) / "cache"


_PACKED = b"SCZ2"
"""Starts an entry written compressed; one without it was written before
compression existed and is read as it is."""

_MIN_PACKED = 1024


class CompressedFileStore(FileStore):
    """marimo's file store, compressing what it writes.

    A cell's value carries the definitions of the parts in it (archives and
    JSON documents, written uncompressed) and the geometry: an assembly is a
    hundred megabytes of pickle that shrinks ten-fold at zlib level 1, and
    reading less is most of what a restore costs.  Decompressing happens on
    the loader's reader threads, where zlib lets go of the interpreter lock.
    """

    def get(self, key: str) -> bytes | None:
        data = super().get(key)
        if data is not None and data.startswith(_PACKED):
            return zlib.decompress(data[len(_PACKED) :])
        return data

    def put(self, key: str, value: bytes) -> bool:
        if len(value) >= _MIN_PACKED:
            value = _PACKED + zlib.compress(value, 1)
        return super().put(key, value)


def saved_names_by_cell(sources: Sequence[CellSource], saved: Collection[str]) -> dict[str, set[str]]:
    """Per cell, the saved values its result depends on.

    A cell depends on a saved value when it defines it, or when it or a cell it reads from, directly or not, reads it:
    that is the path the value takes to the cell.  A cell that is downstream of the cell that defines the value only
    because it reads *other* variables of that cell does not depend on it (the notebook's parameter cell defines every
    parameter; changing a joint angle must not change the digest of the cell that builds the parts).
    """

    reached = ancestors(sources)
    own = {source.key: set(source.defs) & set(saved) for source in sources}
    reads = {source.key: set(source.refs) for source in sources}
    result: dict[str, set[str]] = {}
    for source in sources:
        upstream = reached[source.key]
        flowing = set().union(*(own[key] for key in upstream))
        read = set(reads[source.key]).union(*(reads[key] for key in upstream))
        result[source.key] = own[source.key] | (flowing & read)
    return result


class CellDigests:
    """The digest of each cell of a notebook, from what it depends on.

    *saved* are values an editor applies to variables after the cell that
    defines them ran (:mod:`.params`).  They are not in any cell's code, and
    marimo keys a cell that reads an object by the code of the cells that made
    it, so every cell downstream of a saved value carries it in its digest.
    With *kernel*, cells that depend on what a run records (child notebooks)
    have no digest: only a headless run records them, so the kernel runs those
    cells live (the child notebooks themselves are cached).
    """

    def __init__(
        self,
        config: NotebookConfig,
        cells: list[CellImpl],
        setup: CellImpl | None,
        *,
        saved: Mapping[str, Any] | None = None,
        kernel: bool = False,
    ) -> None:
        self.config = config
        self.setup_id = setup.cell_id if setup is not None else None
        sources = [
            CellSource(cell.cell_id, cell.code, frozenset(cell.refs), frozenset(cell.defs))
            for cell in cells
            if cell.cell_id != self.setup_id
        ]
        self._files = cell_module_files(
            config,
            setup.code if setup is not None else None,
            sources,
            read_dependencies(config),
        )
        # A cell that runs a child notebook, or reads what one makes, depends
        # on what the last run recorded; its entries are kept apart so they
        # can follow the record.
        self._uses = frozenset(key for key, deps in self._files.items() if deps.dynamic)
        self._recorded = read_dependencies(config)
        self._kernel = kernel
        self._saved_tag: dict[str, str] = {}
        if saved:
            for key, names in saved_names_by_cell(sources, saved.keys()).items():
                if names:
                    payload = json.dumps({name: saved[name] for name in sorted(names)}, sort_keys=True)
                    self._saved_tag[key] = "p" + hashlib.sha256(payload.encode()).hexdigest()[:12]

    def digest(self, cell_id: CellId_t) -> str | None:
        """The digest for *cell_id*, ``None`` for a cell that is not cached."""

        deps = self._files.get(cell_id)
        if deps is None:
            return None  # the setup cell
        if self._kernel and cell_id in self._uses:
            return None
        named, fallback = names_tag(self.config.directory, deps.names)
        used, unknown = self._used_tag(deps.uses)
        if unknown:
            # A notebook this one uses has a part of its own that only a run
            # can name: depend on what the last run recorded.
            if self._kernel:
                return None
            fallback = fallback | self._recorded
        tag = ("use" if cell_id in self._uses or unknown else "") + self._saved_tag.get(cell_id, "") + named + used
        return cell_digest(self.config, deps.files | fallback, tag=tag)

    @staticmethod
    def _used_tag(paths: frozenset[Path]) -> tuple[str, bool]:
        """The digest of the notebooks a cell uses by a literal path, and
        whether one of them cannot be digested."""

        if not paths:
            return "", False
        digests: dict[str, str] = {}
        for path in sorted(paths):
            digest = notebook_digest(path)
            if digest is None:
                return "", True
            digests[path.name] = digest
        encoded = json.dumps(digests, sort_keys=True).encode("utf-8")
        return "u" + hashlib.sha256(encoded).hexdigest()[:12], False


# -- the editor kernel's memory of what its cells made ---------------------------------------------------------------------


_MEMORY_ENTRIES = 12
"""How many cell results the kernel keeps (the newest; counted in entries, not bytes: an assembly of a few dozen parts is
some tens of megabytes, which is where the editor's extra resident memory comes from).  Only an editor kernel has a
memory (``CellCache(memory=True)``); ``sca run`` and the tests do not, and the SDK's own code cannot change under it:
the kernel is a process that imported it once."""


def _shareable(value: Any) -> bool:
    """Whether *value* may be handed to a later run as the same object: plain data and the SDK's value types.

    Those are functional (an operation returns a new value) except for the semantic state of a shape, which
    :func:`_semantic_state` watches; so a later cell cannot change what an earlier one made without the memory noticing.
    A list or a dict a cell made could be changed by the next cell that reads it, so it is not shared.
    """

    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return True
    if isinstance(value, (tuple, frozenset)):
        return all(_shareable(item) for item in value)
    kind = type(value)
    return kind.__module__ == "simplecadapi.core" or kind.__module__.startswith("simplecadapi.product.")


def _semantic_state(value: Any) -> tuple[int, ...]:
    """The semantic revision of every shape inside *value*: what a later cell could change in place.

    The SDK's values are functional except for the semantic state of a shape (tags, bindings, metadata): ``apply_tag``,
    ``set_metadata`` and ``auto_tag_faces`` change the shape they are called on, and return the very same object.  A
    memory that hands the same object to a later run would hand out the change as well (the copy on the disk is a fresh
    object each time and has none of it).  Each root of shapes counts its writes (``AnyShape._semantic_revision``); an
    entry whose numbers moved since it was kept is not handed out again.  A Part is its body, an Assembly its
    components; reading a shape, or consuming it in an operator, does not count.
    """

    if hasattr(value, "_semantic_revision"):
        return (value._semantic_revision(),)
    if isinstance(value, Part):
        return _semantic_state(value.body)
    if isinstance(value, Assembly):
        return tuple(n for component in value.components for n in _semantic_state(component.item))
    if isinstance(value, (tuple, frozenset)):
        return tuple(n for item in value for n in _semantic_state(item))
    return ()


class _CellMemory:
    """The values of cells restored or run in this process, by cache entry.

    Restoring a cell from the disk cache unpickles what it made: about a second for an assembly of the six-axis arm, and
    a parameter change in the editor restores four of those.  The same entry (the same code and inputs) names the same
    values, and the kernel is a long-lived process: the objects are kept and handed out again.
    """

    def __init__(self, limit: int = _MEMORY_ENTRIES) -> None:
        self._limit = limit
        # (loader, values, meta, the semantic revisions the values had when they were kept)
        self._entries: "OrderedDict[tuple[int, str, str], tuple[Any, dict[str, Any], dict[str, Any], tuple]]" = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(loader: Any, key: Any) -> tuple[int, str, str]:
        return (id(loader), str(key.cache_type), str(key.hash))

    def recall(self, loader: Any, key: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
        key = self._key(loader, key)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry[0] is not loader:  # (an id is reused once its loader is gone)
                return None
            if tuple(_semantic_state(value) for value in entry[1].values()) != entry[3]:
                del self._entries[key]  # something changed a shape in place since it was kept
                return None
            self._entries.move_to_end(key)
            return entry[1], entry[2]

    def remember(self, loader: Any, key: Any, values: dict[str, Any], meta: dict[str, Any], stateful: Any = ()) -> None:
        """Keep *values* (by name) as the entry *key* names; not for stateful cells or values a cell could change."""
        if stateful or not all(_shareable(value) for value in values.values()):
            return
        key = self._key(loader, key)
        revisions = tuple(_semantic_state(value) for value in values.values())
        with self._lock:
            self._entries[key] = (loader, values, meta, revisions)
            self._entries.move_to_end(key)
            while len(self._entries) > self._limit:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


def _attempt_with_memory(
    module: Any,
    graph: Any,
    cell_id: Any,
    scope: dict[str, Any],
    *,
    context: Any = None,
    pin_modules: bool = False,
    hash_type: str = "sha256",
    scoped_refs: Any = None,
    loader: Any,
    as_fn: bool = False,
) -> Any:
    """marimo's ``cache_attempt_from_hash``, asking the kernel's memory before the disk.

    marimo hashes the cell into a key, then asks the loader for the entry, and the loader unpickles what it finds
    while it answers (about a second for the six-axis arm's assemblies).  A loader with a memory is asked after the key
    and before the disk: an entry whose values this process holds is answered from them.
    """

    memory: _CellMemory | None = getattr(loader, "sca_memory", None)
    if memory is None:
        return _marimo_attempt(
            module, graph, cell_id, scope, context=context, pin_modules=pin_modules, hash_type=hash_type,
            scoped_refs=scoped_refs, loader=loader, as_fn=as_fn,
        )
    began = time.perf_counter()
    hasher = BlockHasher(
        module=module, graph=graph, cell_id=cell_id, scope=scope, context=context, pin_modules=pin_modules,
        hash_type=hash_type, scoped_refs=scoped_refs,
    )
    if as_fn:
        hasher.defs.clear()
    key = hasher.key
    hashed = time.perf_counter()
    kept = None if hasher.stateful_refs else memory.recall(loader, key)
    if kept is not None:
        defs, meta = kept
        attempt = MarimoCache(
            defs=dict(defs), hash=key.hash, cache_type=key.cache_type, stateful_refs=set(), hit=True, meta=dict(meta)
        )
        attempt.sca_from_memory = True  # type: ignore[attr-defined]
        attempt.sca_key_ms = (hashed - began) * 1000  # type: ignore[attr-defined]
        attempt.sca_restore_ms = (time.perf_counter() - hashed) * 1000  # type: ignore[attr-defined]
        return attempt
    attempt = loader.cache_attempt(hasher.defs, key, hasher.stateful_refs, glbls=scope)
    attempt.sca_key_ms = (hashed - began) * 1000  # type: ignore[attr-defined]
    attempt.sca_restore_ms = (time.perf_counter() - hashed) * 1000  # type: ignore[attr-defined]  (the loader's answer)
    if not attempt.hit or attempt.stateful_refs:
        return attempt
    restore_from_disk = attempt.restore

    def restore_and_remember(scope: dict[str, Any]) -> None:
        restore_from_disk(scope)
        values = {var: scope.get(lookup) for var, lookup in attempt.contextual_defs()}
        if not any(is_unhashable_stub(value) for value in values.values()):
            memory.remember(loader, key, values, dict(attempt.meta), attempt.stateful_refs)

    attempt.restore = restore_and_remember  # type: ignore[method-assign]
    return attempt


_marimo_attempt = _marimo_cached.cache_attempt_from_hash
_MEMORY_NEEDS = {"module", "graph", "cell_id", "scope", "context", "pin_modules", "hash_type", "scoped_refs", "loader", "as_fn"}

if _MEMORY_NEEDS <= set(inspect.signature(_marimo_attempt).parameters):
    _marimo_cached.cache_attempt_from_hash = _attempt_with_memory  # a loader without a memory is not affected
else:
    # The cell memory re-implements the first half of this marimo function; with another signature it cannot.
    say(
        "this marimo's cache_attempt_from_hash has another signature than the cell memory was written for: "
        "the editor kernel will not keep cell results in memory (every restore reads the disk)",
        once="cell-memory-marimo",
    )


class CellCache(CachedLifecycle):
    """marimo's cell cache, a store per digest, reporting its hits."""

    def __init__(
        self,
        graph: DirectedGraph,
        root: Path,
        digest_for: Callable[[CellImpl], str | None],
        *,
        memory: bool = False,
    ) -> None:
        # CachedLifecycle only takes a loader kind and stores in marimo's
        # default place; its loader is replaced by one stored under *root*
        # (the pickle kind is merely the cheapest to build and discard).
        super().__init__(graph, loader="pickle")
        self._root = root
        self._digest_for = digest_for
        self._stores: dict[str, LazyLoader] = {}
        self._cell_store: dict[CellId_t, LazyLoader] = {}
        self._active: dict[CellId_t, LazyLoader] = {}
        self.restored: set[CellId_t] = set()
        self._used: dict[str, None] = {}
        # The editor's kernel keeps what its cells made (see _CellMemory); a headless run is one process per run.
        self._memory: _CellMemory | None = _CellMemory() if memory and not os.environ.get("SCA_NO_CELL_MEMORY") else None
        self.last_timing: dict[CellId_t, tuple[float, float, float]] = {}
        """Per cell, the milliseconds of the last restore: the entry key, the values, the lineage record."""
        self.from_memory: set[CellId_t] = set()
        """The cells whose last restore came from memory, not from the disk."""


    @property
    def used(self) -> set[str]:
        """Digests of the cells this lifecycle has run or restored."""

        return set(self._used)

    def recent(self, limit: int) -> set[str]:
        """The *limit* digests used most recently."""

        return set(list(self._used)[-limit:])

    def _store(self, digest: str) -> LazyLoader:
        if digest not in self._stores:
            loader = LazyLoader(name=_CELLS, store=LazyStore(CompressedFileStore(str(self._root / digest))))
            loader.sca_memory = self._memory  # type: ignore[attr-defined]
            self._stores[digest] = loader
        return self._stores[digest]

    def setup(self, cell: CellImpl, glbls: MutableGlobals) -> Skip | None:
        digest = self._digest_for(cell)
        if digest is None:
            return None  # an uncached cell runs live
        loader = self._store(digest)
        self._used.pop(digest, None)
        self._used[digest] = None  # most recently used last
        self._loader = loader
        self._cell_store[cell.cell_id] = loader
        self._active[cell.cell_id] = loader
        decision = super().setup(cell, glbls)
        attempt_now = self._attempts.get(cell.cell_id)
        if isinstance(decision, Skip) and attempt_now is not None and getattr(attempt_now, "sca_from_memory", False):
            self.from_memory.add(cell.cell_id)
        else:
            self.from_memory.discard(cell.cell_id)
        lineage_began = time.perf_counter()
        if isinstance(decision, Skip):
            lineage_ok = self._load_lineage(cell, digest)
            self.last_timing[cell.cell_id] = (
                getattr(attempt_now, "sca_key_ms", 0.0),
                getattr(attempt_now, "sca_restore_ms", 0.0),
                (time.perf_counter() - lineage_began) * 1000,
            )
            if not lineage_ok:
                # The values are cached but the nodes behind them are missing (or are another graph's): run the
                # cell, and let the run write the entry and the nodes again.  The attempt becomes a miss for marimo
                # and the cell stays active here: dropping either made the cell run on every later call without
                # ever repairing what was missing.
                attempt = self._attempts.get(cell.cell_id)
                if attempt is not None:
                    attempt.hit = False
                self._exec_starts[cell.cell_id] = time.time()
                self.restored.discard(cell.cell_id)
                return None
            self.restored.add(cell.cell_id)
        else:
            self.restored.discard(cell.cell_id)
        return decision

    def discard(self, cell: CellImpl) -> None:
        """Delete the entry this cell was restored from (it could not be unpickled).

        marimo's own invalidation only makes the entry miss for the rest of the process and never overwrites it, so an
        entry that names classes which are gone would come back as a stub on every later run.
        """

        key = self._restored_keys.pop(cell.cell_id, None)
        digest = self._digest_for(cell)
        self.restored.discard(cell.cell_id)
        if key is None or digest is None:
            return
        directory = self._root / digest
        manifest = directory / key
        blobs = directory / manifest.parent.name / manifest.stem.split("_", 1)[-1]
        try:
            manifest.unlink(missing_ok=True)
            shutil.rmtree(blobs, ignore_errors=True)
        except OSError as error:
            say(f"could not delete the stale cache entry {manifest} ({error}); it will be read again")

    def _load_lineage(self, cell: CellImpl, digest: str) -> bool:
        from . import lineage

        try:
            # The entries of a run live in <state>/<id>/cache: the nodes of its cells belong to the graph of that id.
            return lineage.load(self._root / digest, str(cell.cell_id), self._root.parent.name)
        except Exception as error:  # noqa: BLE001 - an unreadable record is a miss, never a failure
            say(f"unreadable lineage record of cell {cell.cell_id} ({type(error).__name__}: {error}); running it again")
            return False


    def teardown(self, cell: CellImpl, glbls: MutableGlobals, run_result: RunResult) -> None:
        loader = self._active.pop(cell.cell_id, None)
        if loader is None:
            return
        self._loader = loader
        # A name that starts with an underscore belongs to its cell: no other
        # cell reads it, so storing its value only costs disk and restore time
        # (a cell that builds an assembly in `_a` stored it twice).  marimo
        # insists that an entry has a value for every name the cell defines,
        # so the name stays, with nothing in it.
        attempt = self._attempts.get(cell.cell_id)
        if attempt is not None and not attempt.hit:
            glbls = {**glbls}
            for name in attempt.defs:
                if name.startswith("_"):
                    glbls[name] = None
                    glbls[f"_cell_{cell.cell_id}_{name[1:]}"] = None
        live = glbls
        super().teardown(cell, glbls, run_result)
        if run_result.exception is None:
            self._save_lineage(cell, loader)
            if attempt is not None and not attempt.hit and self._memory is not None:
                # what this run made is what the entry names: the next evaluation with the same inputs takes it
                values = {var: (None if var.startswith("_") else live.get(lookup)) for var, lookup in attempt.contextual_defs()}
                if not any(is_unhashable_stub(value) for value in values.values()):
                    self._memory.remember(loader, attempt.key, values, dict(attempt.meta), attempt.stateful_refs)

    def _save_lineage(self, cell: CellImpl, loader: LazyLoader) -> None:
        from . import executor, lineage

        session = executor.take_session(cell.cell_id)
        digest = self._digest_for(cell)
        if session is None or digest is None or cell.cell_id in self.restored:
            return  # a restored cell keeps the record it was restored with
        if session.graph.graph_id != self._root.parent.name:
            return  # recorded under another id: not this run's lineage to keep
        lineage.save(self._root / digest, str(cell.cell_id), session)

    def _invalidate(self, cell_id: CellId_t) -> None:
        # The producer's entry lives in the store of its own digest.
        loader = self._cell_store.get(cell_id)
        if loader is None:
            super()._invalidate(cell_id)
            return
        current, self._loader = self._loader, loader
        try:
            super()._invalidate(cell_id)
        finally:
            self._loader = current

    def move(self, old: str, new: str) -> None:
        """Rename the store of digest *old* to *new* (a cell whose dependencies became known)."""

        source = self._root / old
        target = self._root / new
        self._stores.pop(old, None)
        if source != target and source.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            source.rename(target)

    def flush(self) -> None:
        """Wait until every entry is written (they are pickled on background threads)."""

        for loader in self._stores.values():
            loader.flush()


def prune(root: Path, used: set[str]) -> None:
    """Keep the stores this run used and the last run's; remove the rest."""

    if not root.is_dir():
        return
    runs = root / _RUNS
    try:
        previous = set(json.loads(runs.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        previous = set()
    keep = used | previous
    for entry in root.iterdir():
        if entry.name == _RUNS or entry.name in keep:
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
    runs.write_text(json.dumps(sorted(used)), encoding="utf-8")


__all__ = ["CellCache", "CellDigests", "cache_root", "prune"]

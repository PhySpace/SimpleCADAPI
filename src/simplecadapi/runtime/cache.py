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
import json
import shutil
import zlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

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
)
from .config import NotebookConfig
from .names import names_tag
from .deps import (
    CellSource,
    ancestors,
    cell_digest,
    cell_module_files,
    read_dependencies,
    recorded_dependents,
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
        self._uses = recorded_dependents(sources)
        self._kernel = kernel
        self._saved_tag: dict[str, str] = {}
        if saved:
            reached = ancestors(sources)
            own = {source.key: source.defs & saved.keys() for source in sources}
            for source in sources:
                names = set(own[source.key]).union(*(own[key] for key in reached[source.key]))
                if names:
                    payload = json.dumps({name: saved[name] for name in sorted(names)}, sort_keys=True)
                    self._saved_tag[source.key] = "p" + hashlib.sha256(payload.encode()).hexdigest()[:12]

    def digest(self, cell_id: CellId_t) -> str | None:
        """The digest for *cell_id*, ``None`` for a cell that is not cached."""

        deps = self._files.get(cell_id)
        if deps is None:
            return None  # the setup cell
        if self._kernel and cell_id in self._uses:
            return None
        named, fallback = names_tag(self.config.directory, deps.names)
        tag = ("use" if cell_id in self._uses else "") + self._saved_tag.get(cell_id, "") + named
        return cell_digest(self.config, deps.files | fallback, tag=tag)


class CellCache(CachedLifecycle):
    """marimo's cell cache, a store per digest, reporting its hits."""

    def __init__(
        self,
        graph: DirectedGraph,
        root: Path,
        digest_for: Callable[[CellImpl], str | None],
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

    @property
    def used(self) -> set[str]:
        """Digests of the cells this lifecycle has run or restored."""

        return set(self._used)

    def recent(self, limit: int) -> set[str]:
        """The *limit* digests used most recently."""

        return set(list(self._used)[-limit:])

    def _store(self, digest: str) -> LazyLoader:
        if digest not in self._stores:
            self._stores[digest] = LazyLoader(
                name=_CELLS, store=LazyStore(CompressedFileStore(str(self._root / digest)))
            )
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
        if isinstance(decision, Skip):
            self.restored.add(cell.cell_id)
        return decision

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
        super().teardown(cell, glbls, run_result)

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

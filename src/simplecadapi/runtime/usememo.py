"""The product of the last run of each child notebook, kept in the process (``use``).

A notebook that ``use`` s children runs them on every evaluation of the cell that calls it, and a run is not free even
when every cell of the child is restored from the cache: the cells are loaded, the product is projected onto its
definition and packaged (about a third of a second for a part, a few seconds for the gripper's six grandchildren).  The
editor's kernel is a long-lived process, so the result of a run is kept and handed out again while nothing it depends
on has changed.

What a run depends on is what its cell cache is keyed by: the child's static digest (its source, its header, the
local modules and input files it reads, the children it uses, recursively) and the overrides the caller passes.  One
entry is kept per (notebook, id): the run's nodes are registered by graph id, so the registry holds the last run's
nodes for that id and the entry has to be that run's product.  A notebook with no static digest (a computed ``use``
path), overrides that are not plain data, or ``SCA_NO_USE_MEMO=1`` are not kept.
"""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .children import notebook_digest

_MAX_ENTRIES = 128


@dataclass(frozen=True)
class Kept:
    """What a ``use`` hands back: the product and the files its run depended on."""

    product: Any
    path: Path
    dependencies: frozenset[Path]
    graph_id: str


_entries: "OrderedDict[tuple[str, str | None], tuple[tuple[str, str], Kept]]" = OrderedDict()
_owners: dict[str, tuple[str, str | None]] = {}  # graph id -> the entry whose run registered its nodes
_lock = threading.Lock()


def _signature(target: Path, overrides: Mapping[str, Any]) -> tuple[str, str] | None:
    """(the child's digest, the overrides as canonical JSON), or ``None`` when this call cannot be kept."""

    if os.environ.get("SCA_NO_USE_MEMO"):
        return None
    digest = notebook_digest(target)
    if digest is None:
        return None
    try:
        encoded = json.dumps(dict(overrides), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return None  # an Expr, a shape, a NaN: not plain data
    return digest, encoded


def recall(target: Path, id: str | None, overrides: Mapping[str, Any]) -> Kept | None:
    """The kept result of running *target* under *id* with *overrides*, if nothing it depends on changed."""

    signature = _signature(target, overrides)
    if signature is None:
        return None
    key = (str(target.resolve()), id)
    with _lock:
        entry = _entries.get(key)
        if entry is None or entry[0] != signature:
            return None
        _entries.move_to_end(key)
        return entry[1]


def keep(target: Path, id: str | None, overrides: Mapping[str, Any], kept: Kept) -> None:
    """Remember the result of a run (it replaces the entry of the same notebook and id)."""

    signature = _signature(target, overrides)
    key = (str(target.resolve()), id)
    with _lock:
        # The registry now holds this run's nodes: whatever entry owned the graph id before no longer matches.
        previous = _owners.pop(kept.graph_id, None)
        if previous is not None:
            _entries.pop(previous, None)
        _forget(key)  # (this key may have been kept under another graph id: the header id was edited)
        if signature is None:
            return
        _entries[key] = (signature, kept)
        _owners[kept.graph_id] = key
        while len(_entries) > _MAX_ENTRIES:
            _forget(next(iter(_entries)))


def _forget(key: tuple[str, str | None]) -> None:
    """Drop the entry of *key* and, if it is the owner of its graph id, that ownership (the lock is held)."""

    entry = _entries.pop(key, None)
    if entry is not None and _owners.get(entry[1].graph_id) == key:
        del _owners[entry[1].graph_id]


def clear() -> None:
    with _lock:
        _entries.clear()
        _owners.clear()

"""Tessellate the parts a cell made while the next cell computes (the editor kernel).

The editor publishes a preview once the cells have settled, and the preview of a part (its mesh and edge polylines)
takes tens of milliseconds -- for an assembly of nineteen parts, about 0.4 s that the person waits for after the last
cell.  :func:`preview_solid` keeps its result by the part's geometry, so doing the work earlier costs nothing and
changes nothing: the preview that follows finds every part in the cache.

The meshing itself runs without the interpreter lock (``cached_mesh``), so it overlaps with the cells that follow.
One daemon thread does the work, in submission order; a failing part is left for the real preview to report.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Iterable, Iterator

from simplecadapi._cpp import Assembly, Part, Solid

from .preview import preview_solid

_BACKLOG = 256
_queue: "queue.Queue[Solid]" = queue.Queue(maxsize=_BACKLOG)
_worker: threading.Thread | None = None
_lock = threading.Lock()


def solids_of(values: Iterable[Any]) -> Iterator[Solid]:
    """The solids a preview would draw for *values*: parts' bodies, assemblies' parts' bodies (each once)."""

    seen: set[int] = set()

    def visit(item: Any) -> Iterator[Solid]:
        if id(item) in seen:
            return
        seen.add(id(item))
        if isinstance(item, Part):
            body = item.body
            if isinstance(body, Solid):
                yield body
        elif isinstance(item, Assembly):
            for component in item.components:
                yield from visit(component.item)
        elif isinstance(item, Solid):
            yield item

    for value in values:
        yield from visit(value)


def submit(values: Iterable[Any]) -> int:
    """Queue the solids of *values* for tessellation; returns how many were queued (never blocks, never raises)."""

    queued = 0
    try:
        for solid in solids_of(values):
            try:
                _queue.put_nowait(solid)
            except queue.Full:
                break
            queued += 1
    except Exception:  # noqa: BLE001 - an optimisation: whatever a cell defined, it must not fail the cell
        return queued
    if queued:
        _ensure_worker()
    return queued


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="sca-preview-warm", daemon=True)
            _worker.start()


def _run() -> None:
    while True:
        try:
            solid = _queue.get(timeout=30.0)
        except queue.Empty:
            return  # the thread ends when idle; the next submit starts another
        try:
            preview_solid(solid)
        except Exception:  # noqa: BLE001 - the preview that follows reports a part that cannot be drawn
            pass

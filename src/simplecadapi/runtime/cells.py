"""What the runtime knows about a notebook's cells.

* **Cell keys.** Each cell gets a key from its code, ``c`` + the first 8
  hex digits of the code's sha256 (a second cell with the same code gets
  ``_2``, and so on).  The key is the namespace of every id the cell's
  session allocates, and it names the cell in recorded source positions.
  It follows the code rather than marimo's cell id because the cell cache
  is keyed by code too: node ids restored from the cache can never collide
  with ids another cell allocates.
* **Source lookup.** :class:`NotebookCells` implements
  :class:`~simplecadapi.recording.source_mapping.CellSourceMap`: it maps a
  frame's compile filename and line to the cell code running there, and a
  cell key to the cell's place in the saved notebook file.
* **Bound requirements.** The cache stores a cell's variables and nothing
  else, so a tolerance requirement survives a cache hit only if a variable
  holds it; :func:`bound_requirements` defines "holds".
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..params.tolerance import ToleranceRequirement
from ..recording.source_mapping import CellPlacement, ResolvedSource
from ._marimo import (
    CellId_t,
    CellImpl,
    get_filename,
    parse_notebook,
    solve_source_position,
)


def cell_keys(codes: Iterable[str]) -> list[str]:
    """Return the key of each cell, given the cells' code in notebook order."""

    seen: Counter[str] = Counter()
    keys: list[str] = []
    for code in codes:
        digest = "c" + hashlib.sha256(code.strip().encode("utf-8")).hexdigest()[:8]
        seen[digest] += 1
        keys.append(digest if seen[digest] == 1 else f"{digest}_{seen[digest]}")
    return keys


@dataclass(frozen=True)
class _Span:
    """Lines ``first..last`` of a compile filename hold one cell's code."""

    first: int
    last: int
    source: ResolvedSource


class NotebookCells:
    """Keys and source positions of the cells of one notebook.

    Built from the cells marimo compiled, in notebook order.  A cell's code
    compiles under a temporary filename of its own (the editor, and
    :func:`~._marimo.load_notebook`) or under the notebook path with absolute line numbers
    (a notebook run as a script); both map back to the cell's own code.
    """

    def __init__(self, path: Path, cells: Iterable[CellImpl]) -> None:
        self.path = path
        ordered = list(cells)
        keys = cell_keys(cell.code for cell in ordered)
        self._keys = {cell.cell_id: key for cell, key in zip(ordered, keys)}
        self._spans: dict[str, list[_Span]] = {}
        for cell, key in zip(ordered, keys):
            if cell.body is None:
                continue
            filename = cell.body.co_filename
            offset = _line_offset(cell, filename)
            if offset is None:
                continue
            source = ResolvedSource(
                text=cell.code, path=path, line_offset=offset, cell=key
            )
            span = _Span(offset + 1, offset + max(1, len(cell.code.splitlines())), source)
            self._spans.setdefault(filename, []).append(span)
        self._placements: dict[str, CellPlacement] | None = None

    def key(self, cell_id: CellId_t) -> str:
        """Return the key of the cell marimo calls *cell_id*."""

        return self._keys[cell_id]

    def resolve(self, filename: str, line: int) -> ResolvedSource | None:
        for span in self._spans.get(filename, ()):
            if span.first <= line <= span.last:
                return span.source
        return None

    def place(self, cell: str) -> CellPlacement | None:
        if self._placements is None:
            self._placements = _saved_placements(self.path)
        return self._placements.get(cell)


def _line_offset(cell: CellImpl, filename: str) -> int | None:
    """Return how far marimo shifted the lines of *cell* in *filename*."""

    if filename == get_filename(cell.cell_id):
        return 0
    # Same lookup marimo's compiler used to shift the cell into the file.
    position = solve_source_position(cell.code, filename)
    return position.lineno if position is not None else None


def _saved_placements(path: Path) -> dict[str, CellPlacement]:
    """Place every cell of the notebook file as saved, by key."""

    try:
        text = path.read_text(encoding="utf-8")
        notebook = parse_notebook(text)
    except (OSError, UnicodeError, SyntaxError):
        return {}
    if notebook is None or not notebook.valid:
        return {}
    lines = text.splitlines()
    keys = cell_keys(cell.code for cell in notebook.cells)
    return {
        key: CellPlacement(
            path=path,
            line_offset=cell.lineno,
            column_offset=_body_indent(lines, cell.lineno, cell.code),
        )
        for key, cell in zip(keys, notebook.cells)
    }


def _body_indent(lines: list[str], line_offset: int, code: str) -> int:
    """Return the indentation marimo added to *code* in the file *lines*.

    marimo reports where a cell's ``def`` starts, not how deep its body is
    indented, so compare the first non-blank line of the code with the
    same line in the file.
    """

    for number, line in enumerate(code.splitlines(), start=1):
        if not line.strip() or line_offset + number > len(lines):
            continue
        saved = lines[line_offset + number - 1]
        return (len(saved) - len(saved.lstrip())) - (len(line) - len(line.lstrip()))
    return 0


def bound_requirements(values: Iterable[object]) -> Iterator[ToleranceRequirement]:
    """Yield the tolerance requirements held by *values*.

    A value holds a requirement by being it, or by being a list, tuple,
    set or dict (values) that directly contains it.
    """

    for value in values:
        if isinstance(value, ToleranceRequirement):
            yield value
        elif isinstance(value, (list, tuple, set, frozenset, Mapping)):
            items = value.values() if isinstance(value, Mapping) else value
            yield from (item for item in items if isinstance(item, ToleranceRequirement))


__all__ = ["NotebookCells", "bound_requirements", "cell_keys"]

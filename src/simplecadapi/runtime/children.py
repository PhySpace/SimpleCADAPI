"""What a notebook is, to the notebook that uses it.

``use("child.py")`` makes a cell depend on the child.  When the path is a
literal that is known before the cell runs, so the cell is keyed by a digest
of the child, and each ``use`` is followed on its own: editing one child
recomputes the cells that use it, not those that use its siblings.

The digest is of what the child *is*: its text, the local modules it imports,
the project files it reads, and, in turn, the digest of every notebook it
uses.  Its text, not its syntax tree: the definition a run makes records where
in the file each step is, so a comment or a blank line changes the definition
of every notebook that embeds the child, and a cached parent must equal a
fresh one.
A child that computes a path itself has no such digest (``None``): the caller
then depends on whatever a run recorded.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import read_notebook_config
from .deps import file_digest, input_files, local_modules, use_calls


@dataclass(frozen=True)
class _Parts:
    syntax: str
    header: str
    modules: tuple[Path, ...]
    inputs: tuple[Path, ...]
    children: tuple[Path, ...]


_parts_memo: dict[tuple[Path, str | None], _Parts | None] = {}
_memo_lock = threading.Lock()


def notebook_digest(path: Path) -> str | None:
    """The digest of the notebook at *path* and what it depends on, or ``None``
    when that cannot be told without running it."""

    return _digest(path.resolve(), frozenset())


def _digest(path: Path, stack: frozenset[Path]) -> str | None:
    if path in stack:
        return "cycle"  # a run reports it
    parts = _parts(path)
    if parts is None:
        return None
    here = path.parent
    children: dict[str, str] = {}
    for child in parts.children:
        digest = _digest(child, stack | {path})
        if digest is None:
            return None
        children[_relative(child, here)] = digest
    payload = {
        "syntax": parts.syntax,
        "header": parts.header,
        "modules": {_relative(item, here): file_digest(item) for item in parts.modules},
        "inputs": {_relative(item, here): file_digest(item) for item in parts.inputs},
        "children": children,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _parts(path: Path) -> _Parts | None:
    key = (path, file_digest(path))
    with _memo_lock:
        if key in _parts_memo:
            return _parts_memo[key]
    parts = _analyse(path)
    with _memo_lock:
        if len(_parts_memo) > 512:
            _parts_memo.clear()
        _parts_memo[key] = parts
    return parts


def _analyse(path: Path) -> _Parts | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    config = read_notebook_config(path)
    if config is None:
        return None
    calls = use_calls(text)
    if any(call is None for call in calls):
        return None
    return _Parts(
        syntax=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        header=repr((config.id, config.revision, config.tolerance_profile, config.inputs)),
        modules=tuple(sorted(local_modules(config, [text]).values())),
        inputs=tuple(sorted(input_files(config))),
        children=tuple(sorted({(path.parent / call).resolve() for call in calls if call is not None})),
    )


def _relative(path: Path, start: Path) -> str:
    try:
        return Path(os.path.relpath(path, start)).as_posix()
    except ValueError:  # another drive on Windows
        return path.as_posix()


__all__ = ["notebook_digest"]

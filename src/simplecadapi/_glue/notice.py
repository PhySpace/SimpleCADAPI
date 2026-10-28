"""A line on stderr for a failure that is handled and must still be seen (never a silent ``except``)."""

from __future__ import annotations

import sys
import threading

_said: set[str] = set()
_lock = threading.Lock()


def say(message: str, *, once: str | None = None) -> None:
    """Print ``[sca] message``; with *once*, only the first time that key is used in this process."""

    if once is not None:
        with _lock:
            if once in _said:
                return
            _said.add(once)
    print(f"[sca] {message}", file=sys.stderr, flush=True)

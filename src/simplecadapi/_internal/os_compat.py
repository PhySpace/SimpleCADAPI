"""OS-portability primitives for byte-exact file IO and console output.

Windows defaults differ from POSIX in two ways that must not surface as
corrupted bytes or masked failures:

- ``os.open`` without ``O_BINARY`` opens in text mode: ``read()`` strips
  every CR and ``write()`` expands every LF, so byte counts and hashes
  drift on any checkout made with ``core.autocrlf=true``.
- Legacy consoles (cp1252) raise ``UnicodeEncodeError`` on non-ASCII
  diagnostic output, which can replace the real failure inside an error
  handler.
"""

from __future__ import annotations

import os
from typing import Iterable


def with_binary_flag(flags: int) -> int:
    """Return read/write flags forced into binary mode on Windows."""

    return flags | getattr(os, "O_BINARY", 0)


def harden_console_streams(streams: Iterable[object]) -> None:
    """Escape instead of crash when a stream cannot encode a diagnostic.

    Only non-UTF streams with strict error handling are reconfigured, so
    UTF-8 consoles and host-configured streams keep their behavior; the
    real failure stays visible instead of being replaced by a
    ``UnicodeEncodeError`` from a diagnostic print.
    """

    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        encoding = (getattr(stream, "encoding", "") or "")
        normalized = encoding.replace("-", "").replace("_", "").lower()
        if "utf" in normalized:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (ValueError, OSError):
            continue


__all__ = ["harden_console_streams", "with_binary_flag"]

"""Where a shape came from: the bytes it was read from, kept on the wrapper so it can be pickled by value."""

from __future__ import annotations

from simplecadapi._glue.compat import remember_source_bytes, source_bytes

__all__ = ["remember_source_bytes", "source_bytes"]

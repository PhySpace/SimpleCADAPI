"""Lazy access to pymupdf for the drawing inspection namespace.

pymupdf (AGPL-3.0 / Artifex commercial dual license) is an optional dependency
of the ``drawing`` extra. It is needed only by the engineering-drawing family,
never by modeling, export or rendering, so ``import simplecadapi`` must work
without it. Modules bind the proxy exported here under the name ``pymupdf``
(real module under ``TYPE_CHECKING``); the first attribute access performs the
actual import, and a missing pymupdf surfaces as an ImportError naming the
extra to install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pymupdf  # noqa: F401

_MISSING_PYMUPDF_MESSAGE = (
    "simplecadapi.inspect.drawing requires the optional 'drawing' extra; "
    "install it with: pip install 'simplecadapi[drawing]' (provides pymupdf)"
)


class _LazyPymupdf:
    """Stand-in for the ``pymupdf`` module that imports it on first use."""

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        try:
            import pymupdf
        except ImportError as exc:
            raise ImportError(_MISSING_PYMUPDF_MESSAGE) from exc
        return getattr(pymupdf, name)


pymupdf = _LazyPymupdf()

__all__ = ["pymupdf"]

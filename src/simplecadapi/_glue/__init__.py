"""The C++ module ``simplecadapi._cpp`` and the Python glue that adapts it to the layers that stay Python.

``install()`` runs once, first thing in ``simplecadapi/__init__``: it prepares the C++ module (error classes, signature
wrappers, recording wrappers, docstrings; see ``compat.prepare``).  Everything the SDK used to import from its own
Python modules (``simplecadapi.core``, ``simplecadapi.operators.*``, ...) is a real forwarding module that re-exports
the C++ names; the Python-side helpers they add live in ``glue.py``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

_NATIVE_PKG = "simplecadapi._cpp"

_native_module: Any = None
_installed = False


def _import_native() -> Any:
    """The C++ module ``simplecadapi._cpp``: in a wheel it is installed with the package, in a checkout the CMake
    development build (``src/cpp``) writes the extension next to its Python files in ``src/simplecadapi/_cpp``."""

    return importlib.import_module(_NATIVE_PKG)


def native() -> Any:
    global _native_module
    if _native_module is None:
        try:
            _native_module = _import_native()
        except ImportError as exc:  # pragma: no cover - environment problem
            raise ImportError(
                "simplecadapi needs its compiled C++ module 'simplecadapi._cpp': install a wheel, or build the "
                "extension in place (cmake -S src/cpp -B src/cpp/build/dev && cmake --build src/cpp/build/dev)"
            ) from exc
    return _native_module


def install() -> None:
    global _installed
    if _installed:
        return
    nat = native()
    from . import compat

    try:  # the graph JSON names the SDK version that produced it
        from importlib import metadata as _metadata

        nat.set_producer_version(_metadata.version("simplecadapi"))
    except Exception:  # noqa: BLE001 - not installed: the graph keeps its default
        pass

    _installed = True
    compat.prepare(nat)

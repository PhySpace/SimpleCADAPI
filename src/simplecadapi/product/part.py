"""Parts.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_topo.cpp`` -> ``src/cpp/src/topo``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_topo.cpp
    Solid,
    # (defined by the module itself)
    Connector,
    Material,
    Part,
)

__all__ = [
    "Connector",
    "Material",
    "Part",
    "Solid",
]

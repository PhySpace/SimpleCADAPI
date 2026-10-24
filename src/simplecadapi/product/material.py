"""Materials.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_core.cpp`` -> ``src/cpp/src/core``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_core.cpp
    Vec3,
    # (defined by the module itself)
    Material,
)

__all__ = [
    "Material",
    "Vec3",
]

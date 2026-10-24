"""``simplecadapi.std.chain``: the C++ module's ``std.chain`` namespace.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_std.cpp`` -> ``src/cpp/src/std``
"""

from __future__ import annotations

import simplecadapi._cpp as _cpp

_ns = _cpp.std.chain

# bind_std.cpp
make_roller_chain_sprocket_rsolid = _ns.make_roller_chain_sprocket_rsolid

__all__ = [
    "make_roller_chain_sprocket_rsolid",
]

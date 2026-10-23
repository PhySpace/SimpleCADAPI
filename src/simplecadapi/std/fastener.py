"""``simplecadapi.std.fastener``: the C++ module's ``std.fastener`` namespace.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_std.cpp`` -> ``src/cpp/src/std``
"""

from __future__ import annotations

import simplecadapi._cpp as _cpp

_ns = _cpp.std.fastener

# bind_std.cpp
make_bolt_rsolid = _ns.make_bolt_rsolid
make_nut_rsolid = _ns.make_nut_rsolid

__all__ = [
    "make_bolt_rsolid",
    "make_nut_rsolid",
]

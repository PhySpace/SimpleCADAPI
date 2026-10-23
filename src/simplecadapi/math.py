"""``simplecadapi.math``: the C++ module's ``math`` namespace.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_reactive_math.cpp`` -> ``src/cpp/src/reactive``
"""

from __future__ import annotations

import simplecadapi._cpp as _cpp

_ns = _cpp.math

# bind_reactive_math.cpp
BSplineFitResult = _ns.BSplineFitResult
fit_cubic_bspline_control_points = _ns.fit_cubic_bspline_control_points

__all__ = [
    "BSplineFitResult",
    "fit_cubic_bspline_control_points",
]

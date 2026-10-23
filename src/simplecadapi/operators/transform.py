"""Operators of the ``transform`` group.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_ops_features.cpp`` -> ``src/cpp/src/ops/features``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_ops_features.cpp
    linear_pattern_rsolidlist,
    mirror_shape,
    radial_pattern_rsolidlist,
    rotate_shape,
    scale_rsolid,
    transform_rsolid,
    translate_shape,
)

__all__ = [
    "linear_pattern_rsolidlist",
    "mirror_shape",
    "radial_pattern_rsolidlist",
    "rotate_shape",
    "scale_rsolid",
    "transform_rsolid",
    "translate_shape",
]

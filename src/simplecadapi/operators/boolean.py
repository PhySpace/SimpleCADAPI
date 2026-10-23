"""Operators of the ``boolean`` group.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_ops_features.cpp`` -> ``src/cpp/src/ops/features``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_ops_features.cpp
    boolean_rsolidlist,
    cut_rsolid,
    diagnose_boolean_failure,
    intersect_rsolid,
    union_rsolid,
    # (defined by the module itself)
    BooleanDiagnosis,
    make_2d_cut_rface,
    make_2d_intersect_rface,
    make_2d_union_rface,
)

__all__ = [
    "BooleanDiagnosis",
    "boolean_rsolidlist",
    "cut_rsolid",
    "diagnose_boolean_failure",
    "intersect_rsolid",
    "make_2d_cut_rface",
    "make_2d_intersect_rface",
    "make_2d_union_rface",
    "union_rsolid",
]

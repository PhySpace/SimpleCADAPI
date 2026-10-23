"""Operators of the ``_diagnostics`` group.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_ops_features.cpp`` -> ``src/cpp/src/ops/features``

Names that carry Python-side behaviour (recording wrappers, typing aliases) come from
``simplecadapi/_native/glue.py``.
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_ops_features.cpp
    assert_blend_volume_monotonic,
    diagnose_blend_failure,
    diagnose_boolean_failure,
    raise_loft_failure_if_diagnosed,
    # (defined by the module itself)
    BlendDiagnosis,
    BooleanDiagnosis,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

_RENDER_DEDUP = _glue._RENDER_DEDUP
diagnostics_dir = _glue.diagnostics_dir

__all__ = [
    "BlendDiagnosis",
    "BooleanDiagnosis",
    "assert_blend_volume_monotonic",
    "diagnose_blend_failure",
    "diagnose_boolean_failure",
    "diagnostics_dir",
    "raise_loft_failure_if_diagnosed",
]

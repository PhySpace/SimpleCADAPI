"""Tracking scopes.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_ops_features.cpp`` -> ``src/cpp/src/ops/features``
  * ``bind_topo.cpp`` -> ``src/cpp/src/topo``

Names that carry Python-side behaviour (recording wrappers, typing aliases) come from
``simplecadapi/_native/glue.py``.
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_ops_features.cpp
    current_tracking_policy,
    tracking_policy_scope,
    # bind_topo.cpp
    Edge,
    Face,
    Solid,
    Vertex,
    Wire,
    # (defined by the module itself)
    TrackingPolicy,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

graph_tracking_scope = _glue.graph_tracking_scope

__all__ = [
    "Edge",
    "Face",
    "Solid",
    "TrackingPolicy",
    "Vertex",
    "Wire",
    "current_tracking_policy",
    "graph_tracking_scope",
    "tracking_policy_scope",
]

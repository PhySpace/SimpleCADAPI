"""The operation graph and its recording session.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_core.cpp`` -> ``src/cpp/src/core``
  * ``bind_reactive_exprs.cpp`` -> ``src/cpp/src/reactive``
  * ``bind_reactive_graph.cpp`` -> ``src/cpp/src/reactive``
  * ``bind_reactive_session.cpp`` -> ``src/cpp/src/reactive``
  * ``bind_semantic.cpp`` -> ``src/cpp/src/semantic``
  * ``bind_topo.cpp`` -> ``src/cpp/src/topo``

Names that carry Python-side behaviour (recording wrappers, typing aliases) come from
``simplecadapi/_native/glue.py``.
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_core.cpp
    get_current_cs,
    use_coordinate_system,
    # bind_reactive_exprs.cpp
    ExpressionGraph,
    canonicalize_params,
    referenced_expressions,
    # bind_reactive_graph.cpp
    FrameGraph,
    FrameNode,
    OperationGraph,
    OperationNode,
    # bind_reactive_session.cpp
    get_active_session,
    isolated_recording,
    suspend_graph_recording,
    # bind_semantic.cpp
    SemanticDelta,
    SemanticRef,
    # bind_topo.cpp
    Compound,
    Edge,
    Face,
    Shell,
    Solid,
    Vertex,
    Wire,
    # (defined by the module itself)
    Assembly,
    Part,
    WORLD_CS,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

GraphSession = _glue.GraphSession
attach_graph_node = _glue.attach_graph_node
attach_semantic_graph_node = _glue.attach_semantic_graph_node
record_operation = _glue.record_operation
record_operation_if_active = _glue.record_operation_if_active

__all__ = [
    "Assembly",
    "Compound",
    "Edge",
    "ExpressionGraph",
    "Face",
    "FrameGraph",
    "FrameNode",
    "GraphSession",
    "OperationGraph",
    "OperationNode",
    "Part",
    "SemanticDelta",
    "SemanticRef",
    "Shell",
    "Solid",
    "Vertex",
    "WORLD_CS",
    "Wire",
    "attach_graph_node",
    "attach_semantic_graph_node",
    "canonicalize_params",
    "get_active_session",
    "get_current_cs",
    "isolated_recording",
    "record_operation",
    "record_operation_if_active",
    "referenced_expressions",
    "suspend_graph_recording",
    "use_coordinate_system",
]

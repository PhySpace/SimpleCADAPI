"""Shape, topology and coordinate-system classes.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_core.cpp`` -> ``src/cpp/src/core``
  * ``bind_semantic.cpp`` -> ``src/cpp/src/semantic``
  * ``bind_topo.cpp`` -> ``src/cpp/src/topo``

Names that carry Python-side behaviour (recording wrappers, typing aliases) come from
``simplecadapi/_native/glue.py``.
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_core.cpp
    CoordinateSystem,
    SimpleWorkplane,
    Vec3,
    get_current_cs,
    # bind_semantic.cpp
    TagBinding,
    TagEvidence,
    TagLineageWitness,
    TagProducer,
    # bind_topo.cpp
    AnyShape,
    Compound,
    Edge,
    Face,
    Shell,
    Solid,
    Vertex,
    Wire,
    # (defined by the module itself)
    LineagePolicy,
    SimpleCADError,
    TagAttachment,
    TagProducerKind,
    TagScope,
    TopologyPropagation,
    WORLD_CS,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

TaggedMixin = _glue.TaggedMixin
clone_semantic_shape_view = _glue.clone_semantic_shape_view
use_coordinate_system = _glue.use_coordinate_system

__all__ = [
    "AnyShape",
    "Compound",
    "CoordinateSystem",
    "Edge",
    "Face",
    "LineagePolicy",
    "Shell",
    "SimpleCADError",
    "SimpleWorkplane",
    "Solid",
    "TagAttachment",
    "TagBinding",
    "TagEvidence",
    "TagLineageWitness",
    "TagProducer",
    "TagProducerKind",
    "TagScope",
    "TaggedMixin",
    "TopologyPropagation",
    "Vec3",
    "Vertex",
    "WORLD_CS",
    "Wire",
    "clone_semantic_shape_view",
    "get_current_cs",
    "use_coordinate_system",
]

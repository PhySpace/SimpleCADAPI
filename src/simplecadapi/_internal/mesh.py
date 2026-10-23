"""Internal mesh companion data: built on first use, kept on the solid per tolerance.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_io.cpp`` -> ``src/cpp/src/io``
"""

from __future__ import annotations

import simplecadapi._cpp as _cpp

_ns = _cpp._internal_mesh

# bind_io.cpp
FaceTriangleRange = _ns.FaceTriangleRange
TriMesh = _ns.TriMesh
build_solid_trimesh = _ns.build_solid_trimesh
cached_mesh = _ns.cached_mesh
mesh_error = _ns.mesh_error
# (defined in Python or by the module itself)
DEFAULT_ANGULAR_TOLERANCE = _ns.DEFAULT_ANGULAR_TOLERANCE
DEFAULT_LINEAR_TOLERANCE = _ns.DEFAULT_LINEAR_TOLERANCE
MESH_ERROR_RUNTIME_KEY = _ns.MESH_ERROR_RUNTIME_KEY
MESH_RUNTIME_KEY = _ns.MESH_RUNTIME_KEY

__all__ = [
    "DEFAULT_ANGULAR_TOLERANCE",
    "DEFAULT_LINEAR_TOLERANCE",
    "FaceTriangleRange",
    "MESH_ERROR_RUNTIME_KEY",
    "MESH_RUNTIME_KEY",
    "TriMesh",
    "build_solid_trimesh",
    "cached_mesh",
    "mesh_error",
]

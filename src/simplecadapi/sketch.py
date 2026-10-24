"""Sketch documents and their constraints.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_reactive_exprs.cpp`` -> ``src/cpp/src/reactive``
  * ``bind_sketch.cpp`` -> ``src/cpp/src/sketch``
  * ``bind_topo.cpp`` -> ``src/cpp/src/topo``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_reactive_exprs.cpp
    evaluate_scalar,
    # bind_sketch.cpp
    Sketch,
    SketchConstraint,
    SketchConstraintDiagnostic,
    SketchEntity,
    SketchRef,
    SketchSolveResult,
    # bind_topo.cpp
    Edge,
    Face,
    Wire,
)

__all__ = [
    "Edge",
    "Face",
    "Sketch",
    "SketchConstraint",
    "SketchConstraintDiagnostic",
    "SketchEntity",
    "SketchRef",
    "SketchSolveResult",
    "Wire",
    "evaluate_scalar",
]

"""Assembly constraints.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_product_values.cpp`` -> ``src/cpp/src/product``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_product_values.cpp
    ConstraintReport,
    ConstraintResidual,
    # (defined by the module itself)
    ConnectorRef,
    Constraint,
    ScalarLimit,
)

__all__ = [
    "ConnectorRef",
    "Constraint",
    "ConstraintReport",
    "ConstraintResidual",
    "ScalarLimit",
]

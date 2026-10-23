"""Assembly constraint solving.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_product_values.cpp`` -> ``src/cpp/src/product``
  * ``bind_sdk_compat.cpp`` -> ``src/cpp/src (several; see the binding file)``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_product_values.cpp
    ConstraintReport,
    ConstraintResidual,
    # bind_sdk_compat.cpp
    constraint_reports_match,
    inspect_assembly_constraints,
    resolve_item_connector_placement,
    solve_assembly_constraints,
    # (defined by the module itself)
    Assembly,
    ConnectorRef,
    Constraint,
    Placement,
)

__all__ = [
    "Assembly",
    "ConnectorRef",
    "Constraint",
    "ConstraintReport",
    "ConstraintResidual",
    "Placement",
    "constraint_reports_match",
    "inspect_assembly_constraints",
    "resolve_item_connector_placement",
    "solve_assembly_constraints",
]

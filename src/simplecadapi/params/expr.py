"""Scalar expressions, variables and constants.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_reactive_exprs.cpp`` -> ``src/cpp/src/reactive``
  * ``bind_reactive_units.cpp`` -> ``src/cpp/src/reactive``

Names that carry Python-side behaviour (recording wrappers, typing aliases) come from
``simplecadapi/_native/glue.py``.
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_reactive_exprs.cpp
    Const,
    DimensionTolerance,
    Expr,
    ExpressionGraph,
    Var,
    atan2,
    canonicalize_params,
    const,
    evaluate_scalar,
    evaluate_value,
    lift_scalar,
    referenced_expressions,
    var,
    # bind_reactive_units.cpp
    Dimension,
    Unit,
    get_unit,
    unit_from_payload,
    unit_to_payload,
    # (defined by the module itself)
    acos,
    asin,
    atan,
    cos,
    sin,
    sqrt,
    tan,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

ScalarExpr = _glue.ScalarExpr
ScalarExprBase = _glue.ScalarExprBase
ScalarLike = _glue.ScalarLike
ToleranceLike = _glue.ToleranceLike
_expr_signature = _glue._expr_signature
coerce_dimension_tolerance = _glue.coerce_dimension_tolerance

__all__ = [
    "Const",
    "Dimension",
    "DimensionTolerance",
    "Expr",
    "ExpressionGraph",
    "ScalarExpr",
    "ScalarExprBase",
    "ScalarLike",
    "ToleranceLike",
    "Unit",
    "Var",
    "acos",
    "asin",
    "atan",
    "atan2",
    "canonicalize_params",
    "coerce_dimension_tolerance",
    "const",
    "cos",
    "evaluate_scalar",
    "evaluate_value",
    "get_unit",
    "lift_scalar",
    "referenced_expressions",
    "sin",
    "sqrt",
    "tan",
    "unit_from_payload",
    "unit_to_payload",
    "var",
]

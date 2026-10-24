"""Units and dimensions.

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
    expression_uses_units,
    infer_dimension,
    # bind_reactive_units.cpp
    Dimension,
    Unit,
    canonical_unit_for_dimension,
    convert_value,
    get_unit,
    unit_from_payload,
    unit_to_payload,
    # (defined by the module itself)
    ANGLE,
    AREA,
    CM,
    CUBIC_CM,
    CUBIC_FOOT,
    CUBIC_INCH,
    CUBIC_M,
    CUBIC_MM,
    DEGREE,
    DIMENSIONLESS,
    FOOT,
    INCH,
    LENGTH,
    M,
    MM,
    ONE,
    PERCENT,
    RADIAN,
    SQUARE_CM,
    SQUARE_FOOT,
    SQUARE_INCH,
    SQUARE_M,
    SQUARE_MM,
    UnitValidationError,
    VOLUME,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

UnitLike = _glue.UnitLike

__all__ = [
    "ANGLE",
    "AREA",
    "CM",
    "CUBIC_CM",
    "CUBIC_FOOT",
    "CUBIC_INCH",
    "CUBIC_M",
    "CUBIC_MM",
    "DEGREE",
    "DIMENSIONLESS",
    "Dimension",
    "FOOT",
    "INCH",
    "LENGTH",
    "M",
    "MM",
    "ONE",
    "PERCENT",
    "RADIAN",
    "SQUARE_CM",
    "SQUARE_FOOT",
    "SQUARE_INCH",
    "SQUARE_M",
    "SQUARE_MM",
    "Unit",
    "UnitLike",
    "UnitValidationError",
    "VOLUME",
    "canonical_unit_for_dimension",
    "convert_value",
    "expression_uses_units",
    "get_unit",
    "infer_dimension",
    "unit_from_payload",
    "unit_to_payload",
]

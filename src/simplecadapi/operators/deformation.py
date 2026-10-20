"""Moved: the operators this module held live in the module of their family (``_MOVED``).

Kept so that ``from simplecadapi.operators.deformation import <name>`` keeps working;
import from the package root instead, ``from simplecadapi import <name>``.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_MOVED = {
    "scale_rsolid": "transform",
    "transform_rsolid": "transform",
    "offset_rsolid": "features",
    "boolean_rsolidlist": "boolean",
}


def __getattr__(name: str):
    family = _MOVED.get(name)
    if family is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    warnings.warn(
        f"{__name__}.{name} moved to simplecadapi.operators.{family}; "
        f"import it from simplecadapi instead (from simplecadapi import {name})",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(import_module(f"simplecadapi.operators.{family}"), name)

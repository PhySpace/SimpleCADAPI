"""Assemblies and components.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_product_values.cpp`` -> ``src/cpp/src/product``
  * ``bind_sdk_compat.cpp`` -> ``src/cpp/src (several; see the binding file)``

Names that carry Python-side behaviour (recording wrappers, typing aliases) come from
``simplecadapi/_native/glue.py``.
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_product_values.cpp
    Component,
    PublicConnectorRef,
    # bind_sdk_compat.cpp
    resolve_connector,
    resolve_item_connector,
    # (defined by the module itself)
    Assembly,
    ConnectorRef,
    Constraint,
    Part,
    Placement,
)

# simplecadapi/_native/glue.py
from simplecadapi._glue import names as _glue

_AUTHORED_PLACEMENTS_RUNTIME_KEY = _glue._AUTHORED_PLACEMENTS_RUNTIME_KEY
_component_occurrence_placements = _glue._component_occurrence_placements
_restore_component_occurrence_placements = _glue._restore_component_occurrence_placements

__all__ = [
    "Assembly",
    "Component",
    "ConnectorRef",
    "Constraint",
    "Part",
    "Placement",
    "PublicConnectorRef",
    "resolve_connector",
    "resolve_item_connector",
]

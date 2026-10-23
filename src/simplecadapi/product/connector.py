"""Connectors.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_core.cpp`` -> ``src/cpp/src/core``
  * ``bind_sdk_compat.cpp`` -> ``src/cpp/src (several; see the binding file)``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_core.cpp
    Vec3,
    # bind_sdk_compat.cpp
    resolve_connector,
    resolve_connector_placement,
    resolve_connector_ref_placement,
    resolve_item_connector,
    resolve_item_connector_placement,
    # (defined by the module itself)
    Connector,
    ConnectorAnchor,
    ConnectorRef,
    GeometryRef,
    Placement,
)

__all__ = [
    "Connector",
    "ConnectorAnchor",
    "ConnectorRef",
    "GeometryRef",
    "Placement",
    "Vec3",
    "resolve_connector",
    "resolve_connector_placement",
    "resolve_connector_ref_placement",
    "resolve_item_connector",
    "resolve_item_connector_placement",
]

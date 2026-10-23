"""``simplecadapi.ql``: the C++ module's ``ql`` namespace.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_core.cpp`` -> ``src/cpp/src/core``
  * ``bind_io.cpp`` -> ``src/cpp/src/io``
  * ``bind_ql.cpp`` -> ``src/cpp/src/ql``
"""

from __future__ import annotations

import simplecadapi._cpp as _cpp

_ns = _cpp.ql

# bind_core.cpp
origin = _ns.origin
# bind_io.cpp
vertices = _ns.vertices
# bind_ql.cpp
Query = _ns.Query
SerializableKey = _ns.SerializableKey
SerializablePredicate = _ns.SerializablePredicate
ShapeSelector = _ns.ShapeSelector
TraversalSpec = _ns.TraversalSpec
_Missing = _ns._Missing
_set_evidence_provider = _ns._set_evidence_provider
_testing = _ns._testing
and_ = _ns.and_
center_axis = _ns.center_axis
curve_type = _ns.curve_type
edges = _ns.edges
faces = _ns.faces
geo = _ns.geo
key = _ns.key
meta = _ns.meta
not_ = _ns.not_
op = _ns.op
operation_event = _ns.operation_event
or_ = _ns.or_
origin_role = _ns.origin_role
output_role = _ns.output_role
prop = _ns.prop
register_property_resolver = _ns.register_property_resolver
role = _ns.role
select = _ns.select
selector_from_dict = _ns.selector_from_dict
shells = _ns.shells
solids = _ns.solids
source_binding = _ns.source_binding
source_topology = _ns.source_topology
surface_type = _ns.surface_type
tag = _ns.tag
unregister_property_resolver = _ns.unregister_property_resolver
value = _ns.value
wires = _ns.wires
# (defined in Python or by the module itself)
MISSING = _ns.MISSING

__all__ = [
    "MISSING",
    "Query",
    "SerializableKey",
    "SerializablePredicate",
    "ShapeSelector",
    "TraversalSpec",
    "and_",
    "center_axis",
    "curve_type",
    "edges",
    "faces",
    "geo",
    "key",
    "meta",
    "not_",
    "op",
    "operation_event",
    "or_",
    "origin",
    "origin_role",
    "output_role",
    "prop",
    "register_property_resolver",
    "role",
    "select",
    "selector_from_dict",
    "shells",
    "solids",
    "source_binding",
    "source_topology",
    "surface_type",
    "tag",
    "unregister_property_resolver",
    "value",
    "vertices",
    "wires",
]

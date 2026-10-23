"""The Python-side names of the C++ port: helpers the kept layers need that the native module does not carry.

Generated from the registrations of ``compat.prepare``; the forwarding modules (``simplecadapi.operators``,
``simplecadapi.recording.graph``, ...) re-export them under the paths the SDK always had.
"""

from __future__ import annotations

from . import compat as _compat


def _get(key: str, name: str):
    value = _compat.names_for(key)[name]
    return value() if getattr(value, "_lazy", False) else value

GraphSession = _get("recording.graph", "GraphSession")
ScalarExpr = _get("params.expr", "ScalarExpr")
ScalarExprBase = _get("params.expr", "ScalarExprBase")
ScalarLike = _get("params.expr", "ScalarLike")
TaggedMixin = _get("core", "TaggedMixin")
ToleranceLike = _get("params.expr", "ToleranceLike")
UnitLike = _get("params.units", "UnitLike")
_AUTHORED_PLACEMENTS_RUNTIME_KEY = _get("product.assembly", "_AUTHORED_PLACEMENTS_RUNTIME_KEY")
_RENDER_DEDUP = _get("operators._diagnostics", "_RENDER_DEDUP")
_assert_sketch_solve_snapshot_dict_matches = _get("operators", "_assert_sketch_solve_snapshot_dict_matches")
_brep_region_path = _get("operators", "_brep_region_path")
_component_occurrence_placements = _get("product.assembly", "_component_occurrence_placements")
_constrain_rsketch = _get("operators", "_constrain_rsketch")
_expr_signature = _get("params.expr", "_expr_signature")
_load_brep_region_rshape = _get("operators", "_load_brep_region_rshape")
_restore_component_occurrence_placements = _get("product.assembly", "_restore_component_occurrence_placements")
attach_graph_node = _get("recording.graph", "attach_graph_node")
attach_semantic_graph_node = _get("recording.graph", "attach_semantic_graph_node")
clone_semantic_shape_view = _get("core", "clone_semantic_shape_view")
coerce_dimension_tolerance = _get("params.expr", "coerce_dimension_tolerance")
diagnostics_dir = _get("operators._diagnostics", "diagnostics_dir")
record_operation = _get("recording.graph", "record_operation")
record_operation_if_active = _get("recording.graph", "record_operation_if_active")
remember_source_bytes = _get("_internal.shape_pickle", "remember_source_bytes")
source_bytes = _get("_internal.shape_pickle", "source_bytes")
use_coordinate_system = _get("core", "use_coordinate_system")

_LAZY = {
    "SCREENSHOT_VIEWS": "operators",
    "_OPERATION_OUTPUT_ROLE_CARDINALITY": "operators",
    "_execute_screenshot_render": "operators",
    "_prepare_screenshot_render": "operators",
    "_screenshot_views": "operators",
    "render_screenshot_rpath": "operators",
}


def __getattr__(name: str):
    """The names that import heavy modules (rendering) are resolved on first use."""

    if name in _LAZY:
        value = _get(_LAZY[name], name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def graph_tracking_scope(factory):
    """Decorator: build ``factory`` under the graph tracking policy."""

    from . import stdlib

    return stdlib.graph_tracking_scope(factory)

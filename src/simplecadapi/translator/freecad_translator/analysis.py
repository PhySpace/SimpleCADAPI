"""Pure graph analysis used by the FreeCAD compiler."""

from __future__ import annotations

from typing import AbstractSet, Set
import math

from simplecadapi._cpp import OperationGraph, OperationNode


def _contains_expr_refs(value: object) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("expr_id"), str) and value["expr_id"]:
            return True
        return any(_contains_expr_refs(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_expr_refs(child) for child in value)
    return False


TRANSPARENT_GEOMETRY_OPS = frozenset({"apply_tag_rselection"})


def unwrap_transparent_geometry_node(
    graph: OperationGraph,
    node: OperationNode | None,
) -> OperationNode | None:
    """Return the first geometry-producing node behind transparent wrappers."""

    seen: Set[str] = set()
    current = node
    while (
        current is not None
        and current.op in TRANSPARENT_GEOMETRY_OPS
        and len(current.inputs) == 1
        and current.node_id not in seen
    ):
        seen.add(current.node_id)
        current = graph.get_node(current.inputs[0].node_id)
    return current


def can_lower_circle_extrusion_to_cylinder(
    circle_node: OperationNode,
    extrusion_node: OperationNode,
) -> bool:
    """Return whether a circle extrusion exactly matches a native cylinder."""

    if _contains_expr_refs(circle_node.param_exprs) or _contains_expr_refs(
        extrusion_node.param_exprs
    ):
        return False
    try:
        normal = tuple(float(value) for value in circle_node.params["normal"])
        direction = tuple(float(value) for value in extrusion_node.params["direction"])
        if len(normal) != 3 or len(direction) != 3:
            return False
        normal_length = math.sqrt(sum(value * value for value in normal))
        direction_length = math.sqrt(sum(value * value for value in direction))
        if normal_length <= 1e-12 or direction_length <= 1e-12:
            return False
        cosine = sum(normal[index] * direction[index] for index in range(3)) / (
            normal_length * direction_length
        )
        return abs(abs(cosine) - 1.0) <= 1e-9
    except (KeyError, TypeError, ValueError):
        return False


def find_cylinder_profile_nodes(
    graph: OperationGraph,
    result_node_ids: AbstractSet[str],
) -> Set[str]:
    """Find single-use circle profiles represented by native cylinders."""

    use_counts: dict[str, int] = {}
    for graph_node in graph.topological_order():
        for input_ref in graph_node.inputs:
            use_counts[input_ref.node_id] = use_counts.get(input_ref.node_id, 0) + 1

    suppressed: Set[str] = set()
    for graph_node in graph.topological_order():
        if graph_node.op != "make_extrude_rsolid" or len(graph_node.inputs) != 1:
            continue
        profile_node = graph.get_node(graph_node.inputs[0].node_id)
        face_node = None
        if (
            profile_node is not None
            and profile_node.op == "make_face_from_wire_rface"
            and len(profile_node.inputs) == 1
        ):
            face_node = profile_node
            profile_node = graph.get_node(profile_node.inputs[0].node_id)
        if (
            profile_node is None
            or profile_node.op != "make_wire_from_edges_rwire"
            or len(profile_node.inputs) != 1
        ):
            continue
        edge_node = graph.get_node(profile_node.inputs[0].node_id)
        if edge_node is None or edge_node.op != "make_circle_redge":
            continue
        if not can_lower_circle_extrusion_to_cylinder(edge_node, graph_node):
            continue
        profile_ids = [profile_node.node_id]
        if face_node is not None:
            profile_ids.append(face_node.node_id)
        if any(node_id in result_node_ids for node_id in profile_ids):
            continue
        if any(use_counts.get(node_id, 0) != 1 for node_id in profile_ids):
            continue
        suppressed.update(profile_ids)
    return suppressed


def can_fold_transform_into_input(
    node: OperationNode,
    graph: OperationGraph,
    result_node_ids: AbstractSet[str],
) -> bool:
    """Return whether a single-use transform can mutate its source placement."""

    if (
        node.op not in {"make_translate_rshape", "make_rotate_rshape"}
        or len(node.inputs) != 1
    ):
        return False
    source = node.inputs[0]
    if source.op not in {
        "make_box_rsolid",
        "make_cone_rsolid",
        "make_cylinder_rsolid",
        "make_extrude_rsolid",
        "make_sphere_rsolid",
        "make_wire_from_edges_rwire",
        "make_face_from_wire_rface",
        "make_wire_from_sketch_rwire",
        "make_face_from_sketch_rface",
        "make_translate_rshape",
        "make_rotate_rshape",
    }:
        return False
    if source.node_id in result_node_ids:
        return False
    return graph.downstream_nodes(source.node_id) == [node.node_id]


def transform_feeds_only_loft(
    graph: OperationGraph,
    node_id: str,
    seen: Set[str],
) -> bool:
    """Return whether all paths from a transform terminate at loft nodes."""

    if node_id in seen:
        return False
    seen.add(node_id)
    downstream = graph.downstream_nodes(node_id)
    if not downstream:
        return False
    for downstream_id in downstream:
        downstream_node = graph.get_node(downstream_id)
        if downstream_node is None:
            return False
        if downstream_node.op == "make_loft_rsolid":
            continue
        if downstream_node.op in {"make_translate_rshape", "make_rotate_rshape"}:
            if transform_feeds_only_loft(graph, downstream_id, seen):
                continue
        return False
    return True


def should_materialize_transform_for_loft_section(
    node: OperationNode,
    graph: OperationGraph,
) -> bool:
    """Return whether a loft section transform requires a concrete object."""

    if (
        node.op not in {"make_translate_rshape", "make_rotate_rshape"}
        or len(node.inputs) != 1
    ):
        return False
    if not transform_feeds_only_loft(graph, node.node_id, set()):
        return False
    return node.inputs[0].op in {
        "make_wire_from_edges_rwire",
        "make_face_from_wire_rface",
        "make_wire_from_sketch_rwire",
        "make_face_from_sketch_rface",
        "make_translate_rshape",
        "make_rotate_rshape",
    }


__all__ = [
    "can_fold_transform_into_input",
    "can_lower_circle_extrusion_to_cylinder",
    "find_cylinder_profile_nodes",
    "should_materialize_transform_for_loft_section",
    "transform_feeds_only_loft",
    "unwrap_transparent_geometry_node",
]

"""Plan a human-readable FreeCAD model tree from the canonical operation DAG."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Set

from simplecadapi._cpp import OperationGraph, OperationNode
from .analysis import unwrap_transparent_geometry_node


_OPERATION_LABELS: Dict[str, str] = {
    "make_box_rsolid": "Box",
    "make_cylinder_rsolid": "Cylinder",
    "make_cone_rsolid": "Cone",
    "make_sphere_rsolid": "Sphere",
    "make_point_rvertex": "Point",
    "make_line_redge": "Line",
    "make_circle_redge": "Circle",
    "make_angle_arc_redge": "Arc",
    "make_three_point_arc_redge": "Three Point Arc",
    "make_spline_redge": "Spline",
    "make_helix_redge": "Helix",
    "make_wire_from_edges_rwire": "Profile",
    "make_face_from_wire_rface": "Profile",
    "make_face_from_wires_rface": "Profile",
    "make_sketch_rsketch": "Sketch",
    "make_wire_from_sketch_rwire": "Sketch",
    "make_face_from_sketch_rface": "Sketch",
    "make_extrude_rsolid": "Extrude",
    "make_revolve_rsolid": "Revolve",
    "make_loft_rsolid": "Loft",
    "make_sweep_rsolid": "Sweep",
    "make_twisted_sweep_rsolid": "Twisted Sweep",
    "make_cut_rsolid": "Cut",
    "make_union_rsolid": "Union",
    "make_intersect_rsolid": "Intersection",
    "make_2d_cut_rface": "Profile Cut",
    "make_2d_union_rface": "Profile Union",
    "make_2d_intersect_rface": "Profile Intersection",
    "make_fillet_rsolid": "Fillet",
    "make_chamfer_rsolid": "Chamfer",
    "make_shell_rsolid": "Shell",
    "make_mirror_rshape": "Mirror",
    "make_translate_rshape": "Move",
    "make_rotate_rshape": "Rotate",
    "make_part_rpart": "Part",
    "make_assembly_rassembly": "Assembly",
    "make_add_component_rassembly": "Component",
    "make_place_component_rassembly": "Component Placement",
    "make_material_rmaterial": "Material",
    "make_placement_rplacement": "Placement",
    "make_identity_placement_rplacement": "Placement",
    "make_compound_from_assembly_rcompound": "Assembly Result",
}

_PRODUCT_OPS = {
    "make_part_rpart",
    "make_assign_material_rpart",
    "make_assembly_rassembly",
    "make_add_component_rassembly",
    "make_place_component_rassembly",
    "make_add_connector_rpart",
    "make_set_public_connector_rassembly",

    "make_ground_component_rassembly",
    "make_unground_component_rassembly",
    "make_fixed_constraint_rassembly",
    "make_revolute_constraint_rassembly",
    "make_prismatic_constraint_rassembly",
    "make_gear_constraint_rassembly",
    "make_belt_constraint_rassembly",
    "make_rack_pinion_constraint_rassembly",
    "make_solve_assembly_constraints_rassembly",
    "evaluate_assembly_definition",
}

_PRODUCT_VALUE_OPS = _PRODUCT_OPS | {
    "make_material_rmaterial",
    "make_placement_rplacement",
    "make_identity_placement_rplacement",
    "make_face_connector_rconnector",
    "make_edge_connector_rconnector",
    "make_vertex_connector_rconnector",
    "make_placement_connector_rconnector",
    "make_connector_ref_rconnectorref",
    "reference_definition",
    "make_scalar_limit_rscalarlimit",
}

_ASSEMBLY_PROJECTION_OPS = {"make_compound_from_assembly_rcompound"}
_METADATA_ONLY_OPS = {"apply_tag_rselection"}


def _operation_label(op: str) -> str:
    known = _OPERATION_LABELS.get(str(op))
    if known:
        return known
    token = str(op)
    if token.startswith("make_"):
        token = token[5:]
    for suffix in (
        "_rsolid",
        "_rface",
        "_rwire",
        "_redge",
        "_rvertex",
        "_rshape",
        "_rsketch",
        "_rselection",
        "_rassembly",
        "_rpart",
        "_rcompound",
    ):
        if token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    words = [word for word in token.split("_") if word]
    return " ".join(word.capitalize() for word in words) or "Operation"


def _source(node: OperationNode) -> Dict[str, Any]:
    return dict(node.source) if isinstance(node.source, dict) else {}


def _assignment_targets(nodes: Iterable[OperationNode]) -> List[str]:
    targets: List[str] = []
    for node in nodes:
        source = _source(node)
        values = source.get("assignment_targets")
        if not isinstance(values, list):
            continue
        for value in values:
            target = " ".join(str(value).split())
            if target and target != "_" and target not in targets:
                targets.append(target)
    return targets


def _explicit_name(nodes: Sequence[OperationNode]) -> str:
    keys = (
        "name",
        "component_id",
        "part_id",
        "assembly_id",
        "connector_id",
        "constraint_id",
        "material_id",
    )
    for node in reversed(nodes):
        for key in keys:
            value = node.params.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _semantic_tag(nodes: Sequence[OperationNode]) -> str:
    tags = sorted({str(tag) for node in nodes for tag in node.tags})
    for prefix in ("role.", "anchor.", "group."):
        for tag in tags:
            if tag.startswith(prefix) and len(tag) > len(prefix):
                return tag[len(prefix) :].replace(".", " ")
    return ""


def _group_key(node: OperationNode) -> str:
    callsite_id = _source(node).get("callsite_id")
    return f"callsite:{callsite_id}" if callsite_id else f"node:{node.node_id}"


def _upstream_closure(graph: OperationGraph, node_id: str) -> Set[str]:
    seen: Set[str] = set()
    pending = [str(node_id)]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        node = graph.get_node(current)
        assert (
            node is not None
        ), "operation graph input closure is internally inconsistent"
        seen.add(current)
        pending.extend(inp.node_id for inp in node.inputs)
    return seen


def _terminal_nodes(
    graph: OperationGraph,
    nodes: Sequence[OperationNode],
    reachable_ids: Set[str],
) -> List[OperationNode]:
    ids = {node.node_id for node in nodes}
    terminals = [
        node
        for node in nodes
        if not any(
            downstream in ids and downstream in reachable_ids
            for downstream in graph.downstream_nodes(node.node_id)
        )
    ]
    return terminals


def _preferred_label(
    nodes: Sequence[OperationNode], representative: OperationNode
) -> str:
    explicit = _explicit_name(nodes)
    if representative.op in _PRODUCT_VALUE_OPS and explicit:
        return explicit
    targets = _assignment_targets(nodes)
    if targets:
        return ", ".join(targets)
    if explicit:
        return explicit
    semantic_nodes = [node for node in nodes if node.op not in _METADATA_ONLY_OPS]
    tag = _semantic_tag(semantic_nodes)
    if tag:
        return tag
    return _operation_label(representative.op)


def _unique_label(base: str, counts: Dict[str, int]) -> str:
    normalized = str(base).strip() or "Operation"
    counts[normalized] = counts.get(normalized, 0) + 1
    occurrence = counts[normalized]
    return normalized if occurrence == 1 else f"{normalized} ({occurrence})"


def _product_kind(op: str) -> str | None:
    if op in {
        "make_part_rpart",
        "make_assign_material_rpart",
        "make_add_connector_rpart",
    }:
        return "part"
    if op in _PRODUCT_OPS:
        return "assembly"
    return None


def _node_display_labels(graph: OperationGraph) -> Dict[str, str]:
    grouped: Dict[str, List[OperationNode]] = {}
    topo = graph.topological_order()
    reachable_ids = {node.node_id for node in topo}
    for node in topo:
        grouped.setdefault(_group_key(node), []).append(node)

    labels: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    for nodes in grouped.values():
        semantic_nodes = [node for node in nodes if node.op not in _METADATA_ONLY_OPS]
        terminals = _terminal_nodes(graph, semantic_nodes or nodes, reachable_ids)
        terminal_ids = {node.node_id for node in terminals}
        for node in nodes:
            if node.node_id not in terminal_ids:
                labels[node.node_id] = _operation_label(node.op)
        for terminal in terminals:
            label_nodes = nodes if len(terminals) == 1 else [terminal]
            labels[terminal.node_id] = _unique_label(
                _preferred_label(label_nodes, terminal), counts
            )
    return labels


def build_freecad_semantic_plan(
    graph: OperationGraph,
    result_node_ids: Sequence[str],
    *,
    document_name: str,
) -> Dict[str, Any]:
    """Build the native FreeCAD occurrence-tree plan.

    The canonical graph remains a value DAG.  FreeCAD occurrences are created
    later from each result path, so a shared input can appear independently
    below every consuming feature.  This plan only carries roots, reachability,
    and human-facing labels; it never creates a presentation-only copy.
    """
    node_labels = _node_display_labels(graph)
    roots: List[Dict[str, Any]] = []
    product_body_ids: Set[str] = set()
    display_product_node_ids: List[str] = []

    for node in graph.topological_order():
        if node.op != "make_part_rpart" or not node.inputs:
            continue
        body_node_id = node.inputs[0].node_id
        product_body_ids.add(body_node_id)
        body_label = node_labels.get(body_node_id) or _operation_label(
            graph.get_node(body_node_id).op
            if graph.get_node(body_node_id) is not None
            else "body"
        )
        roots.append(
            {
                "root_id": f"part:{node.node_id}",
                "kind": "part",
                "label": str(
                    node.params.get("name")
                    or node.params.get("part_id")
                    or node_labels.get(node.node_id)
                    or "Part"
                ),
                "product_node_id": node.node_id,
                "result_node_id": body_node_id,
                "result_label": body_label,
                "managed_node_ids": sorted(
                    _upstream_closure(graph, body_node_id),
                    key={
                        item.node_id: index
                        for index, item in enumerate(graph.topological_order())
                    }.__getitem__,
                ),
            }
        )

    for result_node_id in result_node_ids:
        result_node = graph.get_node(str(result_node_id))
        classified_node = unwrap_transparent_geometry_node(graph, result_node)
        if result_node is None or classified_node is None:
            continue
        if classified_node.op in _ASSEMBLY_PROJECTION_OPS:
            if classified_node.inputs:
                product_node = graph.get_node(classified_node.inputs[0].node_id)
                if (
                    product_node is not None
                    and _product_kind(product_node.op) is not None
                ):
                    if product_node.node_id not in display_product_node_ids:
                        display_product_node_ids.append(product_node.node_id)
            continue
        if _product_kind(classified_node.op) is not None:
            if classified_node.node_id not in display_product_node_ids:
                display_product_node_ids.append(classified_node.node_id)
            continue
        if result_node.node_id in product_body_ids:
            continue
        managed = _upstream_closure(graph, result_node.node_id)
        result_label = node_labels.get(result_node.node_id) or _operation_label(
            result_node.op
        )
        topo_index = {
            item.node_id: index for index, item in enumerate(graph.topological_order())
        }
        roots.append(
            {
                "root_id": f"geometry:{result_node.node_id}",
                "kind": "geometry",
                "label": f"{result_label} Model",
                "result_label": result_label,
                "product_node_id": None,
                "result_node_id": result_node.node_id,
                "managed_node_ids": sorted(managed, key=topo_index.__getitem__),
            }
        )
    return {
        "schema_version": "2.0",
        "document_label": str(document_name),
        "roots": roots,
        "display_product_node_ids": display_product_node_ids,
        "node_labels": node_labels,
    }


__all__ = ["build_freecad_semantic_plan"]

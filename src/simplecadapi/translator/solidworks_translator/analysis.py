"""Structural graph analysis and recorded geometry selectors.

Translation never replays source solids or measures expected feature results;
expected values are asserted by the test suite.
"""
from __future__ import annotations
import copy
import os
from typing import Any, Dict, List, Sequence, Set, Tuple
from ...topology import OperationGraph

_ASSEMBLY_ACTIVE_STATE_PRIORITY = (
    "operating",
    "locked",
    "nominal",
    "default",
    "middle",
    "middle_adjustment",
)



def _assembly_state_result_node_ids(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> Dict[str, List[str]]:
    """Group sibling assembly snapshots by the state suffix in their IDs."""

    node_ids = [str(node_id) for node_id in result_node_ids]
    if len(node_ids) < 2:
        return {}
    snapshots: List[Tuple[str, str, int]] = []
    for node_id in node_ids:
        node = graph.get_node(node_id)
        if node is None or node.op != "make_compound_from_assembly_rcompound":
            return {}
        assembly_id = str(node.params.get("assembly_id") or "")
        if not assembly_id:
            return {}
        snapshots.append(
            (
                node_id,
                assembly_id,
                int(node.params.get("component_count") or 0),
            )
        )
    if len({count for _, _, count in snapshots}) != 1:
        return {}
    common_prefix = os.path.commonprefix(
        [assembly_id for _, assembly_id, _ in snapshots]
    )
    separator_index = common_prefix.rfind("_")
    if separator_index <= 0:
        return {}
    state_prefix = common_prefix[: separator_index + 1]
    state_node_ids: Dict[str, List[str]] = {}
    for node_id, assembly_id, _ in snapshots:
        if not assembly_id.startswith(state_prefix):
            return {}
        state = assembly_id[len(state_prefix) :].strip("_")
        if not state or state in state_node_ids:
            return {}
        state_node_ids[state] = [node_id]
    return state_node_ids


def _result_dependency_node_ids(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> Set[str]:
    pending = [str(node_id) for node_id in result_node_ids]
    visited: Set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = graph.get_node(node_id)
        if node is None:
            continue
        pending.extend(str(input_ref.node_id) for input_ref in node.inputs)
        for key in ("selected_edge_node_ids", "selected_face_node_ids"):
            pending.extend(str(value) for value in node.params.get(key, []) or [])
    return visited


def _result_dependency_ops(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> Set[str]:
    pending = [str(node_id) for node_id in result_node_ids]
    visited: Set[str] = set()
    operations: Set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = graph.get_node(node_id)
        if node is None:
            continue
        operations.add(str(node.op))
        pending.extend(str(input_ref.node_id) for input_ref in node.inputs)
    return operations


def _preferred_result_node_ids(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> List[str]:
    """Choose the nominal snapshot from an explicitly named assembly state set."""

    node_ids = [str(node_id) for node_id in result_node_ids]
    state_node_ids = _assembly_state_result_node_ids(graph, node_ids)
    for state in _ASSEMBLY_ACTIVE_STATE_PRIORITY:
        selected = state_node_ids.get(state)
        if selected is not None:
            return list(selected)
    node_by_id = {str(node.node_id): node for node in graph.nodes}
    assembly_results = [
        node_id
        for node_id in node_ids
        if getattr(node_by_id.get(node_id), "op", None)
        == "make_compound_from_assembly_rcompound"
    ]
    if assembly_results:
        return assembly_results
    return node_ids


def _recorded_detail_edge_catalog(graph: OperationGraph, result_node_ids: Sequence[str]) -> Dict[str, Any]:
    """Keep recorded seed signatures for GSM and persistent native references.

    A recorded edge_index is only a source identifier in the saved reference
    map. Runtime selection always resolves the accompanying geometry signature;
    the identifier is never used to index SolidWorks edges.
    """
    active = _result_dependency_node_ids(graph, result_node_ids)
    sources: Dict[str, Any] = {}
    for node in graph.nodes:
        if str(node.node_id) not in active or node.op not in {
            'make_fillet_rsolid', 'make_chamfer_rsolid'
        } or not node.inputs:
            continue
        source_id = str(node.inputs[0].node_id)
        seeds = []
        for selector_id in node.params.get('selected_edge_node_ids') or []:
            selection = graph.get_node(str(selector_id))
            selector = copy.deepcopy(selection.params.get('geo_selector') or {}) if selection else {}
            metadata = selector.pop('metadata_geo', None) or {}
            index = metadata.get('edge_index')
            if not selector or not isinstance(index, int) or isinstance(index, bool) or index < 0:
                seeds = []
                break
            seeds.append({'canonical_index': index, 'selector': selector})
        if not seeds:
            continue
        entry = sources.setdefault(source_id, {'edges': [], 'targets': {}})
        existing = {item['canonical_index'] for item in entry['edges']}
        for seed in seeds:
            if seed['canonical_index'] not in existing:
                entry['edges'].append(seed)
                existing.add(seed['canonical_index'])
        entry['targets'][str(node.node_id)] = {
            'selected_indices': [seed['canonical_index'] for seed in seeds],
        }
    return {'schema': 'simplecad-sw-canonical-topology-v1', 'method': 'gsm', 'sources': sources}

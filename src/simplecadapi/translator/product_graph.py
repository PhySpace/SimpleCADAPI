"""Internal dependency-first graph view for product-package translators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simplecadapi._cpp import OperationGraph
from .package_units import ProductPackageInput, read_product_package_translation_units


_NODE_ID_KEYS = {
    "node_id",
    "source_node_id",
    "target_node_id",
    "topology_source_node_id",
    "topology_target_node_id",
}
_NODE_IDS_KEYS = {
    "node_ids",
    "selected_edge_node_ids",
    "selected_face_node_ids",
    "source_node_ids",
    "target_node_ids",
}


@dataclass(frozen=True, slots=True)
class ProductGraphView:
    """One translator-internal graph spanning a validated package closure."""

    graph: OperationGraph
    root_result_node_id: str
    definition_result_node_ids: dict[str, str]
    definition_ids: tuple[str, ...]
    root_definition_id: str
    root_definition_kind: str

    def model_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "2.0",
            "graph": self.graph,
            "leaf_ids": [self.root_result_node_id],
        }


def _safe_token(value: str) -> str:
    token = "".join(character if character.isalnum() else "_" for character in value)
    return token.strip("_") or "definition"


def _remap_node_ids(value: Any, mapping: dict[str, str], key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            str(child_key): _remap_node_ids(child, mapping, str(child_key))
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        if key in _NODE_IDS_KEYS:
            return [mapping.get(str(child), str(child)) for child in value]
        return [_remap_node_ids(child, mapping) for child in value]
    if isinstance(value, tuple):
        if key in _NODE_IDS_KEYS:
            return tuple(mapping.get(str(child), str(child)) for child in value)
        return tuple(_remap_node_ids(child, mapping) for child in value)
    if key in _NODE_ID_KEYS and value is not None:
        return mapping.get(str(value), str(value))
    return value


def build_product_graph_view(data: ProductPackageInput) -> ProductGraphView:
    """Build a namespaced in-memory graph from one validated `.scadpkg` closure.

    This is a translator implementation detail, not a serialized interchange
    format. External-definition reference nodes are resolved to the already
    translated dependency result node they name.
    """

    package, units = read_product_package_translation_units(data)
    if not units:
        raise ValueError("Product package contains no definition units")

    graph = OperationGraph(
        graph_id=f"product_{_safe_token(package.root_definition.definition_id)}"
    )
    definition_results: dict[str, str] = {}

    for unit_index, unit in enumerate(units):
        prefix = f"d{unit_index:04d}_{_safe_token(unit.definition_id)}"
        local_mapping: dict[str, str] = {}
        for node in unit.graph.topological_order():
            if node.op == "reference_definition":
                definition_id = str(node.params.get("definition_id") or "")
                result_node_id = definition_results.get(definition_id)
                if result_node_id is None:
                    raise ValueError(
                        f"Definition {unit.definition_id!r} references unresolved "
                        f"dependency {definition_id!r}"
                    )
                local_mapping[node.node_id] = result_node_id
                continue
            local_mapping[node.node_id] = f"{prefix}_{node.node_id}"

        for node in unit.graph.topological_order():
            if node.op == "reference_definition":
                continue
            input_nodes = []
            for source in node.inputs:
                source_id = local_mapping.get(source.node_id)
                if source_id is None:
                    raise ValueError(
                        f"Definition {unit.definition_id!r} has unmapped input "
                        f"{source.node_id!r}"
                    )
                source_node = graph.get_node(source_id)
                if source_node is None:
                    raise ValueError(
                        f"Definition {unit.definition_id!r} input {source.node_id!r} "
                        "was not emitted dependency-first"
                    )
                input_nodes.append(source_node)
            graph.add_node(
                op=node.op,
                params=_remap_node_ids(node.params, local_mapping),
                param_exprs=_remap_node_ids(node.param_exprs, local_mapping),
                inputs=input_nodes,
                node_id=local_mapping[node.node_id],
                output_count=node.output_count,
                context=node.context,
                tags=set(node.tags),
                source=node.source,
            )

        result_node_id = local_mapping.get(unit.result_node_id)
        if result_node_id is None or graph.get_node(result_node_id) is None:
            raise ValueError(
                f"Definition {unit.definition_id!r} result node did not enter product graph"
            )
        definition_results[unit.definition_id] = result_node_id

    root = package.root_definition
    root_result = definition_results.get(root.definition_id)
    if root_result is None:
        raise ValueError("Product package root definition has no translated result")
    return ProductGraphView(
        graph=graph,
        root_result_node_id=root_result,
        definition_result_node_ids=dict(definition_results),
        definition_ids=tuple(unit.definition_id for unit in units),
        root_definition_id=root.definition_id,
        root_definition_kind=root.definition_kind,
    )


__all__ = ["ProductGraphView", "build_product_graph_view"]

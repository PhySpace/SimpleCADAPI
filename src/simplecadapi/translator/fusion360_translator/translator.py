"""Fusion 360 backend facade for product-package translation."""

from __future__ import annotations

from typing import Any, Dict, Sequence, Set

from ...errors import ErrorGuidance
from simplecadapi._cpp import OperationGraph
from ..base import BaseTranslator
from ..errors import TranslationRequestError
from ..package_units import ProductPackageInput
from ..product_graph import build_product_graph_view
from ..types import BackendCapabilities, SupportLevel, TranslationArtifact
from .capabilities import CAPABILITIES
from .compiler import Fusion360ScriptTranslator


def _dependency_node_ids(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> Set[str]:
    needed: Set[str] = set()
    pending = [str(node_id) for node_id in result_node_ids]
    while pending:
        node_id = pending.pop()
        if node_id in needed:
            continue
        node = graph.get_node(node_id)
        if node is None:
            raise ValueError(f"Result node {node_id!r} is not present in the graph")
        needed.add(node_id)
        pending.extend(input_ref.node_id for input_ref in node.inputs)
        for key in ("selected_edge_node_ids", "selected_face_node_ids"):
            pending.extend(str(value) for value in node.params.get(key, []) or [])
    return needed


class Fusion360Translator(BaseTranslator):
    """Translate validated `.scadpkg` products into Fusion 360 scripts."""

    def __init__(
        self,
        document_name: str = "SimpleCADProduct",
        *,
        selection_mode: str = "gsm",
        source_kernel_fallback: bool = False,
    ) -> None:
        self.document_name = str(document_name)
        self.selection_mode = str(selection_mode)
        self.source_kernel_fallback = bool(source_kernel_fallback)

    @property
    def capabilities(self) -> BackendCapabilities:
        return CAPABILITIES

    def _preflight(
        self,
        payload: Dict[str, Any],
        graph: OperationGraph,
        result_node_id: str,
    ) -> None:
        needed = _dependency_node_ids(graph, [result_node_id])
        unsupported = sorted(
            {
                node.op
                for node_id in needed
                for node in [graph.get_node(node_id)]
                if node is not None
                and (
                    node.op not in CAPABILITIES.operations
                    or CAPABILITIES.operations[node.op].level
                    is SupportLevel.UNSUPPORTED
                )
            }
        )
        if unsupported:
            joined = ", ".join(unsupported)
            raise TranslationRequestError(
                "fusion360",
                "translate_product_package",
                ErrorGuidance(
                    what_happened=(
                        "The product package uses unsupported Fusion 360 "
                        f"operations: {joined}."
                    ),
                    possible_causes=(
                        "A definition-owned Feature Graph uses operations not "
                        "implemented by the Fusion 360 runtime.",
                    ),
                    how_to_fix=(
                        "Use operations declared by fusion360_translator.CAPABILITIES.",
                        "Use another translator backend for this product.",
                    ),
                ),
            )

    def translate_product_package(
        self,
        data: ProductPackageInput,
        **_options: Any,
    ) -> TranslationArtifact:
        view = build_product_graph_view(data)
        payload = view.model_payload()
        self._preflight(payload, view.graph, view.root_result_node_id)
        script = Fusion360ScriptTranslator(
            document_name=self.document_name,
            result_node_ids=[view.root_result_node_id],
            selection_mode=self.selection_mode,
            source_kernel_fallback=self.source_kernel_fallback,
        ).translate_model_payload_to_script(payload, graph=view.graph)
        return TranslationArtifact(
            backend_id="fusion360",
            target_id="fusion360_script",
            media_type="text/x-python",
            suggested_suffix=".py",
            content=script,
            metadata={
                "document_name": self.document_name,
                "root_definition_id": view.root_definition_id,
                "root_definition_kind": view.root_definition_kind,
                "definition_ids": view.definition_ids,
                "selection_mode": self.selection_mode,
                "source_kernel_fallback": self.source_kernel_fallback,
                "target_runtime_validated": False,
            },
        )


__all__ = ["Fusion360Translator"]

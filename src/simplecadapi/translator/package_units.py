"""Validated product-package translation units shared by CAD backends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..artifacts.assembly_definition import AssemblyDefinition
from ..artifacts.feature_graph import FeatureGraphArtifact, load_feature_graph_artifact
from ..artifacts.part_definition import PartDefinition
from ..product.packages import (
    ProductPackage,
    read_product_package,
    validate_product_package,
)
from simplecadapi._cpp import OperationGraph

Definition = PartDefinition | AssemblyDefinition
ProductPackageInput = ProductPackage | bytes | bytearray | memoryview | str | Path


@dataclass(frozen=True, slots=True)
class ProductPackageTranslationUnit:
    """One definition-owned graph in dependency-first translation order."""

    definition: Definition
    feature_graph: FeatureGraphArtifact
    graph: OperationGraph

    @property
    def definition_kind(self) -> str:
        return self.definition.definition_kind

    @property
    def definition_id(self) -> str:
        return self.definition.definition_id

    @property
    def revision(self) -> str:
        return self.definition.revision

    @property
    def content_hash(self) -> str:
        return self.definition.content_hash

    @property
    def result_node_id(self) -> str:
        return self.feature_graph.result_node_ids[0]

    def model_payload(self) -> dict[str, Any]:
        semantic_index = dict(self.feature_graph.semantic_index)
        return {
            "graph": self.graph,
            "leaf_ids": list(self.feature_graph.result_node_ids),
            "expression_graph": dict(self.feature_graph.expression_graph),
            "tolerance_graph": dict(self.feature_graph.tolerance_graph),
            "frame_graph": dict(self.feature_graph.frame_graph),
            "geometry_registry": list(semantic_index.get("geometry_registry", [])),
            "semantic_entity_registry": list(
                semantic_index.get("semantic_entity_registry", [])
            ),
            "sketch_profile_registry": list(
                semantic_index.get("sketch_profile_registry", [])
            ),
            "semantic_delta_log": list(semantic_index.get("semantic_delta_log", [])),
            "topology_delta_log": list(semantic_index.get("topology_delta_log", [])),
            "semantic_bindings": list(semantic_index.get("semantic_bindings", [])),
        }


def read_product_package_translation_units(
    data: ProductPackageInput,
) -> tuple[ProductPackage, tuple[ProductPackageTranslationUnit, ...]]:
    """Return a validated package and dependency-first definition units."""

    if isinstance(data, ProductPackage):
        validate_product_package(data)
        package = data
    else:
        package = read_product_package(data)
    ordered: list[Definition] = []
    visited: set[tuple[str, str]] = set()

    def visit(definition: Definition) -> None:
        # Deduplicate by definition identity, not content hash: consumers
        # (STEP label index, product-graph reference resolution, FreeCAD
        # tokens) all look units up by definition_id, and a package may
        # legitimately contain two same-content definitions with different
        # ids.
        key = (definition.definition_kind, definition.definition_id)
        if key in visited:
            return
        if isinstance(definition, AssemblyDefinition):
            for ref in definition.definition_refs:
                child = definition.resolved_definitions.get(ref.definition_id)
                if not isinstance(child, (PartDefinition, AssemblyDefinition)):
                    raise ValueError(
                        f"assembly {definition.definition_id!r} has unresolved definition "
                        f"{ref.definition_id!r}"
                    )
                visit(child)
        visited.add(key)
        ordered.append(definition)

    visit(package.root_definition)
    units: list[ProductPackageTranslationUnit] = []
    for definition in ordered:
        feature_graph = load_feature_graph_artifact(
            definition.blobs[definition.feature_graph_ref.path]
        )
        units.append(
            ProductPackageTranslationUnit(
                definition=definition,
                feature_graph=feature_graph,
                graph=OperationGraph.from_dict(dict(feature_graph.graph)),
            )
        )
    return package, tuple(units)


__all__ = [
    "ProductPackageInput",
    "ProductPackageTranslationUnit",
    "read_product_package_translation_units",
]

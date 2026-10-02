"""Typed results of ``@part`` and ``@assemble`` builds."""

from __future__ import annotations

from dataclasses import dataclass

from ..artifacts.assembly_definition import AssemblyDefinition
from ..artifacts.assembly_io import attach_definition
from ..artifacts.feature_graph import FeatureGraphArtifact
from ..artifacts.part_definition import PartDefinition
from ..product.assembly import Assembly
from ..product.part import Part


@dataclass(frozen=True)
class PartBuildResult:
    """Runtime Part plus its durable definition and feature DAG."""

    value: Part
    definition: PartDefinition
    feature_graph: FeatureGraphArtifact

    def __post_init__(self) -> None:
        attach_definition(self.value, self.definition)

    @property
    def part(self) -> Part:
        return self.value

    def replay(self, *, strict: bool = True):
        return self.feature_graph.replay(strict=strict)


@dataclass(frozen=True)
class AssemblyBuildResult:
    """Runtime Assembly plus its durable definition and feature DAG."""

    value: Assembly
    definition: AssemblyDefinition
    feature_graph: FeatureGraphArtifact

    def __post_init__(self) -> None:
        attach_definition(self.value, self.definition)

    @property
    def assembly(self) -> Assembly:
        return self.value

    def replay(self, *, strict: bool = True) -> Assembly:
        rebuilt = self.feature_graph.replay(
            strict=strict,
            external_definitions=self.definition.resolved_definitions,
        )
        if len(rebuilt) != 1 or not isinstance(rebuilt[0], Assembly):
            raise TypeError("assembly feature graph did not replay exactly one Assembly")
        return rebuilt[0]


__all__ = ["AssemblyBuildResult", "PartBuildResult"]

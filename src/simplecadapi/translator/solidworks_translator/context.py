"""Per-translation compiler state for the SolidWorks backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from simplecadapi._cpp import OperationGraph
from .versions import normalize_solidworks_version


@dataclass
class SolidWorksCompileContext:
    """Mutable state owned by one SolidWorks script compilation."""

    document_name: str
    visible: bool = False
    solidworks_version: str = "2025"
    source_graph: Optional[OperationGraph] = None
    declared_result_node_id_list: List[str] = field(default_factory=list)
    result_node_ids: Set[str] = field(default_factory=set)
    result_node_id_list: List[str] = field(default_factory=list)
    result_state_node_ids: Dict[str, List[str]] = field(default_factory=dict)
    active_result_state: Optional[str] = None

    def __post_init__(self) -> None:
        self.solidworks_version = normalize_solidworks_version(self.solidworks_version)


__all__ = ["SolidWorksCompileContext"]

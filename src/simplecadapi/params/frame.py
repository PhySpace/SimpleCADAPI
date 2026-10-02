"""Explicit frame graph for the 2.0 rearchitecture path."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class FrameNode:
    frame_id: str
    origin: tuple[float, float, float]
    x_axis: tuple[float, float, float]
    y_axis: tuple[float, float, float]
    z_axis: tuple[float, float, float]
    parent_frame_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class FrameGraph:
    def __init__(self) -> None:
        self._nodes: Dict[str, FrameNode] = {}

    def ensure_frame(
        self,
        frame_id: str,
        *,
        origin: tuple[float, float, float],
        x_axis: tuple[float, float, float],
        y_axis: tuple[float, float, float],
        z_axis: tuple[float, float, float],
        parent_frame_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FrameNode:
        return self.add(
            FrameNode(
                frame_id=frame_id,
                origin=origin,
                x_axis=x_axis,
                y_axis=y_axis,
                z_axis=z_axis,
                parent_frame_id=parent_frame_id,
                metadata=dict(metadata or {}),
            )
        )

    def add(self, node: FrameNode) -> FrameNode:
        """Register *node*, replacing any frame with the same id."""

        self._nodes[node.frame_id] = node
        return node

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [
                {
                    "frame_id": node.frame_id,
                    "origin": node.origin,
                    "x_axis": node.x_axis,
                    "y_axis": node.y_axis,
                    "z_axis": node.z_axis,
                    "parent_frame_id": node.parent_frame_id,
                    "metadata": dict(node.metadata),
                }
                for node in self._nodes.values()
            ]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FrameGraph":
        graph = cls()
        for item in data.get("nodes", []):
            if not isinstance(item, dict):
                continue
            graph.ensure_frame(
                str(item["frame_id"]),
                origin=tuple(item.get("origin", (0.0, 0.0, 0.0))),
                x_axis=tuple(item.get("x_axis", (1.0, 0.0, 0.0))),
                y_axis=tuple(item.get("y_axis", (0.0, 1.0, 0.0))),
                z_axis=tuple(item.get("z_axis", (0.0, 0.0, 1.0))),
                parent_frame_id=item.get("parent_frame_id"),
                metadata=dict(item.get("metadata", {})),
            )
        return graph

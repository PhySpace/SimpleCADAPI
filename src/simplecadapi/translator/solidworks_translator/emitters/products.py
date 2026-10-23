"""SolidWorks operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List

from ....product.placement import placement_frame_mm
from simplecadapi._cpp import OperationNode
from ..codegen import _emit_node_lines


def evaluated_assembly_params(params):
    """Convert durable evaluation ticks for both payload and emitted calls."""
    # The older make_solve operation already carries millimetre frames.
    return {
        **params,
        "component_placements": [
            {**record, "placement": placement_frame_mm(record["placement"])}
            for record in params.get("component_placements", [])
        ],
    }


class ProductEmitterMixin:
    def _emit_products(self, node: OperationNode) -> List[str]:
        return _emit_node_lines(
            node,
            params=self._solidworks_params(node),
            inputs=self._node_inputs(node),
        )


__all__ = ["ProductEmitterMixin"]

"""SolidWorks operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List

from simplecadapi._cpp import OperationNode
from ..codegen import _emit_node_lines


class PrimitiveEmitterMixin:
    def _emit_primitives(self, node: OperationNode) -> List[str]:
        return _emit_node_lines(
            node,
            params=self._solidworks_params(node),
            inputs=self._node_inputs(node),
        )


__all__ = ["PrimitiveEmitterMixin"]

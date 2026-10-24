"""SolidWorks operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List

from simplecadapi._cpp import OperationNode
from ..codegen import _emit_node_lines


class BooleanEmitterMixin:
    def _emit_booleans(self, node: OperationNode) -> List[str]:
        return _emit_node_lines(
            node,
            params=self._solidworks_params(node),
            inputs=self._node_inputs(node),
        )


__all__ = ["BooleanEmitterMixin"]

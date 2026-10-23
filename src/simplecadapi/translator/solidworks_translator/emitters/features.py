"""SolidWorks operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List

from simplecadapi._cpp import OperationNode
from ..codegen import _emit_node_lines


class FeatureEmitterMixin:
    def _emit_features(self, node: OperationNode) -> List[str]:
        return _emit_node_lines(
            node,
            params=self._solidworks_params(node),
            inputs=self._node_inputs(node),
        )


__all__ = ["FeatureEmitterMixin"]

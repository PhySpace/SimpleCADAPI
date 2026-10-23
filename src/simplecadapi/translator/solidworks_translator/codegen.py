"""Literal/codegen helpers for the SolidWorks backend (compile-time)."""

from __future__ import annotations

import json
import pprint
from typing import Any

from simplecadapi._cpp import OperationNode


def _json_ascii(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _py_literal(value: Any) -> str:
    return pprint.pformat(value, compact=True, sort_dicts=True, width=120)


def _safe_var(value: Any) -> str:
    """Return a valid Python identifier for one graph node id."""

    name = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(value))
    if not name or name[0].isdigit():
        name = "node_" + name
    return name


def _emit_node_lines(
    node: OperationNode,
    *,
    params: Any,
    inputs: Any,
    indent: str = "        ",
) -> list:
    """Build the per-node automation lines emitted into the main() body."""

    from .semantic import operation_label

    var = _safe_var(node.node_id)
    params_var = f"{var}_params"
    inputs_var = f"{var}_inputs"
    return [
        f"{indent}# Step {node.node_id}: {str(node.op)}",
        f"{indent}{params_var} = {_py_literal(params)}",
        f"{indent}{inputs_var} = {_py_literal(list(inputs))}",
        f"{indent}{var} = runtime.emit_node({{'node_id': {_json_ascii(str(node.node_id))}, "
        f"'op': {_json_ascii(str(node.op))}, 'params': {params_var}, 'inputs': {inputs_var}, "
        f"'output_count': {int(node.output_count)}}})",
    ]


__all__ = ["_json_ascii", "_py_literal", "_safe_var", "_emit_node_lines"]

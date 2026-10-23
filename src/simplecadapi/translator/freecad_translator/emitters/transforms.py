"""FreeCAD operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List, Optional

from simplecadapi._cpp import OperationNode
from ..codegen import *


class TransformEmitterMixin:
    def _emit_transforms(
        self,
        node: OperationNode,
        *,
        var_name: str,
        object_name: str,
        tags_literal: str,
        context_literal: str,
        param_exprs_literal: str,
        semantic_delta_literal: str,
        topo_delta_literal: str,
    ) -> Optional[List[str]]:
        graph = self._source_graph
        if graph is None:
            return None

        rp = f"{var_name}_params"
        re = f"{var_name}_param_exprs"
        inputs = [inp.node_id for inp in node.inputs]

        def finish() -> List[str]:
            return [
                f"_attach_simplecad_metadata({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
                f"GRAPH_NODES[{_json_ascii(node.node_id)}] = {var_name}",
                f"GRAPH_METADATA[{_json_ascii(node.node_id)}] = {{'op': {_json_ascii(node.op)}, 'params': {rp}, 'inputs': {var_name}_inputs, 'context': {context_literal}, 'tags': {tags_literal}}}",
                f"GRAPH_OUTPUTS[{_json_ascii(node.node_id)}] = [{var_name}]",
            ]

        def finish_ir() -> List[str]:
            return [
                f"{var_name} = _register_ir_node({_json_ascii(object_name)}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]

        def finish_alias(source_node_id: str) -> List[str]:
            return [
                f"{var_name} = _register_graph_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(source_node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]

        if node.op == "make_translate_rshape" and len(inputs) == 1:
            vector = node.params.get("vector")
            if isinstance(vector, (list, tuple)) and len(vector) == 3:
                try:
                    if all(
                        abs(float(v)) <= 1e-12 for v in vector
                    ) and not _contains_expr_refs(dict(node.param_exprs)):
                        return finish_alias(inputs[0])
                except Exception:
                    pass
            if self._can_fold_transform_into_input(node):
                lines = [
                    f"{var_name} = GRAPH_NODES[{_json_ascii(inputs[0])}]",
                    f"_fold_object_placement({var_name}, App.Placement(_vec(_resolve_vec3_param({rp}, {re}, 'vector')), App.Rotation()))",
                ]
                lines.append(
                    f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
                )
                lines.append(
                    f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
                )
                return lines
            if self._should_materialize_transform_for_loft_section(node):
                lines = [
                    f"{var_name}_shape = _shape_from_graph_node({_json_ascii(inputs[0])}).copy()",
                    f"{var_name}_placement = App.Placement(_vec(_resolve_vec3_param({rp}, {re}, 'vector')), App.Rotation())",
                    f"{var_name}_shape.Placement = {var_name}_placement.multiply({var_name}_shape.Placement)",
                    f"{var_name} = _make_feature({_json_ascii(object_name)}, {var_name}_shape, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
                ]
                return lines
            lines = [
                f"{var_name} = doc.addObject('App::Link', {_json_ascii(object_name)})",
                f"{var_name}.LinkedObject = GRAPH_NODES[{_json_ascii(inputs[0])}]",
                f"{var_name}.LinkTransform = True",
                f"{var_name}.Placement = App.Placement(_vec(_resolve_vec3_param({rp}, {re}, 'vector')), App.Rotation())",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            lines.extend(finish())
            return lines
        if node.op == "make_rotate_rshape" and len(inputs) == 1:
            if self._can_fold_transform_into_input(node):
                lines = [
                    f"{var_name} = GRAPH_NODES[{_json_ascii(inputs[0])}]",
                    f"_fold_object_placement({var_name}, _placement_for_rotation(_resolve_vec3_param({rp}, {re}, 'origin') if 'origin' in {rp} else (0.0, 0.0, 0.0), _resolve_vec3_param({rp}, {re}, 'axis') if 'axis' in {rp} else (0.0, 0.0, 1.0), _resolve_param_value({rp}, {re}, 'angle')))",
                ]
                lines.append(
                    f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
                )
                lines.append(
                    f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
                )
                return lines
            if self._should_materialize_transform_for_loft_section(node):
                lines = [
                    f"{var_name}_shape = _shape_from_graph_node({_json_ascii(inputs[0])}).copy()",
                    f"{var_name}_placement = _placement_for_rotation(_resolve_vec3_param({rp}, {re}, 'origin') if 'origin' in {rp} else (0.0, 0.0, 0.0), _resolve_vec3_param({rp}, {re}, 'axis') if 'axis' in {rp} else (0.0, 0.0, 1.0), _resolve_param_value({rp}, {re}, 'angle'))",
                    f"{var_name}_shape.Placement = {var_name}_placement.multiply({var_name}_shape.Placement)",
                    f"{var_name} = _make_feature({_json_ascii(object_name)}, {var_name}_shape, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
                ]
                return lines
            lines = [
                f"{var_name} = doc.addObject('App::Link', {_json_ascii(object_name)})",
                f"{var_name}.LinkedObject = GRAPH_NODES[{_json_ascii(inputs[0])}]",
                f"{var_name}.LinkTransform = True",
                f"{var_name}.Placement = _placement_for_rotation(_resolve_vec3_param({rp}, {re}, 'origin') if 'origin' in {rp} else (0.0, 0.0, 0.0), _resolve_vec3_param({rp}, {re}, 'axis') if 'axis' in {rp} else (0.0, 0.0, 1.0), _resolve_param_value({rp}, {re}, 'angle'))",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            lines.extend(finish())
            return lines
        return None


__all__ = ["TransformEmitterMixin"]

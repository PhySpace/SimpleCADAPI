"""FreeCAD operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List, Optional

from simplecadapi._cpp import OperationNode
from ..codegen import *


class BooleanEmitterMixin:
    def _emit_booleans(
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

        if node.op == "make_cut_rsolid" and len(inputs) >= 2:
            if len(inputs) == 2:
                base_name = _safe_name(f"{object_name}_base", prefix="operand")
                tool_name = _safe_name(f"{object_name}_tool", prefix="operand")
                lines = [
                    "doc.recompute()",
                    f"{var_name} = doc.addObject('Part::Cut', {_json_ascii(object_name)})",
                    f"{var_name}.Base = _materialize_boolean_operand(GRAPH_NODES[{_json_ascii(inputs[0])}], {_json_ascii(base_name)})",
                    f"{var_name}.Tool = _materialize_boolean_operand(GRAPH_NODES[{_json_ascii(inputs[1])}], {_json_ascii(tool_name)})",
                ]
            else:
                lines = ["doc.recompute()"]
                base_name = _safe_name(f"{object_name}_base", prefix="operand")
                previous_expr = f"_materialize_boolean_operand(GRAPH_NODES[{_json_ascii(inputs[0])}], {_json_ascii(base_name)})"
                for index, tool_node_id in enumerate(inputs[1:], start=1):
                    is_last = index == len(inputs) - 1
                    step_var = var_name if is_last else f"{var_name}_step_{index}"
                    step_name = (
                        object_name
                        if is_last
                        else _safe_name(f"{object_name}_step_{index}", prefix="step")
                    )
                    tool_name = _safe_name(
                        f"{object_name}_tool_{index}", prefix="operand"
                    )
                    lines.extend(
                        [
                            f"{step_var} = doc.addObject('Part::Cut', {_json_ascii(step_name)})",
                            f"{step_var}.Base = {previous_expr}",
                            f"{step_var}.Tool = _materialize_boolean_operand(GRAPH_NODES[{_json_ascii(tool_node_id)}], {_json_ascii(tool_name)})",
                        ]
                    )
                    if not is_last:
                        lines.append(f"_set_visibility({step_var}, False)")
                        lines.append("doc.recompute()")
                    previous_expr = step_var
            lines.extend(finish())
            return lines
        if node.op == "make_union_rsolid" and len(inputs) >= 2:
            if len(inputs) == 2:
                base_name = _safe_name(f"{object_name}_base", prefix="operand")
                tool_name = _safe_name(f"{object_name}_tool", prefix="operand")
                lines = [
                    "doc.recompute()",
                    f"{var_name} = doc.addObject('Part::Fuse', {_json_ascii(object_name)})",
                    f"{var_name}.Base = _materialize_boolean_operand(GRAPH_NODES[{_json_ascii(inputs[0])}], {_json_ascii(base_name)})",
                    f"{var_name}.Tool = _materialize_boolean_operand(GRAPH_NODES[{_json_ascii(inputs[1])}], {_json_ascii(tool_name)})",
                ]
            else:
                lines = [
                    "doc.recompute()",
                    f"{var_name} = doc.addObject('Part::MultiFuse', {_json_ascii(object_name)})",
                    f"{var_name}.Shapes = [_materialize_boolean_operand(GRAPH_NODES[node_id], {_json_ascii(object_name)} + '_operand_' + str(index)) for index, node_id in enumerate({var_name}_inputs)]",
                ]
            lines.extend(finish())
            return lines
        if node.op == "make_intersect_rsolid" and len(inputs) >= 2:
            if len(inputs) == 2:
                base_name = _safe_name(f"{object_name}_base", prefix="operand")
                tool_name = _safe_name(f"{object_name}_tool", prefix="operand")
                lines = [
                    f"{var_name} = doc.addObject('Part::Common', {_json_ascii(object_name)})",
                    f"{var_name}.Base = _materialize_boolean_operand(GRAPH_NODES[{_json_ascii(inputs[0])}], {_json_ascii(base_name)})",
                    f"{var_name}.Tool = _materialize_boolean_operand(GRAPH_NODES[{_json_ascii(inputs[1])}], {_json_ascii(tool_name)})",
                ]
            else:
                lines = [
                    f"{var_name} = doc.addObject('Part::MultiCommon', {_json_ascii(object_name)})",
                    f"{var_name}.Shapes = [_materialize_boolean_operand(GRAPH_NODES[node_id], {_json_ascii(object_name)} + '_operand_' + str(index)) for index, node_id in enumerate({var_name}_inputs)]",
                ]
            lines.extend(finish())
            return lines
        if (
            node.op
            in {"make_2d_cut_rface", "make_2d_union_rface", "make_2d_intersect_rface"}
            and len(inputs) >= 2
        ):
            lines = [
                "doc.recompute()",
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _face_boolean_shape({_json_ascii(node.op)}, GRAPH_NODES[{_json_ascii(inputs[0])}], GRAPH_NODES[{_json_ascii(inputs[1])}]), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
            return lines
        if node.op == "make_fillet_rsolid" and len(inputs) >= 1:
            lines = [
                f"{var_name} = doc.addObject('Part::Fillet', {_json_ascii(object_name)})",
                f"{var_name}.Base = GRAPH_NODES[{_json_ascii(inputs[0])}]",
                f"{var_name}.Edges = [(int(idx) + 1, float(_resolve_param_value({rp}, {re}, 'radius')), float(_resolve_param_value({rp}, {re}, 'radius'))) for idx in _selected_indices_from_nodes({rp}.get('selected_edge_node_ids', []), {rp}.get('selected_edge_indices', []), _shape_from_graph_node({_json_ascii(inputs[0])}), 'edge')]",
            ]
            lines.append(f"_apply_detail_feature_bindings({var_name}, {re}, 'radius')")
            lines.extend(finish())
            return lines
        if node.op == "make_chamfer_rsolid" and len(inputs) >= 1:
            lines = [
                f"{var_name} = doc.addObject('Part::Chamfer', {_json_ascii(object_name)})",
                f"{var_name}.Base = GRAPH_NODES[{_json_ascii(inputs[0])}]",
                f"{var_name}.Edges = [(int(idx) + 1, float(_resolve_param_value({rp}, {re}, 'distance')), float(_resolve_param_value({rp}, {re}, 'distance2') if 'distance2' in {rp} else float(_resolve_param_value({rp}, {re}, 'distance')))) for idx in _selected_indices_from_nodes({rp}.get('selected_edge_node_ids', []), {rp}.get('selected_edge_indices', []), _shape_from_graph_node({_json_ascii(inputs[0])}), 'edge')]",
            ]
            lines.append(
                f"_apply_detail_feature_bindings({var_name}, {re}, 'distance')"
            )
            lines.extend(finish())
            return lines
        if node.op == "make_shell_rsolid" and len(inputs) >= 1:
            lines = [
                f"{var_name} = doc.addObject('Part::Thickness', {_json_ascii(object_name)})",
                f"{var_name}.Value = float(_resolve_param_value({rp}, {re}, 'thickness'))",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            if node.params.get("selected_face_indices") or node.params.get(
                "selected_face_node_ids"
            ):
                face_name_expr = f"['Face' + str(int(i) + 1) for i in _selected_indices_from_nodes({rp}.get('selected_face_node_ids', []), {rp}.get('selected_face_indices', []), _shape_from_graph_node({_json_ascii(inputs[0])}), 'face')]"
                lines.append(
                    f"{var_name}.Faces = (GRAPH_NODES[{_json_ascii(inputs[0])}], {face_name_expr})"
                )
            lines.extend(finish())
            return lines
        if node.op == "make_mirror_rshape" and len(inputs) == 1:
            lines = [
                f"{var_name} = doc.addObject('Part::Mirroring', {_json_ascii(object_name)})",
                f"{var_name}.Source = GRAPH_NODES[{_json_ascii(inputs[0])}]",
                f"{var_name}.Base = _vec(_resolve_vec3_param({rp}, {re}, 'plane_origin') if 'plane_origin' in {rp} else (0.0, 0.0, 0.0))",
                f"{var_name}.Normal = _vec(_resolve_vec3_param({rp}, {re}, 'plane_normal') if 'plane_normal' in {rp} else (0.0, 0.0, 1.0))",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            lines.extend(finish())
            return lines
        return None


__all__ = ["BooleanEmitterMixin"]

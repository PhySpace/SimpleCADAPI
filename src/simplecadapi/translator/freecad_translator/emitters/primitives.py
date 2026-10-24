"""FreeCAD operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List, Optional

from simplecadapi._cpp import OperationNode
from ..codegen import *


class PrimitiveEmitterMixin:
    def _emit_primitives(
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

        if node.op == "make_box_rsolid":
            lines = [
                f"{var_name}_width = float(_resolve_param_value({rp}, {re}, 'width'))",
                f"{var_name}_height = float(_resolve_param_value({rp}, {re}, 'height'))",
                f"{var_name}_depth = float(_resolve_param_value({rp}, {re}, 'depth'))",
                f"{var_name}_bottom = _vec(_resolve_vec3_param({rp}, {re}, 'bottom_face_center'))",
                f"{var_name}_corner = {var_name}_bottom - App.Vector({var_name}_width / 2.0, {var_name}_height / 2.0, 0.0)",
                f"{var_name} = doc.addObject('Part::Box', {_json_ascii(object_name)})",
                f"{var_name}.Length = {var_name}_width",
                f"{var_name}.Width = {var_name}_height",
                f"{var_name}.Height = {var_name}_depth",
                f"{var_name}.Placement = App.Placement({var_name}_corner, App.Rotation())",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            lines.extend(finish())
            return lines
        if node.op == "make_cylinder_rsolid":
            lines = [
                f"{var_name} = doc.addObject('Part::Cylinder', {_json_ascii(object_name)})",
                f"{var_name}.Radius = float(_resolve_param_value({rp}, {re}, 'radius'))",
                f"{var_name}.Height = float(_resolve_param_value({rp}, {re}, 'height'))",
                f"{var_name}.Placement = App.Placement(_vec(_resolve_vec3_param({rp}, {re}, 'bottom_face_center')), App.Rotation(App.Vector(0.0, 0.0, 1.0), _vec(_resolve_vec3_param({rp}, {re}, 'axis'))))",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            lines.extend(finish())
            return lines
        if node.op == "make_cone_rsolid":
            lines = [
                f"{var_name} = doc.addObject('Part::Cone', {_json_ascii(object_name)})",
                f"{var_name}.Radius1 = float(_resolve_param_value({rp}, {re}, 'bottom_radius'))",
                f"{var_name}.Radius2 = float(_resolve_param_value({rp}, {re}, 'top_radius'))",
                f"{var_name}.Height = float(_resolve_param_value({rp}, {re}, 'height'))",
                f"{var_name}.Placement = App.Placement(_vec(_resolve_vec3_param({rp}, {re}, 'bottom_face_center')), App.Rotation(App.Vector(0.0, 0.0, 1.0), _vec(_resolve_vec3_param({rp}, {re}, 'axis'))))",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            lines.extend(finish())
            return lines
        if node.op == "make_sphere_rsolid":
            lines = [
                f"{var_name} = doc.addObject('Part::Sphere', {_json_ascii(object_name)})",
                f"{var_name}.Radius = float(_resolve_param_value({rp}, {re}, 'radius'))",
                f"{var_name}.Placement = App.Placement(_vec(_resolve_vec3_param({rp}, {re}, 'center')), App.Rotation())",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            lines.extend(finish())
            return lines
        return None


__all__ = ["PrimitiveEmitterMixin"]

"""FreeCAD operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List, Optional

from simplecadapi._cpp import OperationNode
from ..codegen import *
from ..analysis import unwrap_transparent_geometry_node


_TWISTED_SWEEP_EMULATION_LIMITATION = (
    "FreeCAD has no auxiliary-spine twisted-sweep feature. This object is a "
    "smooth solid loft through rotated and translated profile sections; it "
    "approximates the continuous SimpleCAD sweep, and expressions are evaluated "
    "when the generated script runs rather than remaining dynamically bound."
)


class FeatureEmitterMixin:
    def _emit_features(
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

        if node.op == "make_extrude_rsolid" and len(inputs) == 1:
            direct_base_node = graph.get_node(inputs[0])
            base_node = unwrap_transparent_geometry_node(graph, direct_base_node)
            profile_node = base_node
            if (
                profile_node is not None
                and profile_node.op == "make_face_from_wire_rface"
                and profile_node.inputs
            ):
                profile_node = graph.get_node(profile_node.inputs[0].node_id)
            circle_node = None
            if (
                profile_node is not None
                and profile_node.op == "make_wire_from_edges_rwire"
                and len(profile_node.inputs) == 1
            ):
                edge_node = graph.get_node(profile_node.inputs[0].node_id)
                if edge_node is not None and edge_node.op == "make_circle_redge":
                    circle_node = edge_node
            if (
                direct_base_node is base_node
                and circle_node is not None
                and self._can_lower_circle_extrusion_to_cylinder(circle_node, node)
            ):
                circle_var = _safe_name(circle_node.node_id)
                lines = [
                    f"{var_name} = doc.addObject('Part::Cylinder', {_json_ascii(object_name)})",
                    f"{var_name}.Radius = float(_resolve_param_value({circle_var}_params, {circle_var}_param_exprs, 'radius'))",
                    f"{var_name}.Height = float(_resolve_param_value({rp}, {re}, 'distance'))",
                    f"{var_name}.Placement = App.Placement(_vec(_resolve_vec3_param({circle_var}_params, {circle_var}_param_exprs, 'center')), _periodic_axis_rotation(_resolve_vec3_param({rp}, {re}, 'direction'), {circle_var}_params.get('_kernel_x_axis'), {circle_var}_params.get('_kernel_y_axis')))",
                ]
                lines.extend(finish())
                return lines
            if base_node is not None and base_node.op in {
                "make_face_from_wire_rface",
                "make_face_from_wires_rface",
                "make_wire_from_edges_rwire",
                "make_face_from_sketch_rface",
                "make_wire_from_sketch_rwire",
                "make_2d_cut_rface",
                "make_2d_union_rface",
                "make_2d_intersect_rface",
                "make_bezier_surface_rface",
            }:
                sketch_node = base_node
                if base_node.op == "make_face_from_wire_rface" and base_node.inputs:
                    sketch_node = unwrap_transparent_geometry_node(
                        graph, graph.get_node(base_node.inputs[0].node_id)
                    )
                sketch_node_id = (
                    sketch_node.node_id
                    if sketch_node is not None
                    else base_node.node_id
                )
                base_expr = f"GRAPH_NODES[{_json_ascii(sketch_node_id)}]"
                lines: List[str] = []
                lines.extend(
                    [
                        f"{var_name} = doc.addObject('Part::Extrusion', {_json_ascii(object_name)})",
                        f"{var_name}.Base = {base_expr}",
                        f"{var_name}.DirMode = 'Custom'",
                        f"{var_name}.Dir = _vec(_resolve_vec3_param({rp}, {re}, 'direction'))",
                        f"{var_name}.LengthFwd = float(_resolve_param_value({rp}, {re}, 'distance'))",
                        f"{var_name}.LengthRev = 0.0",
                        f"{var_name}.Solid = True",
                    ]
                )
                lines.append(
                    f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
                )
                lines.extend(finish())
                return lines
        if node.op == "make_revolve_rsolid" and len(inputs) == 1:
            direct_base_node = graph.get_node(inputs[0])
            base_node = unwrap_transparent_geometry_node(graph, direct_base_node)
            if base_node is not None and base_node.op in {
                "make_face_from_wire_rface",
                "make_wire_from_edges_rwire",
                "make_wire_from_sketch_rwire",
            }:
                source_expr = f"GRAPH_NODES[{_json_ascii(inputs[0])}]"
                lines: List[str] = []
                lines.extend(
                    [
                        f"{var_name} = doc.addObject('Part::Revolution', {_json_ascii(object_name)})",
                        f"{var_name}.Source = {source_expr}",
                        f"{var_name}.Axis = _vec(_resolve_vec3_param({rp}, {re}, 'axis') if 'axis' in {rp} else (0.0, 0.0, 1.0))",
                        f"{var_name}.Base = _vec(_resolve_vec3_param({rp}, {re}, 'origin') if 'origin' in {rp} else (0.0, 0.0, 0.0))",
                        f"{var_name}.Angle = float(_resolve_param_value({rp}, {re}, 'angle') if 'angle' in {rp} else 360.0)",
                        f"{var_name}.Solid = True",
                    ]
                )
                lines.append(
                    f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
                )
                lines.extend(finish())
                return lines
        if node.op == "make_loft_rsolid" and len(inputs) >= 2:
            lines = [
                f"{var_name} = doc.addObject('Part::Loft', {_json_ascii(object_name)})",
                f"{var_name}.Sections = [GRAPH_NODES[node_id] for node_id in {var_name}_inputs]",
                f"{var_name}.Solid = True",
                f"{var_name}.Ruled = bool(_resolve_param_value({rp}, {re}, 'ruled') if 'ruled' in {rp} else False)",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            lines.extend(finish())
            return lines
        if node.op == "make_sweep_rsolid" and len(inputs) == 2:
            lines = [
                f"{var_name} = doc.addObject('Part::Sweep', {_json_ascii(object_name)})",
                f"{var_name}.Sections = [GRAPH_NODES[{_json_ascii(inputs[0])}]]",
                f"{var_name}.Spine = _spine_object({_json_ascii(inputs[1])})",
                f"{var_name}.Solid = True",
                f"{var_name}.Frenet = bool(_resolve_param_value({rp}, {re}, 'is_frenet') if 'is_frenet' in {rp} else False)",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            lines.extend(finish())
            return lines
        if node.op == "make_twisted_sweep_rsolid" and len(inputs) == 1:
            lines = [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _twisted_sweep_loft_shape(GRAPH_NODES[{_json_ascii(inputs[0])}], axis=_resolve_vec3_param({rp}, {re}, 'axis'), origin=_resolve_vec3_param({rp}, {re}, 'origin'), distance=float(_resolve_param_value({rp}, {re}, 'distance')), twist_angle=float(_resolve_param_value({rp}, {re}, 'twist_angle'))), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
                f"_mark_emulated_translation({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, reason={_json_ascii(_TWISTED_SWEEP_EMULATION_LIMITATION)})",
            ]
            return lines
        return None


__all__ = ["FeatureEmitterMixin"]

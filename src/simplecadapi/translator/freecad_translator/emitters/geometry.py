"""FreeCAD operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List, Optional

from simplecadapi._cpp import OperationNode
from ..codegen import *


_DYNAMIC_CURVE_NORMAL_LIMITATION = (
    "FreeCAD Sketcher cannot bind a sketch placement orientation to this vector "
    "expression. The translated profile uses the expression's value when the "
    "script runs, but later spreadsheet edits do not reorient the sketch."
)


class GeometryEmitterMixin:
    def _emit_geometry(
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

        if node.node_id in self._suppressed_profile_node_ids:
            return finish_ir()
        if node.op == "make_line_redge":
            lines = [
                f"{var_name} = _register_graph_value(Part.makeLine(_vec(_resolve_vec3_param({rp}, {re}, 'start')), _vec(_resolve_vec3_param({rp}, {re}, 'end'))), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]
            return lines
        if node.op == "make_circle_redge":
            lines = [
                f"{var_name} = _register_graph_value(_kernel_circle_from_params({rp}, {re}).toShape(), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]
            return lines
        if node.op == "make_ellipse_redge":
            lines = [
                f"{var_name} = _register_graph_value(_kernel_ellipse_from_params({rp}, {re}).toShape(), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]
            return lines
        if node.op == "make_angle_arc_redge":
            lines = [
                f"{var_name} = _register_graph_value(Part.ArcOfCircle(_kernel_circle_from_params({rp}, {re}), float(_resolve_param_value({rp}, {re}, 'start_angle')), float(_resolve_param_value({rp}, {re}, 'end_angle'))).toShape(), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]
            return lines
        if node.op == "make_three_point_arc_redge":
            arc_expr = f"Part.Arc(_vec(_resolve_vec3_param({rp}, {re}, 'start')), _vec(_resolve_vec3_param({rp}, {re}, 'middle')), _vec(_resolve_vec3_param({rp}, {re}, 'end'))).toShape()"
            lines = [
                f"{var_name} = _register_graph_value({arc_expr}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]
            return lines
        if node.op in {"make_spline_redge", "make_interpolated_spline_redge"}:
            lines = [
                f"{var_name} = _register_graph_value(_bspline_curve_from_params({rp}, context={context_literal}).toShape(), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]
            return lines
        if node.op == "make_wire_from_edges_rwire":
            input_nodes = [graph.get_node(node_id) for node_id in inputs]
            if len(inputs) == 1:
                single = input_nodes[0]
                if single is not None and single.op == "make_helix_redge":
                    return finish_alias(inputs[0])
            if input_nodes and all(
                inp is not None
                and inp.op
                in {
                    "make_line_redge",
                    "make_circle_redge",
                    "make_angle_arc_redge",
                    "make_three_point_arc_redge",
                    "make_spline_redge",
                    "make_interpolated_spline_redge",
                }
                for inp in input_nodes
            ):
                if not any(
                    _contains_expr_refs(dict(inp.param_exprs))
                    for inp in input_nodes
                    if inp is not None
                ):
                    return [
                        f"{var_name} = _make_feature({_json_ascii(object_name)}, _wire_shape_from_edge_objects({var_name}_inputs), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
                    ]
                lines = [
                    f"{var_name} = doc.addObject('Sketcher::SketchObject', {_json_ascii(object_name)})",
                    f"{var_name}_sketch_bindings = []",
                    f"{var_name}_expr_limitations = []",
                    f"{var_name}_constraint_bindings = []",
                ]
                point_exprs: List[str] = []
                for geom_index, input_node in enumerate(input_nodes):
                    assert input_node is not None
                    edge_var = _safe_name(input_node.node_id)
                    edge_obj_expr = f"GRAPH_NODES[{_json_ascii(input_node.node_id)}]"
                    if input_node.op == "make_line_redge":
                        point_exprs.append(f"_edge_start_point({edge_obj_expr})")
                        point_exprs.append(f"_edge_end_point({edge_obj_expr})")
                    elif input_node.op == "make_three_point_arc_redge":
                        point_exprs.append(f"_edge_start_point({edge_obj_expr})")
                        point_exprs.append(
                            f"_resolve_vec3_param({edge_var}_params, {edge_var}_param_exprs, 'middle')"
                        )
                        point_exprs.append(f"_edge_end_point({edge_obj_expr})")
                    elif input_node.op == "make_circle_redge":
                        point_exprs.append(
                            f"_resolve_vec3_param({edge_var}_params, {edge_var}_param_exprs, 'center')"
                        )
                    elif input_node.op == "make_angle_arc_redge":
                        point_exprs.append(f"_edge_start_point({edge_obj_expr})")
                        point_exprs.append(f"_edge_mid_point({edge_obj_expr})")
                        point_exprs.append(f"_edge_end_point({edge_obj_expr})")
                    elif input_node.op in {
                        "make_spline_redge",
                        "make_interpolated_spline_redge",
                    }:
                        point_exprs.append(f"_edge_start_point({edge_obj_expr})")
                        point_exprs.append(f"_edge_mid_point({edge_obj_expr})")
                        point_exprs.append(f"_edge_end_point({edge_obj_expr})")
                    limitation_payload = _node_expression_limitation(input_node)
                    if input_node.op in {
                        "make_circle_redge",
                        "make_angle_arc_redge",
                    } and _contains_expr_refs(input_node.param_exprs.get("normal")):
                        limitation_payload = {
                            "op": input_node.op,
                            "reason": _DYNAMIC_CURVE_NORMAL_LIMITATION,
                        }
                    if limitation_payload is not None:
                        lines.append(
                            f"{var_name}_expr_limitations.append({_py_literal(limitation_payload)})"
                        )
                if (
                    len(input_nodes) == 1
                    and input_nodes[0] is not None
                    and input_nodes[0].op == "make_line_redge"
                ):
                    edge_var = _safe_name(input_nodes[0].node_id)
                    lines.append(
                        f"{var_name}_placement, {var_name}_length = _line_sketch_placement(_resolve_vec3_param({edge_var}_params, {edge_var}_param_exprs, 'start'), _resolve_vec3_param({edge_var}_params, {edge_var}_param_exprs, 'end'))"
                    )
                    lines.append(f"{var_name}.Placement = {var_name}_placement")
                else:
                    frame_points = "[" + ", ".join(point_exprs) + "]"
                    preferred_normal_expr = "None"
                    if all(
                        input_node is not None and input_node.op == "make_circle_redge"
                        for input_node in input_nodes
                    ):
                        circle_var = _safe_name(input_nodes[0].node_id)
                        preferred_normal_expr = (
                            f"_resolve_vec3_param({circle_var}_params, "
                            f"{circle_var}_param_exprs, 'normal') "
                            f"if 'normal' in {circle_var}_params else (0.0, 0.0, 1.0)"
                        )
                    lines.append(
                        f"{var_name}_placement, {var_name}_origin, {var_name}_xaxis, {var_name}_yaxis = _frame_from_points({frame_points}, {context_literal}, {preferred_normal_expr})"
                    )
                    lines.append(f"{var_name}.Placement = {var_name}_placement")
                for geom_index, input_node in enumerate(input_nodes):
                    assert input_node is not None
                    edge_var = _safe_name(input_node.node_id)
                    edge_obj_expr = f"GRAPH_NODES[{_json_ascii(input_node.node_id)}]"
                    if input_node.op == "make_line_redge":
                        if len(input_nodes) == 1:
                            lines.append(
                                f"{var_name}_placement, {var_name}_length = _line_sketch_placement(_resolve_vec3_param({edge_var}_params, {edge_var}_param_exprs, 'start'), _resolve_vec3_param({edge_var}_params, {edge_var}_param_exprs, 'end'))"
                            )
                            lines.append(f"{var_name}.Placement = {var_name}_placement")
                            lines.append(
                                f"{var_name}.addGeometry(Part.LineSegment(App.Vector(0.0, 0.0, 0.0), App.Vector({var_name}_length, 0.0, 0.0)), False)"
                            )
                            lines.append(
                                f"{var_name}_length_constraint_{geom_index} = {var_name}.addConstraint(Sketcher.Constraint('Distance', {geom_index}, float({var_name}_length)))"
                            )
                            lines.append(
                                f"{var_name}_dx_constraint_{geom_index} = {var_name}.addConstraint(Sketcher.Constraint('DistanceX', {geom_index}, 1, {geom_index}, 2, float(_resolve_nested_param_value({edge_var}_params, {edge_var}_param_exprs, 'end', 0)) - float(_resolve_nested_param_value({edge_var}_params, {edge_var}_param_exprs, 'start', 0))))"
                            )
                            lines.append(
                                f"{var_name}_dy_constraint_{geom_index} = {var_name}.addConstraint(Sketcher.Constraint('DistanceY', {geom_index}, 1, {geom_index}, 2, float(_resolve_nested_param_value({edge_var}_params, {edge_var}_param_exprs, 'end', 1)) - float(_resolve_nested_param_value({edge_var}_params, {edge_var}_param_exprs, 'start', 1))))"
                            )
                            lines.append(
                                f"{var_name}_sketch_bindings.append(('Placement.Base.x', _nested_expr_ref({edge_var}_param_exprs, 'start', 0)))"
                            )
                            lines.append(
                                f"{var_name}_sketch_bindings.append(('Placement.Base.y', _nested_expr_ref({edge_var}_param_exprs, 'start', 1)))"
                            )
                            lines.append(
                                f"{var_name}_sketch_bindings.append(('Placement.Base.z', _nested_expr_ref({edge_var}_param_exprs, 'start', 2)))"
                            )
                            lines.append(
                                f"{var_name}_length_formula = _line_length_formula({edge_var}_params, {edge_var}_param_exprs)"
                            )
                            lines.append(
                                f"{var_name}.setExpression('Geometry[{geom_index}].EndPoint.x', {var_name}_length_formula) if {var_name}_length_formula else None"
                            )
                            lines.append(
                                f"{var_name}_constraint_bindings.append((f'Constraints[{{{var_name}_length_constraint_{geom_index}}}]', {var_name}_length_formula))"
                            )
                            lines.append(
                                f"{var_name}_constraint_bindings.append((f'Constraints[{{{var_name}_dx_constraint_{geom_index}}}]', {_json_ascii(self._line_delta_formula(dict(input_node.param_exprs), 0)) if self._line_delta_formula(dict(input_node.param_exprs), 0) is not None else 'None'}))"
                            )
                            lines.append(
                                f"{var_name}_constraint_bindings.append((f'Constraints[{{{var_name}_dy_constraint_{geom_index}}}]', {_json_ascii(self._line_delta_formula(dict(input_node.param_exprs), 1)) if self._line_delta_formula(dict(input_node.param_exprs), 1) is not None else 'None'}))"
                            )
                        else:
                            lines.append(
                                f"{var_name}.addGeometry(_local_line_from_edge({edge_obj_expr}, {var_name}_origin, {var_name}_xaxis, {var_name}_yaxis), False)"
                            )
                            lines.append(
                                f"{var_name}_length_formula_{geom_index} = _line_length_formula({edge_var}_params, {edge_var}_param_exprs)"
                            )
                            lines.append(
                                f"{var_name}_length_value_{geom_index} = _resolve_param_value({edge_var}_params, {edge_var}_param_exprs, 'length') if 'length' in {edge_var}_params else {var_name}.Geometry[{geom_index}].length()"
                            )
                            lines.append(
                                f"{var_name}_length_constraint_{geom_index} = {var_name}.addConstraint(Sketcher.Constraint('Distance', {geom_index}, float({var_name}_length_value_{geom_index})))"
                            )
                            lines.append(
                                f"{var_name}_sketch_bindings.extend(_build_local_line_sketch_bindings({edge_var}_params, {edge_var}_param_exprs, geom_index={geom_index}, origin={var_name}_origin, x_axis={var_name}_xaxis, y_axis={var_name}_yaxis))"
                            )
                            lines.append(
                                f"{var_name}_constraint_bindings.append((f'Constraints[{{{var_name}_length_constraint_{geom_index}}}]', {var_name}_length_formula_{geom_index}))"
                            )
                    elif input_node.op == "make_circle_redge":
                        lines.append(
                            f"{var_name}.addGeometry(Part.Circle(_local_point_on_frame(_resolve_vec3_param({edge_var}_params, {edge_var}_param_exprs, 'center'), {var_name}_origin, {var_name}_xaxis, {var_name}_yaxis), App.Vector(0.0, 0.0, 1.0), float(_resolve_param_value({edge_var}_params, {edge_var}_param_exprs, 'radius'))), False)"
                        )
                        lines.append(
                            f"{var_name}_diameter_constraint_{geom_index} = {var_name}.addConstraint(Sketcher.Constraint('Diameter', {geom_index}, 2.0 * float(_resolve_param_value({edge_var}_params, {edge_var}_param_exprs, 'radius'))))"
                        )
                        if len(input_nodes) == 1:
                            lines.append(
                                f"{var_name}_sketch_bindings.append(('Placement.Base.x', _nested_expr_ref({edge_var}_param_exprs, 'center', 0)))"
                            )
                            lines.append(
                                f"{var_name}_sketch_bindings.append(('Placement.Base.y', _nested_expr_ref({edge_var}_param_exprs, 'center', 1)))"
                            )
                            lines.append(
                                f"{var_name}_sketch_bindings.append(('Placement.Base.z', _nested_expr_ref({edge_var}_param_exprs, 'center', 2)))"
                            )
                            lines.append(
                                f"{var_name}_radius_expr_{geom_index} = _expr_formula_from_ref(_nested_expr_ref({edge_var}_param_exprs, 'radius'))"
                            )
                            lines.append(
                                f"{var_name}_constraint_bindings.append((f'Constraints[{{{var_name}_diameter_constraint_{geom_index}}}]', f'2 * ({{{var_name}_radius_expr_{geom_index}}})' if {var_name}_radius_expr_{geom_index} else None))"
                            )
                        else:
                            lines.append(
                                f"{var_name}_sketch_bindings.extend(_build_local_circle_sketch_bindings({edge_var}_params, {edge_var}_param_exprs, geom_index={geom_index}, origin={var_name}_origin, x_axis={var_name}_xaxis, y_axis={var_name}_yaxis))"
                            )
                            lines.append(
                                f"{var_name}_radius_expr_{geom_index} = _expr_formula_from_ref(_nested_expr_ref({edge_var}_param_exprs, 'radius'))"
                            )
                            lines.append(
                                f"{var_name}_constraint_bindings.append((f'Constraints[{{{var_name}_diameter_constraint_{geom_index}}}]', f'2 * ({{{var_name}_radius_expr_{geom_index}}})' if {var_name}_radius_expr_{geom_index} else None))"
                            )
                    elif input_node.op == "make_angle_arc_redge":
                        arc_span_formula = self._angle_arc_span_formula(
                            dict(input_node.param_exprs)
                        )
                        arc_radius_formula = self._compile_time_expr_formula(
                            _compile_time_nested_expr_ref(
                                dict(input_node.param_exprs), "radius"
                            )
                        )
                        lines.append(
                            f"{var_name}.addGeometry(_local_arc_from_edge({edge_obj_expr}, {var_name}_origin, {var_name}_xaxis, {var_name}_yaxis), False)"
                        )
                        lines.append(
                            f"{var_name}_radius_constraint_{geom_index} = {var_name}.addConstraint(Sketcher.Constraint('Radius', {geom_index}, float(_resolve_param_value({edge_var}_params, {edge_var}_param_exprs, 'radius'))))"
                        )
                        lines.append(
                            f"{var_name}_angle_constraint_{geom_index} = {var_name}.addConstraint(Sketcher.Constraint('Angle', {geom_index}, float(_resolve_param_value({edge_var}_params, {edge_var}_param_exprs, 'end_angle')) - float(_resolve_param_value({edge_var}_params, {edge_var}_param_exprs, 'start_angle'))))"
                        )
                        lines.append(
                            f"{var_name}_sketch_bindings.extend(_build_local_angle_arc_sketch_bindings({edge_var}_params, {edge_var}_param_exprs, geom_index={geom_index}, origin={var_name}_origin, x_axis={var_name}_xaxis, y_axis={var_name}_yaxis))"
                        )
                        lines.append(
                            f"{var_name}_constraint_bindings.append((f'Constraints[{{{var_name}_radius_constraint_{geom_index}}}]', {_json_ascii(arc_radius_formula) if arc_radius_formula is not None else 'None'}))"
                        )
                        lines.append(
                            f"{var_name}_constraint_bindings.append((f'Constraints[{{{var_name}_angle_constraint_{geom_index}}}]', {_json_ascii(arc_span_formula) if arc_span_formula is not None else 'None'}))"
                        )
                    elif input_node.op in {
                        "make_spline_redge",
                        "make_interpolated_spline_redge",
                    }:
                        lines.append(
                            f"{var_name}.addGeometry(_bspline_curve_from_params({edge_var}_params, transform_point=lambda point: _local_point_on_frame(point, {var_name}_origin, {var_name}_xaxis, {var_name}_yaxis), context={_py_literal(input_node.context or {})}), False)"
                        )
                    elif input_node.op == "make_three_point_arc_redge":
                        lines.append(
                            f"{var_name}.addGeometry(_local_arc_from_edge({edge_obj_expr}, {var_name}_origin, {var_name}_xaxis, {var_name}_yaxis), False)"
                        )
                        lines.append(
                            f"{var_name}_sketch_bindings.extend(_build_local_three_point_arc_sketch_bindings({edge_var}_params, {edge_var}_param_exprs, geom_index={geom_index}, origin={var_name}_origin, x_axis={var_name}_xaxis, y_axis={var_name}_yaxis))"
                        )
                lines.append(
                    f"_apply_sketch_expression_bindings({var_name}, {var_name}_sketch_bindings)"
                )
                for pair in _coincident_constraint_pairs(input_nodes):
                    lines.append(
                        f"{var_name}.addConstraint(Sketcher.Constraint('Coincident', {pair[0]}, {pair[1]}, {pair[2]}, {pair[3]}))"
                    )
                lines.append(
                    f"[_bind_expression({var_name}, prop, expr) for prop, expr in {var_name}_constraint_bindings if expr]"
                )
                lines.extend(finish())
                lines.append(
                    f"{var_name}.SimpleCADExprSupport = 'limited' if {var_name}_expr_limitations else {var_name}.SimpleCADExprSupport"
                )
                lines.append(
                    f"{var_name}.SimpleCADExprLimitation = json.dumps({var_name}_expr_limitations, ensure_ascii=True, sort_keys=True) if {var_name}_expr_limitations else {var_name}.SimpleCADExprLimitation"
                )
                lines.append(f"if {var_name}_expr_limitations:")
                lines.append(
                    f"    GRAPH_LIMITATIONS[{_json_ascii(node.node_id)}] = {{'op': {_json_ascii(node.op)}, 'reason': json.dumps({var_name}_expr_limitations, ensure_ascii=True, sort_keys=True)}}"
                )
                return lines
            lines = [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _wire_shape_from_edge_objects({var_name}_inputs), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]
            return lines
        if node.op == "make_helix_redge":
            if str(node.params.get("handedness", "Right")) == "Left":
                # Part::Helix only builds right-handed curves; materialize
                # the mirrored winding through Part.makeHelix(lefthand=True).
                lines = [
                    f"{var_name} = _make_feature({_json_ascii(object_name)}, Part.makeHelix(float(_resolve_param_value({rp}, {re}, 'pitch')), float(_resolve_param_value({rp}, {re}, 'height')), float(_resolve_param_value({rp}, {re}, 'radius')), 0.0, True), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
                    f"{var_name}.Placement = App.Placement(_vec(_resolve_vec3_param({rp}, {re}, 'center') if 'center' in {rp} else (0.0, 0.0, 0.0)), App.Rotation(App.Vector(0.0, 0.0, 1.0), _vec(_resolve_vec3_param({rp}, {re}, 'dir') if 'dir' in {rp} else (0.0, 0.0, 1.0))))",
                ]
                lines.append(
                    f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
                )
                return lines
            lines = [
                f"{var_name} = _make_native_object('Part::Helix', {_json_ascii(object_name)}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
                f"{var_name}.Pitch = float(_resolve_param_value({rp}, {re}, 'pitch'))",
                f"{var_name}.Height = float(_resolve_param_value({rp}, {re}, 'height'))",
                f"{var_name}.Radius = float(_resolve_param_value({rp}, {re}, 'radius'))",
                f"{var_name}.Placement = App.Placement(_vec(_resolve_vec3_param({rp}, {re}, 'center') if 'center' in {rp} else (0.0, 0.0, 0.0)), App.Rotation(App.Vector(0.0, 0.0, 1.0), _vec(_resolve_vec3_param({rp}, {re}, 'dir') if 'dir' in {rp} else (0.0, 0.0, 1.0))))",
            ]
            lines.append(
                f"_apply_op_expression_bindings({var_name}, {_json_ascii(node.op)}, {re})"
            )
            return lines
        if node.op == "make_face_from_wire_rface":
            if inputs:
                return [
                    f"{var_name} = _make_feature({_json_ascii(object_name)}, _face_shape_from_wire_shape(GRAPH_NODES[{_json_ascii(inputs[0])}], {_json_ascii(node.op)}), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
                ]
            input_node = graph.get_node(inputs[0]) if inputs else None
            if input_node is not None and input_node.op == "make_wire_from_edges_rwire":
                edge_nodes = [graph.get_node(inp.node_id) for inp in input_node.inputs]
                if edge_nodes and all(
                    ed is not None and ed.op == "make_line_redge" for ed in edge_nodes
                ):
                    lines = [
                        f"{var_name} = doc.addObject('Sketcher::SketchObject', {_json_ascii(object_name)})"
                    ]
                    for edge_node in edge_nodes:
                        assert edge_node is not None
                        edge_var = _safe_name(edge_node.node_id)
                        lines.append(
                            f"{var_name}.addGeometry(Part.LineSegment(_vec(_resolve_vec3_param({edge_var}_params, {edge_var}_param_exprs, 'start')), _vec(_resolve_vec3_param({edge_var}_params, {edge_var}_param_exprs, 'end'))), False)"
                        )
                    lines.extend(finish())
                    return lines
                if edge_nodes and all(
                    ed is not None and ed.op == "make_circle_redge" for ed in edge_nodes
                ):
                    circle_node = edge_nodes[0]
                    assert circle_node is not None
                    circle_var = _safe_name(circle_node.node_id)
                    lines = [
                        f"{var_name} = doc.addObject('Sketcher::SketchObject', {_json_ascii(object_name)})",
                        f"{var_name}.addGeometry(Part.Circle(_vec(_resolve_vec3_param({circle_var}_params, {circle_var}_param_exprs, 'center')), _vec(_resolve_vec3_param({circle_var}_params, {circle_var}_param_exprs, 'normal') if 'normal' in {circle_var}_params else (0.0, 0.0, 1.0)), float(_resolve_param_value({circle_var}_params, {circle_var}_param_exprs, 'radius'))), False)",
                        f"_apply_sketch_expression_bindings({var_name}, _build_circle_sketch_bindings({circle_var}_param_exprs, geom_index=0, local=False))",
                    ]
                    lines.extend(finish())
                    return lines
                if edge_nodes and all(
                    ed is not None and ed.op == "make_angle_arc_redge"
                    for ed in edge_nodes
                ):
                    arc_node = edge_nodes[0]
                    assert arc_node is not None
                    lines = [
                        f"{var_name} = doc.addObject('Sketcher::SketchObject', {_json_ascii(object_name)})",
                        f"{var_name}.addGeometry(_arc_from_edge(GRAPH_NODES[{_json_ascii(arc_node.node_id)}]), False)",
                        f"_apply_sketch_expression_bindings({var_name}, _build_arc_sketch_bindings({_safe_name(arc_node.node_id)}_param_exprs, geom_index=0, prefer_local=False))",
                    ]
                    lines.extend(finish())
                    return lines
                if edge_nodes and all(
                    ed is not None and ed.op == "make_spline_redge" for ed in edge_nodes
                ):
                    spline_node = edge_nodes[0]
                    assert spline_node is not None
                    spline_var = _safe_name(spline_node.node_id)
                    lines = [
                        f"{var_name} = doc.addObject('Sketcher::SketchObject', {_json_ascii(object_name)})",
                        f"{var_name}.addGeometry(_bspline_curve_from_params({spline_var}_params), False)",
                    ]
                    lines.extend(finish())
                    return lines
                if edge_nodes and all(
                    ed is not None and ed.op == "make_three_point_arc_redge"
                    for ed in edge_nodes
                ):
                    arc_node = edge_nodes[0]
                    assert arc_node is not None
                    arc_var = _safe_name(arc_node.node_id)
                    lines = [
                        f"{var_name} = doc.addObject('Sketcher::SketchObject', {_json_ascii(object_name)})",
                        f"{var_name}.addGeometry(Part.ArcOfCircle(Part.Circle(Part.Arc(_vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'start')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'middle')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'end'))).toShape().Curve.Center, Part.Arc(_vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'start')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'middle')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'end'))).toShape().Curve.Axis, Part.Arc(_vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'start')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'middle')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'end'))).toShape().Curve.Radius), Part.Arc(_vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'start')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'middle')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'end'))).FirstParameter, Part.Arc(_vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'start')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'middle')), _vec(_resolve_vec3_param({arc_var}_params, {arc_var}_param_exprs, 'end'))).LastParameter), False)",
                    ]
                    lines.extend(finish())
                    return lines
        if node.op == "make_face_from_wires_rface" and len(inputs) >= 1:
            return [
                "doc.recompute()",
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _face_shape_from_wire_shapes(GRAPH_NODES[{_json_ascii(inputs[0])}], [GRAPH_NODES[node_id] for node_id in {var_name}_inputs[1:]], {_json_ascii(node.op)}), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        return None


__all__ = ["GeometryEmitterMixin"]

"""FreeCAD operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List, Optional

from simplecadapi._cpp import OperationNode
from ..codegen import *


class SketchEmitterMixin:
    def _emit_sketches(
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

        if node.op in {
            "make_sketch_rsketch",
            "add_point_rsketch",
            "add_line_rsketch",
            "add_circle_rsketch",
            "add_arc_rsketch",
            "add_bspline_rsketch",
            "add_ellipse_rsketch",
            "make_constrain_coincident_rsketch",
            "make_constrain_point_on_rsketch",
            "make_constrain_horizontal_rsketch",
            "make_constrain_vertical_rsketch",
            "make_constrain_points_horizontal_rsketch",
            "make_constrain_points_vertical_rsketch",
            "make_constrain_line_distance_rsketch",
            "make_constrain_normal_rsketch",
            "make_constrain_mirror_rsketch",
            "make_constrain_midpoint_points_rsketch",
            "make_constrain_major_radius_rsketch",
            "make_constrain_minor_radius_rsketch",
            "make_constrain_parallel_rsketch",
            "make_constrain_perpendicular_rsketch",
            "make_constrain_collinear_rsketch",
            "make_constrain_tangent_rsketch",
            "make_constrain_concentric_rsketch",
            "make_constrain_midpoint_rsketch",
            "make_constrain_symmetric_rsketch",
            "make_constrain_equal_length_rsketch",
            "make_constrain_equal_radius_rsketch",
            "make_constrain_distance_rsketch",
            "make_constrain_distance_x_rsketch",
            "make_constrain_distance_y_rsketch",
            "make_constrain_length_rsketch",
            "make_constrain_angle_rsketch",
            "make_constrain_radius_rsketch",
            "make_constrain_diameter_rsketch",
            "make_constrain_fix_rsketch",
        }:
            return finish_ir()
        if node.op in {"make_wire_from_sketch_rwire", "make_face_from_sketch_rface"}:
            return [
                f"{var_name} = _make_sketch_promotion_object({_json_ascii(object_name)}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})"
            ]
        return None


__all__ = ["SketchEmitterMixin"]

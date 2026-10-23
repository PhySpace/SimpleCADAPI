"""FreeCAD operation emitters for one canonical graph domain."""

from __future__ import annotations

from typing import List, Optional

from simplecadapi._cpp import OperationNode
from ..codegen import *


class ProductEmitterMixin:
    def _emit_products(
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

        if node.op == "reference_definition":
            return [
                f"{var_name}_definition_id = str({rp}.get('definition_id', ''))",
                f"{var_name}_record = DEFINITION_REGISTRY.get({var_name}_definition_id)",
                f"if not isinstance({var_name}_record, dict): raise RuntimeError('Missing translated definition ' + repr({var_name}_definition_id))",
                f"if str({var_name}_record.get('definition_kind')) != str({rp}.get('definition_kind')) or str({var_name}_record.get('revision')) != str({rp}.get('revision')) or str({var_name}_record.get('content_hash')) != str({rp}.get('content_hash')): raise RuntimeError('Translated definition identity differs for ' + repr({var_name}_definition_id))",
                f"{var_name} = {var_name}_record['product']",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = {var_name}",
                f"{var_name} = _register_graph_value({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if node.op == "evaluate_assembly_definition" and len(inputs) >= 1:
            return [
                f"{var_name}_assembly = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_assembly)",
                f"{var_name}_placements = {{str(item.get('instance_id')): item.get('placement') or {{}} for item in list({rp}.get('component_placements') or []) if isinstance(item, dict)}}",
                f"{var_name}_components = []",
                f"for _component in {var_name}_assembly.get('components', []):",
                f"    _component = dict(_component)",
                f"    _component_id = str(_component.get('component_id'))",
                f"    if _component_id in {var_name}_placements:",
                f"        _component['placement'] = {var_name}_placements[_component_id]",
                f"        _set_component_link_placement(_component['link'], _component.get('item') or {{}}, _component['placement'])",
                f"    {var_name}_components.append(_component)",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}]['components'] = {var_name}_components",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]

        if node.op == "make_material_rmaterial":
            return [
                f"{var_name} = dict({rp})",
                f"{var_name}_object = _ensure_material_object({var_name})",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = {{'kind': 'material', 'material': {var_name}, 'material_object': {var_name}_object}}",
                f"{var_name} = _register_graph_value({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if node.op in {
            "make_placement_rplacement",
            "make_identity_placement_rplacement",
        }:
            return [
                f"{var_name} = dict({rp})",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = {{'kind': 'placement', 'placement': {var_name}}}",
                f"{var_name} = _register_graph_value({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if node.op == "make_part_rpart" and len(inputs) == 1:
            lines = [
                f"{var_name} = doc.addObject('App::Part', {_json_ascii(object_name)})",
                f"{var_name}.Label = str({rp}.get('name') or {rp}.get('part_id') or {_json_ascii(object_name)})",
                f"{var_name}_source_body = GRAPH_NODES[{_json_ascii(inputs[0])}]",
                f"{var_name}_body = _adopt_part_feature_history({var_name}, {var_name}_source_body, {_json_ascii(inputs[0])})",
                f"_ensure_string_property({var_name}, 'SimpleCADPartId')",
                f"{var_name}.SimpleCADPartId = str({rp}.get('part_id', ''))",
                f"_hide_origin_tree({var_name})",
            ]
            lines.extend(finish())
            lines.append(
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = {{'kind': 'part', 'part_id': str({rp}.get('part_id', '')), 'body': {var_name}_body, 'container': {var_name}, 'material': None, 'connectors': []}}"
            )
            return lines
        if node.op == "make_assign_material_rpart" and len(inputs) >= 2:
            lines = [
                f"{var_name}_part = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"{var_name}_material = PRODUCT_VALUES[{_json_ascii(inputs[1])}]['material']",
                f"{var_name} = {var_name}_part['container']",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_part)",
                f"_apply_material_to_product(PRODUCT_VALUES[{_json_ascii(node.node_id)}], {var_name}_material)",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
            return lines
        if node.op == "make_assign_material_rpart" and len(inputs) == 1:
            lines = [
                f"{var_name}_part = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"{var_name}_material = _material_from_assignment_params({rp})",
                f"{var_name} = {var_name}_part['container']",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_part)",
                f"_apply_material_to_product(PRODUCT_VALUES[{_json_ascii(node.node_id)}], {var_name}_material)",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
            return lines
        if node.op == "make_assembly_rassembly":
            lines = [
                f"{var_name} = _make_native_assembly({_json_ascii(object_name)}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
                f"{var_name}.Label = str({rp}.get('name') or {rp}.get('assembly_id') or {_json_ascii(object_name)})",
                f"_ensure_string_property({var_name}, 'SimpleCADAssemblyId')",
                f"{var_name}.SimpleCADAssemblyId = str({rp}.get('assembly_id', ''))",
            ]
            lines.append(
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = {{'kind': 'assembly', 'assembly_id': str({rp}.get('assembly_id', '')), 'container': {var_name}, 'components': [], 'public_connectors': [], 'constraints': [], 'grounded_component_ids': []}}"
            )
            return lines
        if node.op == "make_add_component_rassembly" and len(inputs) >= 2:
            placement_expr = (
                f"PRODUCT_VALUES[{_json_ascii(inputs[2])}]['placement']"
                if len(inputs) >= 3
                else f"dict({rp}.get('placement') or {{}})"
            )
            lines = [
                f"{var_name}_assembly = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"{var_name}_item = PRODUCT_VALUES[{_json_ascii(inputs[1])}]",
                f"{var_name}_placement = {placement_expr}",
                f"{var_name} = {var_name}_assembly['container']",
                f"{var_name}_link_label = str({rp}.get('name') or {rp}.get('component_id') or {_json_ascii(object_name)})",
                f"{var_name}_link = _make_assembly_component_link({var_name}, {var_name}_item, {_json_ascii(object_name + '_component')}, {var_name}_link_label, {var_name}_placement)",
                f"_ensure_string_property({var_name}_link, 'SimpleCADComponentId')",
                f"{var_name}_link.SimpleCADComponentId = str({rp}.get('component_id', ''))",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_assembly)",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}]['components'] = list({var_name}_assembly.get('components', [])) + [{{'component_id': str({rp}.get('component_id', '')), 'link': {var_name}_link, 'placement': {var_name}_placement, 'item': {var_name}_item}}]",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
            return lines
        if node.op == "make_place_component_rassembly" and len(inputs) >= 1:
            placement_expr = (
                f"PRODUCT_VALUES[{_json_ascii(inputs[1])}]['placement']"
                if len(inputs) >= 2
                else f"dict({rp}.get('placement') or {{}})"
            )
            lines = [
                f"{var_name}_assembly = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"{var_name}_placement = {placement_expr}",
                f"{var_name} = {var_name}_assembly['container']",
                f"{var_name}_components = []",
                f"for _component in {var_name}_assembly.get('components', []):",
                f"    if str(_component.get('component_id')) == str({rp}.get('component_id')):",
                f"        _component = dict(_component)",
                f"        _component['placement'] = {var_name}_placement",
                f"        _set_component_link_placement(_component['link'], _component.get('item') or {{}}, {var_name}_placement)",
                f"    {var_name}_components.append(_component)",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_assembly)",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}]['components'] = {var_name}_components",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
            return lines
        if node.op in {
            "make_face_connector_rconnector",
            "make_edge_connector_rconnector",
            "make_vertex_connector_rconnector",
        }:
            return [
                f"{var_name} = dict({rp})",
                f"{var_name}.setdefault('anchor', {{'anchor_kind': 'geometry', 'geometry_ref': {var_name}.get('geometry_ref')}})",
                f"{var_name}.setdefault('geometry_ref', ({var_name}.get('anchor') or {{}}).get('geometry_ref'))",
                f"{var_name}.setdefault('name', {rp}.get('name'))",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = {{'kind': 'connector', 'connector': {var_name}}}",
                f"{var_name} = _register_graph_value({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if node.op == "make_placement_connector_rconnector":
            return [
                f"{var_name} = {{'connector_id': str({rp}.get('connector_id', '')), 'name': {rp}.get('name'), 'anchor': {{'anchor_kind': 'placement', 'placement': {rp}.get('placement') or {{}}}}}}",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = {{'kind': 'connector', 'connector': {var_name}}}",
                f"{var_name} = _register_graph_value({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if node.op == "make_add_connector_rpart" and len(inputs) >= 2:
            return [
                f"{var_name}_part = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"{var_name}_connector = PRODUCT_VALUES[{_json_ascii(inputs[1])}]['connector']",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_part)",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}]['connectors'] = list({var_name}_part.get('connectors', [])) + [{var_name}_connector]",
                f"_materialize_product_connector_datums(PRODUCT_VALUES[{_json_ascii(node.node_id)}])",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if node.op == "make_set_public_connector_rassembly" and len(inputs) >= 1:
            return [
                f"{var_name}_assembly = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"{var_name}_public = {{'connector_id': str({rp}.get('public_connector_id', '')), 'name': {rp}.get('name'), 'anchor': {{'anchor_kind': 'public', 'source_component_id': str({rp}.get('source_component_id', '')), 'source_connector_id': str({rp}.get('source_connector_id', ''))}}}}",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_assembly)",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}]['public_connectors'] = list({var_name}_assembly.get('public_connectors', [])) + [{var_name}_public]",
                f"_materialize_product_connector_datums(PRODUCT_VALUES[{_json_ascii(node.node_id)}])",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]

        if node.op == "make_connector_ref_rconnectorref":
            return [
                f"{var_name} = dict({rp})",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = {{'kind': 'connector_ref', 'connector_ref': {var_name}}}",
                f"{var_name} = _register_graph_value({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if node.op == "make_scalar_limit_rscalarlimit":
            return [
                f"{var_name} = dict({rp})",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = {{'kind': 'scalar_limit', 'scalar_limit': {var_name}}}",
                f"{var_name} = _register_graph_value({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if (
            node.op
            in {"make_ground_component_rassembly", "make_unground_component_rassembly"}
            and len(inputs) >= 1
        ):
            action = "add" if node.op == "make_ground_component_rassembly" else "remove"
            return [
                f"{var_name}_assembly = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_assembly)",
                f"{var_name}_grounded = list({var_name}_assembly.get('grounded_component_ids', []))",
                f"{var_name}_component_id = str({rp}.get('component_id', ''))",
                f"{var_name}_grounded = (list({var_name}_grounded) if {_json_ascii(action)} == 'add' else [component_id for component_id in {var_name}_grounded if component_id != {var_name}_component_id])",
                f"if {_json_ascii(action)} == 'add' and {var_name}_component_id not in {var_name}_grounded: {var_name}_grounded.append({var_name}_component_id)",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}]['grounded_component_ids'] = {var_name}_grounded",
                f"if {_json_ascii(action)} == 'add': _make_simplecad_grounded_joint({var_name}_assembly, {var_name}_component_id)",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if (
            node.op
            in {
                "make_fixed_constraint_rassembly",
                "make_revolute_constraint_rassembly",
                "make_prismatic_constraint_rassembly",
                "make_gear_constraint_rassembly",
                "make_belt_constraint_rassembly",
                "make_rack_pinion_constraint_rassembly",
            }
            and len(inputs) >= 3
        ):
            return [
                f"{var_name}_assembly = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"{var_name}_constraint = dict({rp})",
                f"{var_name}_constraint['connector_a'] = PRODUCT_VALUES[{_json_ascii(inputs[1])}]['connector_ref']",
                f"{var_name}_constraint['connector_b'] = PRODUCT_VALUES[{_json_ascii(inputs[2])}]['connector_ref']",
                f"{var_name}_joint = _make_simplecad_joint({var_name}_assembly, {var_name}_constraint, {_json_ascii(object_name)}, str({rp}.get('name') or {rp}.get('constraint_id') or {_json_ascii(object_name)}))",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_assembly)",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}]['constraints'] = list({var_name}_assembly.get('constraints', [])) + [{var_name}_constraint]",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if node.op == "make_solve_assembly_constraints_rassembly" and len(inputs) >= 1:
            return [
                f"{var_name}_assembly = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}] = dict({var_name}_assembly)",
                f"{var_name}_placements = dict({rp}.get('component_placements') or {{}})",
                f"{var_name}_components = []",
                f"for _component in {var_name}_assembly.get('components', []):",
                f"    _component = dict(_component)",
                f"    _component_id = str(_component.get('component_id'))",
                f"    if _component_id in {var_name}_placements:",
                f"        _component['placement'] = {var_name}_placements[_component_id]",
                f"        _set_component_link_placement(_component['link'], _component.get('item') or {{}}, _component['placement'])",
                f"    {var_name}_components.append(_component)",
                f"PRODUCT_VALUES[{_json_ascii(node.node_id)}]['components'] = {var_name}_components",
                f"{var_name} = _register_graph_folded_alias(node_id={_json_ascii(node.node_id)}, source_node_id={_json_ascii(inputs[0])}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
            ]
        if node.op == "make_compound_from_assembly_rcompound" and len(inputs) == 1:
            return [
                f"{var_name}_assembly = PRODUCT_VALUES[{_json_ascii(inputs[0])}]",
                f"ASSEMBLY_PROJECTION_INPUTS[{_json_ascii(node.node_id)}] = {_json_ascii(inputs[0])}",
                "doc.recompute()",
                f"{var_name}_shapes = _shapes_from_product_value({var_name}_assembly)",
                f"{var_name} = _make_feature({_json_ascii(object_name)}, Part.makeCompound({var_name}_shapes), node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, params={rp}, inputs={var_name}_inputs, tags={tags_literal}, context={context_literal}, output_count={node.output_count}, param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, topo_delta={topo_delta_literal})",
                f"_set_tree_visibility({var_name}, False)",
            ]
        return None


__all__ = ["ProductEmitterMixin"]

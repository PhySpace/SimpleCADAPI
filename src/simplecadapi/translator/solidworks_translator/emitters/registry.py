"""Single operation-to-emitter registry for the SolidWorks backend."""

from __future__ import annotations

from typing import Dict

from simplecadapi._cpp import OperationNode

EMITTER_METHOD_BY_OP: Dict[str, str] = {
    "make_box_rsolid": "_emit_primitives",
    "make_cylinder_rsolid": "_emit_primitives",
    "make_cone_rsolid": "_emit_primitives",
    "make_sphere_rsolid": "_emit_primitives",
    "make_line_redge": "_emit_geometry",
    "make_circle_redge": "_emit_geometry",
    "make_three_point_arc_redge": "_emit_geometry",
    "make_angle_arc_redge": "_emit_geometry",
    "make_spline_redge": "_emit_geometry",
    "make_interpolated_spline_redge": "_emit_geometry",
    "make_helix_redge": "_emit_geometry",
    "make_wire_from_edges_rwire": "_emit_geometry",
    "make_face_from_wire_rface": "_emit_geometry",
    "make_face_from_wires_rface": "_emit_geometry",
    "make_wire_from_sketch_rwire": "_emit_geometry",
    "make_face_from_sketch_rface": "_emit_geometry",
    "make_select_rvertex": "_emit_selections",
    "make_select_redge": "_emit_selections",
    "make_select_rwire": "_emit_selections",
    "make_select_rface": "_emit_selections",
    "make_select_rshell": "_emit_selections",
    "make_select_rsolid": "_emit_selections",
    "apply_tag_rselection": "_emit_selections",
    "make_extrude_rsolid": "_emit_features",
    "make_revolve_rsolid": "_emit_features",
    "make_loft_rsolid": "_emit_features",
    "make_sweep_rsolid": "_emit_features",
    "make_fillet_rsolid": "_emit_features",
    "make_chamfer_rsolid": "_emit_features",
    "make_shell_rsolid": "_emit_features",
    "make_cut_rsolid": "_emit_booleans",
    "make_union_rsolid": "_emit_booleans",
    "make_intersect_rsolid": "_emit_booleans",
    "make_translate_rshape": "_emit_transforms",
    "make_rotate_rshape": "_emit_transforms",
    "make_mirror_rshape": "_emit_transforms",
    "make_material_rmaterial": "_emit_products",
    "make_placement_rplacement": "_emit_products",
    "make_identity_placement_rplacement": "_emit_products",
    "make_part_rpart": "_emit_products",
    "make_assign_material_rpart": "_emit_products",
    "make_assembly_rassembly": "_emit_products",
    "make_add_component_rassembly": "_emit_products",
    "make_place_component_rassembly": "_emit_products",
    "make_compound_from_assembly_rcompound": "_emit_products",
    "make_face_connector_rconnector": "_emit_products",
    "make_edge_connector_rconnector": "_emit_products",
    "make_vertex_connector_rconnector": "_emit_products",
    "make_placement_connector_rconnector": "_emit_products",
    "make_add_connector_rpart": "_emit_products",
    "evaluate_assembly_definition": "_emit_products",
    "make_set_public_connector_rassembly": "_emit_products",
    "make_connector_ref_rconnectorref": "_emit_products",
    "make_scalar_limit_rscalarlimit": "_emit_products",
    "make_ground_component_rassembly": "_emit_products",
    "make_unground_component_rassembly": "_emit_products",
    "make_fixed_constraint_rassembly": "_emit_products",
    "make_revolute_constraint_rassembly": "_emit_products",
    "make_prismatic_constraint_rassembly": "_emit_products",
    "make_gear_constraint_rassembly": "_emit_products",
    "make_belt_constraint_rassembly": "_emit_products",
    "make_rack_pinion_constraint_rassembly": "_emit_products",
    "make_solve_assembly_constraints_rassembly": "_emit_products",
}


def emit_native_node(compiler, node: OperationNode):
    """Emit the per-node automation lines for one canonical graph node."""

    method_name = EMITTER_METHOD_BY_OP.get(str(node.op))
    if method_name is None:
        return None
    method = getattr(compiler, method_name, None)
    if method is None:
        return None
    return method(node)


__all__ = ["EMITTER_METHOD_BY_OP", "emit_native_node"]

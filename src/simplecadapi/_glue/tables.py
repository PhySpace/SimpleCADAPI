"""Data tables of the operator layer that kept code reads (replay validation), lifted from the old Python operators."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Mapping, Tuple

_OP_MAKE_POINT_RVERTEX = "make_point_rvertex"

_OP_LOAD_BREP_REGION_RSOLID = "load_brep_region_rsolid"

_OP_LOAD_BREP_REGION_RSHELL = "load_brep_region_rshell"

_OP_MAKE_LINE_REDGE = "make_line_redge"

_OP_MAKE_CIRCLE_REDGE = "make_circle_redge"

_OP_ADD_ELLIPSE_RSKETCH = "add_ellipse_rsketch"

_OP_MAKE_THREE_POINT_ARC_REDGE = "make_three_point_arc_redge"

_OP_MAKE_ANGLE_ARC_REDGE = "make_angle_arc_redge"

_OP_MAKE_SPLINE_REDGE = "make_spline_redge"

_OP_MAKE_INTERPOLATED_SPLINE_REDGE = "make_interpolated_spline_redge"

_OP_MAKE_HELIX_REDGE = "make_helix_redge"

_OP_MAKE_WIRE_FROM_EDGES_RWIRE = "make_wire_from_edges_rwire"

_OP_MAKE_FACE_FROM_WIRE_RFACE = "make_face_from_wire_rface"

_OP_MAKE_FACE_FROM_WIRES_RFACE = "make_face_from_wires_rface"

_OP_MAKE_TRANSLATE_RSHAPE = "make_translate_rshape"

_OP_MAKE_ROTATE_RSHAPE = "make_rotate_rshape"

_OP_MAKE_MIRROR_RSHAPE = "make_mirror_rshape"

_OP_MAKE_EXTRUDE_RSOLID = "make_extrude_rsolid"

_OP_MAKE_REVOLVE_RSOLID = "make_revolve_rsolid"

_OP_MAKE_LOFT_RSOLID = "make_loft_rsolid"

_OP_MAKE_SWEEP_RSOLID = "make_sweep_rsolid"

_OP_MAKE_TWISTED_SWEEP_RSOLID = "make_twisted_sweep_rsolid"

_OP_MAKE_UNION_RSOLID = "make_union_rsolid"

_OP_MAKE_CUT_RSOLID = "make_cut_rsolid"

_OP_MAKE_INTERSECT_RSOLID = "make_intersect_rsolid"

_OP_MAKE_CUT_RFACE = "make_2d_cut_rface"

_OP_MAKE_UNION_RFACE = "make_2d_union_rface"

_OP_MAKE_INTERSECT_RFACE = "make_2d_intersect_rface"

_OP_MAKE_FILLET_RSOLID = "make_fillet_rsolid"

_OP_MAKE_CHAMFER_RSOLID = "make_chamfer_rsolid"

_OP_MAKE_SHELL_RSOLID = "make_shell_rsolid"

_OP_MAKE_SELECT_RVERTEX = "make_select_rvertex"

_OP_MAKE_SELECT_REDGE = "make_select_redge"

_OP_MAKE_SELECT_RWIRE = "make_select_rwire"

_OP_MAKE_SELECT_RFACE = "make_select_rface"

_OP_MAKE_SELECT_RSHELL = "make_select_rshell"

_OP_MAKE_SELECT_RSOLID = "make_select_rsolid"

_OP_APPLY_TAG_RSELECTION = "apply_tag_rselection"

_OP_MAKE_SKETCH_RSKETCH = "make_sketch_rsketch"

_OP_ADD_POINT_RSKETCH = "add_point_rsketch"

_OP_ADD_LINE_RSKETCH = "add_line_rsketch"

_OP_ADD_CIRCLE_RSKETCH = "add_circle_rsketch"

_OP_ADD_ARC_RSKETCH = "add_arc_rsketch"

_OP_ADD_BSPLINE_RSKETCH = "add_bspline_rsketch"

_OP_MAKE_WIRE_FROM_SKETCH_RWIRE = "make_wire_from_sketch_rwire"

_OP_MAKE_FACE_FROM_SKETCH_RFACE = "make_face_from_sketch_rface"

_OP_MAKE_MATERIAL_RMATERIAL = "make_material_rmaterial"

_OP_MAKE_PLACEMENT_RPLACEMENT = "make_placement_rplacement"

_OP_MAKE_IDENTITY_PLACEMENT_RPLACEMENT = "make_identity_placement_rplacement"

_OP_MAKE_PART_RPART = "make_part_rpart"

_OP_MAKE_ASSIGN_MATERIAL_RPART = "make_assign_material_rpart"

_OP_MAKE_ASSEMBLY_RASSEMBLY = "make_assembly_rassembly"

_OP_MAKE_ADD_COMPONENT_RASSEMBLY = "make_add_component_rassembly"

_OP_MAKE_PLACE_COMPONENT_RASSEMBLY = "make_place_component_rassembly"

_OP_MAKE_COMPOUND_FROM_ASSEMBLY_RCOMPOUND = "make_compound_from_assembly_rcompound"

_OP_MAKE_FACE_CONNECTOR_RCONNECTOR = "make_face_connector_rconnector"

_OP_MAKE_EDGE_CONNECTOR_RCONNECTOR = "make_edge_connector_rconnector"

_OP_MAKE_VERTEX_CONNECTOR_RCONNECTOR = "make_vertex_connector_rconnector"

_OP_MAKE_PLACEMENT_CONNECTOR_RCONNECTOR = "make_placement_connector_rconnector"

_OP_MAKE_ADD_CONNECTOR_RPART = "make_add_connector_rpart"

_OP_MAKE_SET_PUBLIC_CONNECTOR_RASSEMBLY = "make_set_public_connector_rassembly"

_OP_MAKE_CONNECTOR_REF_RCONNECTORREF = "make_connector_ref_rconnectorref"

_OP_MAKE_SCALAR_LIMIT_RSCALARLIMIT = "make_scalar_limit_rscalarlimit"

_OP_MAKE_GROUND_COMPONENT_RASSEMBLY = "make_ground_component_rassembly"

_OP_MAKE_UNGROUND_COMPONENT_RASSEMBLY = "make_unground_component_rassembly"

_OP_MAKE_FIXED_CONSTRAINT_RASSEMBLY = "make_fixed_constraint_rassembly"

_OP_MAKE_REVOLUTE_CONSTRAINT_RASSEMBLY = "make_revolute_constraint_rassembly"

_OP_MAKE_PRISMATIC_CONSTRAINT_RASSEMBLY = "make_prismatic_constraint_rassembly"

_OP_MAKE_GEAR_CONSTRAINT_RASSEMBLY = "make_gear_constraint_rassembly"

_OP_MAKE_BELT_CONSTRAINT_RASSEMBLY = "make_belt_constraint_rassembly"

_OP_MAKE_RACK_PINION_CONSTRAINT_RASSEMBLY = "make_rack_pinion_constraint_rassembly"

_OP_MAKE_SOLVE_ASSEMBLY_CONSTRAINTS_RASSEMBLY = (
    "make_solve_assembly_constraints_rassembly"
)

_OPERATION_OUTPUT_ROLE_CARDINALITY: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "make_box_rsolid": (
        ("box.bottom", "one"),
        ("box.top", "one"),
        ("box.front", "one"),
        ("box.back", "one"),
        ("box.left", "one"),
        ("box.right", "one"),
    ),
    "make_cylinder_rsolid": (
        ("cylinder.start", "one"),
        ("cylinder.end", "one"),
        ("cylinder.side", "one"),
        ("cylinder.start_boundary", "one"),
        ("cylinder.end_boundary", "one"),
        ("cylinder.seam", "one"),
    ),
    "make_cone_rsolid": (
        ("cone.start", "one"),
        ("cone.end", "one"),
        ("cone.side", "one"),
        ("cone.start_boundary", "one"),
        ("cone.end_boundary", "one"),
        ("cone.seam", "one"),
    ),
    _OP_MAKE_EXTRUDE_RSOLID: (
        ("extrusion.start", "one"),
        ("extrusion.end", "one"),
        ("extrusion.side", "many"),
    ),
    _OP_MAKE_REVOLVE_RSOLID: (
        ("revolution.start", "one"),
        ("revolution.end", "one"),
        ("revolution.side", "many"),
    ),
    _OP_MAKE_FILLET_RSOLID: (("fillet.patch", "many"),),
    _OP_MAKE_CHAMFER_RSOLID: (("chamfer.patch", "many"),),
    _OP_MAKE_SHELL_RSOLID: (
        ("shell.body_face", "many"),
        ("shell.offset_face", "many"),
        ("shell.closing_descendant", "many"),
        ("shell.wall", "many"),
    ),
    _OP_MAKE_LOFT_RSOLID: (
        ("loft.start", "one"),
        ("loft.end", "one"),
        ("loft.side", "many"),
    ),
    _OP_MAKE_SWEEP_RSOLID: (
        ("sweep.start", "one"),
        ("sweep.end", "one"),
        ("sweep.side", "many"),
    ),
    "make_loft_rshell": (
        ("loft.start_wire", "one"),
        ("loft.end_wire", "one"),
        ("loft.side", "many"),
    ),
    _OP_MAKE_TWISTED_SWEEP_RSOLID: (
        ("twisted_sweep.start", "one"),
        ("twisted_sweep.end", "one"),
        ("twisted_sweep.side", "many"),
    ),
}


def get(name: str) -> Any:
    return globals()[name]

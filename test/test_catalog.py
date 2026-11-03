"""The operation catalog is read from the signatures: every public operation is in it, and its parameters say what they mean."""

from __future__ import annotations

import json

import simplecadapi as scad
from simplecadapi import catalog

# Operations whose signature still says ``object`` for some parameter: give them real types (simplecadapi.types, typed
# sequences, Literal choices) and remove them here.  The list only shrinks.
PENDING_UNTYPED = {
    "add_belt_constraint_rassembly",
    "add_component_rassembly",
    "add_connector_rpart",
    "add_fixed_constraint_rassembly",
    "add_gear_constraint_rassembly",
    "add_prismatic_constraint_rassembly",
    "add_rack_pinion_constraint_rassembly",
    "add_revolute_constraint_rassembly",
    "apply_tag_rselection",
    "assign_material_rpart",
    "boolean_rsolidlist",
    "chamfer_rsolid",
    "cut_rsolid",
    "draft_rsolid",
    "explode_rassembly",
    "extrude_taper_rsolid",
    "extrude_until_rsolid",
    "fill_holes_rshell",
    "fillet_rsolid",
    "ground_component_rassembly",
    "inspect_assembly_constraints_rconstraintreport",
    "load_brep_region_rshell",
    "load_brep_region_rsolid",
    "loft_rshell",
    "loft_rsolid",
    "make_2d_cut_rface",
    "make_2d_intersect_rface",
    "make_2d_union_rface",
    "make_assembly_rassembly",
    "make_ball_bearing_rassembly",
    "make_bolt_rsolid",
    "make_compound_from_assembly_rcompound",
    "make_connector_ref_rconnectorref",
    "make_edge_connector_rconnector",
    "make_face_connector_rconnector",
    "make_face_from_sketch_rface",
    "make_material_rmaterial",
    "make_nut_rsolid",
    "make_part_rpart",
    "make_placement_connector_rconnector",
    "make_placement_rplacement",
    "make_roller_chain_sprocket_rsolid",
    "make_scalar_limit_rscalarlimit",
    "make_sketch_rsketch",
    "make_spline_redge",
    "make_spline_rwire",
    "make_surface_patch_rface",
    "make_vertex_connector_rconnector",
    "make_wire_from_sketch_rwire",
    "measure_constraint_residual_rconstraintresidual",
    "offset_rsolid",
    "place_component_rassembly",
    "project_rsketch",
    "render_screenshot_rpath",
    "scale_rsolid",
    "set_public_connector_rassembly",
    "shell_rsolid",
    "solve_assembly_constraints_rassembly",
    "sweep_multisection_rsolid",
    "unground_component_rassembly",
    "union_rsolid",
}


def test_every_public_operation_is_in_the_catalog_with_its_parameters():
    names = {op.name for op in catalog.operations()}
    public = {n for n in scad.__all__ if catalog._OP_NAME.match(n) and callable(getattr(scad, n))}
    assert public <= names
    assert {"make_spur_gear_rsolid", "make_bolt_rsolid"} <= names  # the standard library too
    json.dumps(catalog.catalog_dict(), default=str)  # plain data


def test_the_meaning_comes_from_the_binding_types():
    cylinder = catalog.operation("make_cylinder_rsolid")
    kinds = {p.name: p.kind for p in cylinder.params}
    assert (kinds["radius"], kinds["height"], kinds["bottom_face_center"], kinds["axis"]) == ("length", "length", "point3", "direction3")
    assert cylinder.returns == "solid" and cylinder.module == "simplecadapi"
    assert next(p for p in cylinder.params if p.name == "axis").default == (0, 0, 1)
    assert next(p for p in cylinder.params if p.name == "start_face_tag").keyword_only


def test_no_operation_beyond_the_pending_list_takes_an_untyped_parameter():
    untyped = {op.name for op in catalog.operations() for p in op.params if p.kind == "unknown"}
    assert untyped <= PENDING_UNTYPED, sorted(untyped - PENDING_UNTYPED)
    assert not (PENDING_UNTYPED - untyped), f"typed now, drop from PENDING_UNTYPED: {sorted(PENDING_UNTYPED - untyped)}"


def test_types_classify():
    assert catalog.classify("Sequence[Edge]") == {"kind": "edge", "many": True, "optional": False, "choices": ()}
    assert catalog.classify("Literal['NEXT', 'LAST']")["choices"] == ("NEXT", "LAST")
    assert catalog.classify("simplecadapi.types.Angle | None") == {"kind": "angle", "many": False, "optional": True, "choices": ()}
    assert catalog.classify("Sequence[simplecadapi.types.Point3]")["kind"] == "points"

"""Graph serialization and replay executor.

Provides:
- ``export_graph_json`` / ``import_graph_json`` for JSON round-trip
- ``replay_graph`` for rebuilding a model from a recorded graph

Usage::

    from simplecadapi.recording.serializer import export_graph_json, import_graph_json, replay_graph

    # Serialize
    json_str = export_graph_json(session.graph)

    # Deserialize
    graph = import_graph_json(json_str)

    # Rebuild
    solids = replay_graph(graph)
"""

from __future__ import annotations

import math
from contextlib import nullcontext
from pathlib import Path

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from ..errors import raise_harness_error

from ..core import (
    AnyShape,
    Compound,
    Edge,
    Face,
    Shell,
    Solid,
    Vertex,
    Wire,
    clone_semantic_shape_view,
    use_coordinate_system,
)
from .graph import (
    GraphSession,
    attach_graph_node,
    attach_semantic_graph_node,
    suspend_graph_recording,
)
from ..ql import output_role, selector_from_dict
from ..sketch import Sketch
from ..product.assembly import Assembly, _restore_component_occurrence_placements
from ..product.solver import constraint_reports_match
from ..product.connector import Connector, ConnectorRef, GeometryRef
from ..product.constraint import ScalarLimit
from ..product.material import Material
from ..product.part import Part
from ..product.placement import Placement, placement_ticks
from ..topology.model import (
    GRAPH_SCHEMA_VERSION,
    OperationGraph,
    TopoRef,
    semantic_delta_to_dict,
    topo_delta_to_dict,
    topo_ref_to_dict,
    topo_ref_from_dict,
)
from ..topology.tagging import TagBinding, TagTargetKind
from .. import operators as ops
from ..kernel.ocp_properties import bounding_box


MODEL_SCHEMA_VERSION = "2.0"
CANONICAL_CONTRACT_VERSION = "2.1"
SUPPORTED_CANONICAL_CONTRACT_VERSIONS = {"2.0", CANONICAL_CONTRACT_VERSION}

PUBLIC_API_COVERAGE: Dict[str, Dict[str, str]] = {
    # Core geometry ops that are recorded and replayable
    "make_point_rvertex": {"status": "replayable", "op": "make_point_rvertex"},
    "make_line_redge": {"status": "replayable", "op": "make_line_redge"},
    "make_segment_redge": {"status": "expanded_macro", "op": "make_line_redge"},
    "make_segment_rwire": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into make_line_redge + make_wire_from_edges_rwire.",
    },
    "make_circle_redge": {"status": "replayable", "op": "make_circle_redge"},
    "make_circle_rwire": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into make_circle_redge + make_wire_from_edges_rwire.",
    },
    "make_circle_rface": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into edge/wire/face low-level operations.",
    },
    "make_rectangle_rwire": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into make_line_redge + make_wire_from_edges_rwire.",
    },
    "make_rectangle_rface": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into low-level line/wire/face operations.",
    },
    "make_face_from_wire_rface": {
        "status": "replayable",
        "op": "make_face_from_wire_rface",
    },
    "make_face_from_wires_rface": {
        "status": "replayable",
        "op": "make_face_from_wires_rface",
    },
    "make_wire_from_edges_rwire": {
        "status": "replayable",
        "op": "make_wire_from_edges_rwire",
    },
    "make_sketch_rsketch": {"status": "replayable", "op": "make_sketch_rsketch"},
    "add_point_rsketch": {"status": "replayable", "op": "add_point_rsketch"},
    "add_line_rsketch": {"status": "replayable", "op": "add_line_rsketch"},
    "add_circle_rsketch": {"status": "replayable", "op": "add_circle_rsketch"},
    "add_arc_rsketch": {"status": "replayable", "op": "add_arc_rsketch"},
    "add_bspline_rsketch": {"status": "replayable", "op": "add_bspline_rsketch"},
    "add_ellipse_rsketch": {"status": "replayable", "op": "add_ellipse_rsketch"},
    "constrain_coincident_rsketch": {
        "status": "replayable",
        "op": "make_constrain_coincident_rsketch",
    },
    "constrain_connect_rsketch": {
        "status": "replayable",
        "op": "make_constrain_coincident_rsketch",
    },
    "constrain_point_on_rsketch": {
        "status": "replayable",
        "op": "make_constrain_point_on_rsketch",
    },
    "constrain_horizontal_rsketch": {
        "status": "replayable",
        "op": "make_constrain_horizontal_rsketch",
    },
    "constrain_vertical_rsketch": {
        "status": "replayable",
        "op": "make_constrain_vertical_rsketch",
    },
    "constrain_major_radius_rsketch": {
        "status": "replayable",
        "op": "make_constrain_major_radius_rsketch",
    },
    "constrain_minor_radius_rsketch": {
        "status": "replayable",
        "op": "make_constrain_minor_radius_rsketch",
    },
    "constrain_points_horizontal_rsketch": {
        "status": "replayable",
        "op": "make_constrain_points_horizontal_rsketch",
    },
    "constrain_points_vertical_rsketch": {
        "status": "replayable",
        "op": "make_constrain_points_vertical_rsketch",
    },
    "constrain_line_distance_rsketch": {
        "status": "replayable",
        "op": "make_constrain_line_distance_rsketch",
    },
    "constrain_normal_rsketch": {
        "status": "replayable",
        "op": "make_constrain_normal_rsketch",
    },
    "constrain_mirror_rsketch": {
        "status": "replayable",
        "op": "make_constrain_mirror_rsketch",
    },
    "constrain_midpoint_points_rsketch": {
        "status": "replayable",
        "op": "make_constrain_midpoint_points_rsketch",
    },
    "constrain_parallel_rsketch": {
        "status": "replayable",
        "op": "make_constrain_parallel_rsketch",
    },
    "constrain_perpendicular_rsketch": {
        "status": "replayable",
        "op": "make_constrain_perpendicular_rsketch",
    },
    "constrain_collinear_rsketch": {
        "status": "replayable",
        "op": "make_constrain_collinear_rsketch",
    },
    "constrain_tangent_rsketch": {
        "status": "replayable",
        "op": "make_constrain_tangent_rsketch",
    },
    "constrain_concentric_rsketch": {
        "status": "replayable",
        "op": "make_constrain_concentric_rsketch",
    },
    "constrain_midpoint_rsketch": {
        "status": "replayable",
        "op": "make_constrain_midpoint_rsketch",
    },
    "constrain_symmetric_rsketch": {
        "status": "replayable",
        "op": "make_constrain_symmetric_rsketch",
    },
    "constrain_equal_length_rsketch": {
        "status": "replayable",
        "op": "make_constrain_equal_length_rsketch",
    },
    "constrain_equal_radius_rsketch": {
        "status": "replayable",
        "op": "make_constrain_equal_radius_rsketch",
    },
    "constrain_distance_rsketch": {
        "status": "replayable",
        "op": "make_constrain_distance_rsketch",
    },
    "constrain_distance_x_rsketch": {
        "status": "replayable",
        "op": "make_constrain_distance_x_rsketch",
    },
    "constrain_distance_y_rsketch": {
        "status": "replayable",
        "op": "make_constrain_distance_y_rsketch",
    },
    "constrain_length_rsketch": {
        "status": "replayable",
        "op": "make_constrain_length_rsketch",
    },
    "constrain_angle_rsketch": {
        "status": "replayable",
        "op": "make_constrain_angle_rsketch",
    },
    "constrain_radius_rsketch": {
        "status": "replayable",
        "op": "make_constrain_radius_rsketch",
    },
    "constrain_diameter_rsketch": {
        "status": "replayable",
        "op": "make_constrain_diameter_rsketch",
    },
    "constrain_fix_rsketch": {
        "status": "replayable",
        "op": "make_constrain_fix_rsketch",
    },
    "inspect_sketch_rsketchresult": {
        "status": "diagnostic",
        "reason": "Runs the sketch solver for inspection only; solve evidence is recorded on sketch promotion nodes.",
    },
    "make_wire_from_sketch_rwire": {
        "status": "replayable",
        "op": "make_wire_from_sketch_rwire",
    },
    "make_face_from_sketch_rface": {
        "status": "replayable",
        "op": "make_face_from_sketch_rface",
    },
    "make_material_rmaterial": {
        "status": "replayable",
        "op": "make_material_rmaterial",
    },
    "make_placement_rplacement": {
        "status": "replayable",
        "op": "make_placement_rplacement",
    },
    "identity_placement_rplacement": {
        "status": "replayable",
        "op": "make_identity_placement_rplacement",
    },
    "make_part_rpart": {"status": "replayable", "op": "make_part_rpart"},
    "assign_material_rpart": {
        "status": "replayable",
        "op": "make_assign_material_rpart",
    },
    "make_assembly_rassembly": {
        "status": "replayable",
        "op": "make_assembly_rassembly",
    },
    "add_component_rassembly": {
        "status": "replayable",
        "op": "make_add_component_rassembly",
    },
    "place_component_rassembly": {
        "status": "replayable",
        "op": "make_place_component_rassembly",
    },
    "make_compound_from_assembly_rcompound": {
        "status": "replayable",
        "op": "make_compound_from_assembly_rcompound",
    },
    "make_face_connector_rconnector": {
        "status": "replayable",
        "op": "make_face_connector_rconnector",
    },
    "make_edge_connector_rconnector": {
        "status": "replayable",
        "op": "make_edge_connector_rconnector",
    },
    "make_vertex_connector_rconnector": {
        "status": "replayable",
        "op": "make_vertex_connector_rconnector",
    },
    "make_placement_connector_rconnector": {
        "status": "replayable",
        "op": "make_placement_connector_rconnector",
    },
    "add_connector_rpart": {"status": "replayable", "op": "make_add_connector_rpart"},
    "set_public_connector_rassembly": {
        "status": "replayable",
        "op": "make_set_public_connector_rassembly",
    },
    "make_connector_ref_rconnectorref": {
        "status": "replayable",
        "op": "make_connector_ref_rconnectorref",
    },
    "make_scalar_limit_rscalarlimit": {
        "status": "replayable",
        "op": "make_scalar_limit_rscalarlimit",
    },
    "ground_component_rassembly": {
        "status": "replayable",
        "op": "make_ground_component_rassembly",
    },
    "unground_component_rassembly": {
        "status": "replayable",
        "op": "make_unground_component_rassembly",
    },
    "add_fixed_constraint_rassembly": {
        "status": "replayable",
        "op": "make_fixed_constraint_rassembly",
    },
    "add_revolute_constraint_rassembly": {
        "status": "replayable",
        "op": "make_revolute_constraint_rassembly",
    },
    "add_prismatic_constraint_rassembly": {
        "status": "replayable",
        "op": "make_prismatic_constraint_rassembly",
    },
    "add_gear_constraint_rassembly": {
        "status": "replayable",
        "op": "make_gear_constraint_rassembly",
    },
    "add_belt_constraint_rassembly": {
        "status": "replayable",
        "op": "make_belt_constraint_rassembly",
    },
    "add_rack_pinion_constraint_rassembly": {
        "status": "replayable",
        "op": "make_rack_pinion_constraint_rassembly",
    },
    "solve_assembly_constraints_rassembly": {
        "status": "replayable",
        "op": "make_solve_assembly_constraints_rassembly",
    },
    "measure_constraint_residual_rconstraintresidual": {
        "status": "diagnostic",
        "reason": "Measures current constraint residuals without changing model state.",
    },
    "inspect_assembly_constraints_rconstraintreport": {
        "status": "diagnostic",
        "reason": "Inspects current constraint state without changing model state.",
    },
    "make_box_rsolid": {
        "status": "replayable",
        "op": "make_box_rsolid",
    },
    "load_brep_region_rsolid": {
        "status": "replayable",
        "op": "load_brep_region_rsolid",
    },
    "load_brep_region_rshell": {
        "status": "replayable",
        "op": "load_brep_region_rshell",
    },
    "make_cylinder_rsolid": {
        "status": "replayable",
        "op": "make_cylinder_rsolid",
    },
    "make_cone_rsolid": {
        "status": "replayable",
        "op": "make_cone_rsolid",
    },
    "make_sphere_rsolid": {
        "status": "replayable",
        "op": "make_sphere_rsolid",
    },
    "make_three_point_arc_redge": {
        "status": "replayable",
        "op": "make_three_point_arc_redge",
    },
    "make_three_point_arc_rwire": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into make_three_point_arc_redge + make_wire_from_edges_rwire.",
    },
    "make_angle_arc_redge": {"status": "replayable", "op": "make_angle_arc_redge"},
    "make_angle_arc_rwire": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into make_angle_arc_redge + make_wire_from_edges_rwire.",
    },
    "make_spline_redge": {"status": "replayable", "op": "make_spline_redge"},
    "make_interpolated_spline_redge": {
        "status": "replayable",
        "op": "make_interpolated_spline_redge",
    },
    "make_interpolated_spline_rwire": {
        "status": "macro",
        "reason": "Composite convenience API that lowers into make_interpolated_spline_redge + make_wire_from_edges_rwire.",
    },
    "make_periodic_spline_rwire": {
        "status": "macro",
        "reason": "Periodic convenience API that lowers into make_interpolated_spline_redge + make_wire_from_edges_rwire.",
    },
    "make_spline_rwire": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into make_spline_redge + make_wire_from_edges_rwire when open.",
    },
    "make_polyline_rwire": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into make_line_redge + make_wire_from_edges_rwire.",
    },
    "make_helix_redge": {"status": "replayable", "op": "make_helix_redge"},
    "make_helix_rwire": {
        "status": "macro",
        "reason": "Composite convenience API that should lower into make_helix_redge + make_wire_from_edges_rwire.",
    },
    "translate_shape": {"status": "replayable", "op": "make_translate_rshape"},
    "rotate_shape": {"status": "replayable", "op": "make_rotate_rshape"},
    "scale_rsolid": {"status": "replayable", "op": "make_scale_rsolid"},
    "transform_rsolid": {"status": "replayable", "op": "make_transform_rsolid"},
    "offset_rsolid": {"status": "replayable", "op": "make_offset_rsolid"},
    "extrude_taper_rsolid": {"status": "replayable", "op": "make_extrude_taper_rsolid"},
    "sweep_multisection_rsolid": {"status": "replayable", "op": "make_sweep_multisection_rsolid"},
    "extrude_until_rsolid": {"status": "replayable", "op": "make_extrude_until_rsolid"},
    "draft_rsolid": {"status": "replayable", "op": "make_draft_rsolid"},
    "mirror_shape": {"status": "replayable", "op": "make_mirror_rshape"},
    "extrude_rsolid": {"status": "replayable", "op": "make_extrude_rsolid"},
    "revolve_rsolid": {"status": "replayable", "op": "make_revolve_rsolid"},
    "loft_rsolid": {"status": "replayable", "op": "make_loft_rsolid"},
    "sweep_rsolid": {"status": "replayable", "op": "make_sweep_rsolid"},
    "twisted_sweep_rsolid": {
        "status": "replayable",
        "op": "make_twisted_sweep_rsolid",
    },
    "helical_sweep_rsolid": {
        "status": "expanded_macro",
        "op": "make_sweep_rsolid",
        "reason": "Recorded as make_helix_wire + sweep macro instead of a dedicated core IR node.",
    },
    "union_rsolid": {"status": "replayable", "op": "make_union_rsolid"},
    "cut_rsolid": {"status": "replayable", "op": "make_cut_rsolid"},
    "intersect_rsolid": {"status": "replayable", "op": "make_intersect_rsolid"},
    "make_2d_cut_rface": {"status": "replayable", "op": "make_2d_cut_rface"},
    "make_2d_union_rface": {"status": "replayable", "op": "make_2d_union_rface"},
    "make_2d_intersect_rface": {
        "status": "replayable",
        "op": "make_2d_intersect_rface",
    },
    "fillet_rsolid": {"status": "replayable", "op": "make_fillet_rsolid"},
    "chamfer_rsolid": {"status": "replayable", "op": "make_chamfer_rsolid"},
    "shell_rsolid": {"status": "replayable", "op": "make_shell_rsolid"},
    "make_bezier_surface_rface": {
        "status": "replayable",
        "op": "make_bezier_surface_rface",
    },
    "fit_point_grid_rface": {"status": "replayable", "op": "fit_point_grid_rface"},
    "make_ruled_surface_rface": {
        "status": "replayable",
        "op": "make_ruled_surface_rface",
    },
    "make_gordon_surface_rface": {
        "status": "replayable",
        "op": "make_gordon_surface_rface",
    },
    "make_surface_patch_rface": {
        "status": "replayable",
        "op": "make_surface_patch_rface",
    },
    "loft_rshell": {"status": "replayable", "op": "make_loft_rshell"},
    "make_cylindrical_surface_rface": {
        "status": "replayable",
        "op": "make_cylindrical_surface_rface",
    },
    "trim_surface_rface": {"status": "replayable", "op": "trim_surface_rface"},
    "sew_faces_rshell": {"status": "replayable", "op": "sew_faces_rshell"},
    "make_solid_from_shell_rsolid": {
        "status": "replayable",
        "op": "make_solid_from_shell_rsolid",
    },
    "free_boundaries_rwirelist": {
        "status": "replayable",
        "op": "free_boundaries_rwirelist",
    },
    "fill_holes_rshell": {"status": "replayable", "op": "fill_holes_rshell"},
    "make_select_rvertex": {"status": "replayable", "op": "make_select_rvertex"},
    "make_select_redge": {"status": "replayable", "op": "make_select_redge"},
    "make_select_rwire": {"status": "replayable", "op": "make_select_rwire"},
    "make_select_rface": {"status": "replayable", "op": "make_select_rface"},
    "make_select_rshell": {"status": "replayable", "op": "make_select_rshell"},
    "make_select_rsolid": {"status": "replayable", "op": "make_select_rsolid"},
    "apply_tag": {
        "status": "semantic_replayable",
        "op": "apply_tag_rselection",
    },
    "apply_tag_rselection": {
        "status": "semantic_replayable",
        "op": "apply_tag_rselection",
    },
    "linear_pattern_rsolidlist": {
        "status": "macro",
        "reason": "Pattern convenience API that should lower into repeated make_translate_rshape nodes.",
    },
    "radial_pattern_rsolidlist": {
        "status": "macro",
        "reason": "Pattern convenience API that should lower into repeated make_rotate_rshape nodes.",
    },
}


CANONICAL_CORE_OP_SET: Tuple[str, ...] = (
    "load_brep_region_rshell",
    "load_brep_region_rsolid",
    "make_point_rvertex",
    "make_line_redge",
    "make_circle_redge",
    "make_ellipse_redge",
    "make_three_point_arc_redge",
    "make_angle_arc_redge",
    "make_spline_redge",
    "make_interpolated_spline_redge",
    "make_helix_redge",
    "make_wire_from_edges_rwire",
    "make_face_from_wire_rface",
    "make_face_from_wires_rface",
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
    "make_constrain_major_radius_rsketch",
    "make_constrain_minor_radius_rsketch",
    "make_constrain_points_horizontal_rsketch",
    "make_constrain_points_vertical_rsketch",
    "make_constrain_line_distance_rsketch",
    "make_constrain_normal_rsketch",
    "make_constrain_mirror_rsketch",
    "make_constrain_midpoint_points_rsketch",
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
    "make_wire_from_sketch_rwire",
    "make_face_from_sketch_rface",
    "make_box_rsolid",
    "make_cylinder_rsolid",
    "make_cone_rsolid",
    "make_sphere_rsolid",
    "make_material_rmaterial",
    "make_placement_rplacement",
    "make_identity_placement_rplacement",
    "make_part_rpart",
    "make_assign_material_rpart",
    "make_assembly_rassembly",
    "reference_definition",
    "make_add_component_rassembly",
    "make_place_component_rassembly",
    "make_compound_from_assembly_rcompound",
    "make_face_connector_rconnector",
    "make_edge_connector_rconnector",
    "make_vertex_connector_rconnector",
    "make_placement_connector_rconnector",
    "make_add_connector_rpart",
    "make_set_public_connector_rassembly",
    "make_connector_ref_rconnectorref",
    "make_scalar_limit_rscalarlimit",
    "make_ground_component_rassembly",
    "make_unground_component_rassembly",
    "make_fixed_constraint_rassembly",
    "make_revolute_constraint_rassembly",
    "make_prismatic_constraint_rassembly",
    "make_gear_constraint_rassembly",
    "make_belt_constraint_rassembly",
    "make_rack_pinion_constraint_rassembly",
    "make_solve_assembly_constraints_rassembly",
    "evaluate_assembly_definition",
    "make_extrude_rsolid",
    "make_revolve_rsolid",
    "make_loft_rsolid",
    "make_sweep_rsolid",
    "make_twisted_sweep_rsolid",
    "make_translate_rshape",
    "make_rotate_rshape",
    "make_scale_rsolid",
    "make_transform_rsolid",
    "make_offset_rsolid",
    "make_extrude_taper_rsolid",
    "make_sweep_multisection_rsolid",
    "make_extrude_until_rsolid",
    "make_draft_rsolid",
    "make_mirror_rshape",
    "make_cut_rsolid",
    "make_union_rsolid",
    "make_intersect_rsolid",
    "make_2d_cut_rface",
    "make_2d_union_rface",
    "make_2d_intersect_rface",
    "make_fillet_rsolid",
    "make_chamfer_rsolid",
    "make_shell_rsolid",
    "make_bezier_surface_rface",
    "make_cylindrical_surface_rface",
    "fit_point_grid_rface",
    "make_ruled_surface_rface",
    "make_gordon_surface_rface",
    "make_surface_patch_rface",
    "trim_surface_rface",
    "make_loft_rshell",
    "sew_faces_rshell",
    "make_solid_from_shell_rsolid",
    "free_boundaries_rwirelist",
    "fill_holes_rshell",
    "make_select_rvertex",
    "make_select_redge",
    "make_select_rwire",
    "make_select_rface",
    "make_select_rshell",
    "make_select_rsolid",
)

CANONICAL_SEMANTIC_OP_SET: Tuple[str, ...] = ("apply_tag_rselection",)

CANONICAL_OP_SET: Tuple[str, ...] = (
    *CANONICAL_CORE_OP_SET,
    *CANONICAL_SEMANTIC_OP_SET,
)

_CANONICAL_2_1_ONLY_OPS = {
    "load_brep_region_rshell",
    "load_brep_region_rsolid",
    "make_solid_from_shell_rsolid",
}
CANONICAL_CORE_OP_SET_2_0: Tuple[str, ...] = tuple(
    op for op in CANONICAL_CORE_OP_SET if op not in _CANONICAL_2_1_ONLY_OPS
)
CANONICAL_OP_SET_2_0: Tuple[str, ...] = (
    *CANONICAL_CORE_OP_SET_2_0,
    *CANONICAL_SEMANTIC_OP_SET,
)

SELECTION_REF_SCHEMA: Dict[str, Any] = {
    "edge_param": "selected_edges",
    "face_param": "selected_faces",
    "edge_index_param": "selected_edge_indices",
    "face_index_param": "selected_face_indices",
    "required_topo_ref_fields": [
        "graph_id",
        "node_id",
        "output_slot",
        "kind",
        "topo_id",
    ],
    "optional_fields": ["selector_hint", "geo_selector", "selected_*_node_ids"],
    "replay_resolution_order": [
        "geo_select_nodes",
        "selection_query",
        "explicit_topo_refs",
        "stable_indices",
        "selector_hint",
    ],
}


def _canonical_contract_payload(
    contract_version: str = CANONICAL_CONTRACT_VERSION,
) -> Dict[str, Any]:
    if contract_version not in SUPPORTED_CANONICAL_CONTRACT_VERSIONS:
        raise ValueError(f"Unsupported canonical contract version '{contract_version}'")
    core_op_set = (
        CANONICAL_CORE_OP_SET
        if contract_version == CANONICAL_CONTRACT_VERSION
        else CANONICAL_CORE_OP_SET_2_0
    )
    return {
        "contract_version": contract_version,
        "graph_roles": {
            "graph": "canonical_low_level_graph",
            "leaf_ids": "explicit_result_set",
        },
        "replay_policy": {
            "preferred_graph": "graph",
            "default_mode": "strict",
            "permissive_mode": "explicit_opt_in",
        },
        "core_op_set": list(core_op_set),
        "semantic_op_set": list(CANONICAL_SEMANTIC_OP_SET),
        "selection_ref_schema": {
            "edge_param": SELECTION_REF_SCHEMA["edge_param"],
            "face_param": SELECTION_REF_SCHEMA["face_param"],
            "edge_index_param": SELECTION_REF_SCHEMA["edge_index_param"],
            "face_index_param": SELECTION_REF_SCHEMA["face_index_param"],
            "required_topo_ref_fields": list(
                SELECTION_REF_SCHEMA["required_topo_ref_fields"]
            ),
            "optional_fields": list(SELECTION_REF_SCHEMA["optional_fields"]),
            "replay_resolution_order": list(
                SELECTION_REF_SCHEMA["replay_resolution_order"]
            ),
        },
    }


def _validate_canonical_contract(contract: Any) -> Tuple[str, ...]:
    if not isinstance(contract, dict):
        raise ValueError("Model payload is missing canonical_contract")
    contract_version = str(contract.get("contract_version", ""))
    if contract_version not in SUPPORTED_CANONICAL_CONTRACT_VERSIONS:
        raise ValueError(f"Unsupported canonical contract version '{contract_version}'")
    expected = _canonical_contract_payload(contract_version)
    if contract_version == "2.0" and contract == {"contract_version": "2.0"}:
        return CANONICAL_OP_SET_2_0
    if contract == expected:
        return (
            CANONICAL_OP_SET
            if contract_version == CANONICAL_CONTRACT_VERSION
            else CANONICAL_OP_SET_2_0
        )
    if (
        contract_version == "2.0"
        and isinstance(contract.get("core_op_set"), list)
        and contract.get("graph_roles") == expected.get("graph_roles")
        and contract.get("replay_policy") == expected.get("replay_policy")
        and contract.get("semantic_op_set") == expected.get("semantic_op_set")
    ):
        # Accept the SimpleCADAPI 2.0.x contract layout whose declared
        # core_op_set predates later op renames; graph operations are still
        # validated against the current canonical 2.0 set below.
        return CANONICAL_OP_SET_2_0
    raise ValueError(
        "Model canonical_contract does not match the declared contract version"
    )


def _assert_graph_is_canonical(
    graph: OperationGraph, *, allowed_ops: Sequence[str] = CANONICAL_OP_SET
) -> None:
    allowed = set(allowed_ops)
    invalid_ops = sorted(
        {node.op for node in graph.nodes if node.op not in allowed}
    )
    if invalid_ops:
        raise ValueError(
            "graph contains non-canonical operations: " + ", ".join(invalid_ops)
        )


def _as_vec3_tuple(value: Any) -> Tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("Expected a 3D vector-like value")
    return (float(value[0]), float(value[1]), float(value[2]))


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


def export_graph_json(graph: OperationGraph, indent: int = 2) -> str:
    """Export an OperationGraph to a JSON string.

    Args:
        graph: The graph to export.
        indent: JSON indentation level.

    Returns:
        JSON string representation.
    """
    _assert_graph_is_canonical(graph)
    return graph.to_json(indent=indent)


def export_session_json(session: "GraphSession", indent: int = 2) -> str:
    """Export a graph session including its expression graph."""

    import json

    session.tolerance_graph.validate(raise_on_failure=True)
    return json.dumps(
        {
            "graph": session.graph.to_dict(),
            "expression_graph": session.expression_graph.to_dict(),
            "tolerance_graph": session.tolerance_graph.to_dict(),
            "frame_graph": session.frame_graph.to_dict(),
            "result_node_ids": list(session.result_node_ids),
            "has_explicit_results": session.has_explicit_results,
        },
        indent=indent,
    )


def import_graph_json(json_str: str) -> OperationGraph:
    """Import an OperationGraph from a JSON string.

    Args:
        json_str: JSON string to parse.

    Returns:
        Reconstructed OperationGraph.
    """
    import json

    try:
        payload = json.loads(json_str)
        schema_version = str(payload.get("schema_version", ""))
        if schema_version != GRAPH_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported graph schema_version '{schema_version}'. Expected {GRAPH_SCHEMA_VERSION}."
            )
        graph = OperationGraph.from_dict(payload)
        _assert_graph_is_canonical(graph)
        return graph
    except Exception as e:
        raise_harness_error(
            operation="import_graph_json",
            what_happened="Failed to import the graph JSON payload.",
            possible_causes=[
                "The input string is not valid JSON.",
                "The payload does not follow the expected graph schema.",
                "The graph schema_version is unsupported.",
            ],
            how_to_fix=[
                "Pass a valid JSON string produced by export_graph_json().",
                f"Make sure the payload includes graph schema_version {GRAPH_SCHEMA_VERSION}.",
                "If you edited the payload manually, validate the nodes and edges structure before retrying.",
            ],
            error=e,
        )


def import_session_json(json_str: str) -> Dict[str, Any]:
    """Import session payload containing graph and expression graph."""

    import json

    from ..params.expr import ExpressionGraph
    from ..params.frame import FrameGraph
    from ..params.tolerance import ToleranceGraph

    try:
        payload = json.loads(json_str)
        graph_payload = payload.get("graph")
        if not isinstance(graph_payload, dict):
            raise ValueError("Session payload is missing 'graph'")

        expr_payload = payload.get("expression_graph")
        if expr_payload is None:
            expr_graph = ExpressionGraph()
        elif isinstance(expr_payload, dict):
            expr_graph = ExpressionGraph.from_dict(expr_payload)
        else:
            raise ValueError("Session payload 'expression_graph' must be an object")

        tolerance_payload = payload.get("tolerance_graph")
        if tolerance_payload is None:
            tolerance_graph = ToleranceGraph(expr_graph)
        elif isinstance(tolerance_payload, dict):
            tolerance_graph = ToleranceGraph.from_dict(tolerance_payload, expr_graph)
        else:
            raise ValueError("Session payload 'tolerance_graph' must be an object")
        tolerance_graph.validate(raise_on_failure=True)

        frame_payload = payload.get("frame_graph")
        if frame_payload is None:
            frame_graph = FrameGraph()
        elif isinstance(frame_payload, dict):
            frame_graph = FrameGraph.from_dict(frame_payload)
        else:
            raise ValueError("Session payload 'frame_graph' must be an object")

        graph = OperationGraph.from_dict(graph_payload)
        _assert_graph_is_canonical(graph)

        return {
            "graph": graph,
            "expression_graph": expr_graph,
            "tolerance_graph": tolerance_graph,
            "frame_graph": frame_graph,
            "result_node_ids": [str(v) for v in payload.get("result_node_ids", [])],
            "has_explicit_results": bool(payload.get("has_explicit_results", False)),
        }
    except Exception as e:
        raise_harness_error(
            operation="import_session_json",
            what_happened="Failed to import the session JSON payload.",
            possible_causes=[
                "The input string is not valid JSON.",
                "The session payload is missing the required 'graph' object.",
                "The expression_graph, tolerance_graph, or frame_graph fields use the wrong JSON type.",
            ],
            how_to_fix=[
                "Pass a valid JSON string produced by export_session_json().",
                "Make sure 'graph' is present and is a JSON object.",
                "Use JSON objects for expression_graph, tolerance_graph, and frame_graph, not strings or arrays.",
            ],
            error=e,
        )


def export_model_json(
    session: "GraphSession",
    indent: int = 2,
    *,
    result_node_ids: Optional[Sequence[str]] = None,
) -> str:
    """Export the canonical 2.0 model seed JSON.

    Current Phase 1 scope uses the active session as the container of:
    - operation graph
    - expression graph
    - capabilities/schema metadata
    """

    import json

    try:
        geometry_registry: List[Dict[str, Any]] = []
        semantic_entity_registry: List[Dict[str, Any]] = []
        sketch_profile_registry: List[Dict[str, Any]] = []
        semantic_delta_log: List[Dict[str, Any]] = []
        topology_delta_log: List[Dict[str, Any]] = []
        semantic_bindings: List[Dict[str, Any]] = []

        for node in session.graph.topological_order():
            if node.op == "apply_tag_rselection":
                binding_payload = node.params.get("tag_binding")
                if not isinstance(binding_payload, dict):
                    raise ValueError(
                        f"semantic tag node '{node.node_id}' has no TagBinding payload"
                    )
                binding = TagBinding.from_dict(binding_payload)
                if binding.producer.node_id != node.node_id:
                    raise ValueError(
                        f"semantic tag node '{node.node_id}' does not own binding '{binding.binding_id}'"
                    )
                semantic_bindings.append(binding.to_dict())
            if node.semantic_delta is not None:
                semantic_delta_log.append(
                    {
                        "node_id": node.node_id,
                        "op": node.op,
                        "delta": semantic_delta_to_dict(node.semantic_delta),
                    }
                )
                for ref in node.semantic_delta.created:
                    geometry_registry.append(
                        {
                            "graph_id": ref.graph_id,
                            "node_id": ref.node_id,
                            "entity_type": ref.entity_type,
                            "entity_id": ref.entity_id,
                            "source_op": node.op,
                        }
                    )
                    semantic_entity_registry.append(
                        {
                            "graph_id": ref.graph_id,
                            "node_id": ref.node_id,
                            "entity_type": ref.entity_type,
                            "entity_id": ref.entity_id,
                            "source_op": node.op,
                        }
                    )
            else:
                for slot in range(node.output_count):
                    geometry_registry.append(
                        {
                            "graph_id": session.graph.graph_id,
                            "node_id": node.node_id,
                            "entity_type": "ShapeOutput",
                            "entity_id": f"{node.op}:{slot}",
                            "source_op": node.op,
                        }
                    )

            if node.topo_delta is not None:
                topology_delta_log.append(
                    {
                        "node_id": node.node_id,
                        "op": node.op,
                        "delta": topo_delta_to_dict(node.topo_delta),
                    }
                )

            if node.op in {
                "make_point_rvertex",
                "make_line_redge",
                "make_circle_redge",
                "make_ellipse_redge",
                "make_three_point_arc_redge",
                "make_angle_arc_redge",
                "make_spline_redge",
                "make_interpolated_spline_redge",
                "make_helix_redge",
                "make_wire_from_edges_rwire",
                "make_face_from_wire_rface",
                "make_face_from_wires_rface",
                "make_wire_from_sketch_rwire",
                "make_face_from_sketch_rface",
            }:
                sketch_profile_registry.append(
                    {
                        "graph_id": session.graph.graph_id,
                        "node_id": node.node_id,
                        "op": node.op,
                        "params": dict(node.params),
                    }
                )

        frame_graph_payload = session.frame_graph.to_dict()

        _assert_graph_is_canonical(session.graph)
        session.tolerance_graph.validate(raise_on_failure=True)
        if result_node_ids is not None:
            leaf_ids = [str(node_id) for node_id in result_node_ids]
        elif session.has_explicit_results:
            leaf_ids = list(session.result_node_ids)
        else:
            leaf_ids = [node.node_id for node in session.graph.leaf_nodes()]
        unknown_result_ids = [
            node_id for node_id in leaf_ids if session.graph.get_node(node_id) is None
        ]
        if unknown_result_ids:
            raise ValueError(
                "model result node ids are not present in the session graph: "
                + ", ".join(unknown_result_ids)
            )

        payload: Dict[str, Any] = {
            "schema_version": MODEL_SCHEMA_VERSION,
            "canonical_contract": _canonical_contract_payload(),
            "graph": session.graph.to_dict(),
            "leaf_ids": leaf_ids,
            "expression_graph": session.expression_graph.to_dict(),
            "tolerance_graph": session.tolerance_graph.to_dict(),
            "frame_graph": frame_graph_payload,
            "geometry_registry": geometry_registry,
            "semantic_entity_registry": semantic_entity_registry,
            "sketch_profile_registry": sketch_profile_registry,
            "semantic_delta_log": semantic_delta_log,
            "topology_delta_log": topology_delta_log,
            "semantic_bindings": semantic_bindings,
        }

        return json.dumps(payload, indent=indent)
    except Exception as e:
        raise_harness_error(
            operation="export_model_json",
            what_happened="Failed to export the canonical model JSON payload.",
            possible_causes=[
                "The session contains non-serializable graph, expression, or frame data.",
                "The graph contains non-canonical operations instead of the strict low-level op set.",
            ],
            how_to_fix=[
                "Pass a valid GraphSession object built by SimpleCADAPI.",
                "Make sure composite builtins only emit strict low-level graph nodes before exporting model JSON.",
            ],
            error=e,
        )


def import_model_json(json_str: str) -> Dict[str, Any]:
    """Import canonical 2.0 model seed JSON."""

    import json

    try:
        payload = json.loads(json_str)
        schema_version = str(payload.get("schema_version", ""))
        if schema_version != MODEL_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported model schema_version '{schema_version}'; expected {MODEL_SCHEMA_VERSION}"
            )
        if "canonical_contract" not in payload:
            contract_payload = {"contract_version": "2.0"}
        else:
            contract_payload = payload["canonical_contract"]
        allowed_ops = _validate_canonical_contract(contract_payload)

        session_payload = import_session_json(
            json.dumps(
                {
                    "graph": payload.get("graph", {}),
                    "expression_graph": payload.get("expression_graph", {}),
                    "tolerance_graph": payload.get("tolerance_graph", {}),
                    "frame_graph": payload.get("frame_graph", {}),
                }
            )
        )
        graph = session_payload.get("graph")
        if isinstance(graph, OperationGraph):
            _assert_graph_is_canonical(graph, allowed_ops=allowed_ops)
        else:
            raise ValueError("Model payload does not contain a valid graph")
        session_payload["geometry_registry"] = list(
            payload.get("geometry_registry", [])
        )
        session_payload["canonical_contract"] = dict(contract_payload)
        session_payload["semantic_entity_registry"] = list(
            payload.get("semantic_entity_registry", [])
        )
        session_payload["sketch_profile_registry"] = list(
            payload.get("sketch_profile_registry", [])
        )
        session_payload["semantic_delta_log"] = list(
            payload.get("semantic_delta_log", [])
        )
        session_payload["topology_delta_log"] = list(
            payload.get("topology_delta_log", [])
        )
        semantic_bindings = list(payload.get("semantic_bindings", []))
        parsed_bindings = [TagBinding.from_dict(item) for item in semantic_bindings]
        graph_binding_list = [
            TagBinding.from_dict(node.params["tag_binding"])
            for node in graph.nodes
            if node.op == "apply_tag_rselection"
            and isinstance(node.params.get("tag_binding"), dict)
        ]
        registry_bindings = {
            binding.binding_id: binding.to_dict() for binding in parsed_bindings
        }
        graph_bindings = {
            binding.binding_id: binding.to_dict() for binding in graph_binding_list
        }
        if (
            len(registry_bindings) != len(parsed_bindings)
            or len(graph_bindings) != len(graph_binding_list)
            or registry_bindings != graph_bindings
        ):
            raise ValueError(
                "model semantic_bindings do not match apply_tag_rselection graph nodes"
            )
        session_payload["semantic_bindings"] = [
            binding.to_dict() for binding in parsed_bindings
        ]
        session_payload["leaf_ids"] = [str(v) for v in payload.get("leaf_ids", [])]
        return session_payload
    except Exception as e:
        raise_harness_error(
            operation="import_model_json",
            what_happened="Failed to import the canonical model JSON payload.",
            possible_causes=[
                "The input string is not valid JSON.",
                f"The payload does not use the expected {MODEL_SCHEMA_VERSION} model schema_version.",
                "One or more nested graph payloads are malformed.",
            ],
            how_to_fix=[
                "Pass a valid JSON string produced by export_model_json().",
                f"Make sure schema_version is exactly {MODEL_SCHEMA_VERSION}.",
                "If you edited the payload manually, validate graph, expression_graph, and frame_graph fields before retrying.",
            ],
            error=e,
        )


def replay_model_json(json_str: str, *, strict: bool = True) -> List[Any]:
    """Replay a model payload using its canonical low-level graph."""

    try:
        payload = import_model_json(json_str)
        graph = payload.get("graph")
        if not isinstance(graph, OperationGraph):
            raise ValueError("Model payload does not contain a replayable graph")

        tolerance_graph = payload.get("tolerance_graph")
        if tolerance_graph is not None:
            tolerance_graph.validate(raise_on_failure=True)

        explicit_leaf_ids = payload.get("leaf_ids")
        return _execute_graph(
            graph,
            cast(Optional[Sequence[str]], explicit_leaf_ids),
            strict=strict,
        )
    except Exception as e:
        raise_harness_error(
            operation="replay_model_json",
            what_happened="Failed to replay the model JSON payload.",
            possible_causes=[
                "The model payload is malformed or missing a replayable graph.",
                "The graph contains an unsupported or invalid node payload.",
                "One of the replayed operations failed due to invalid parameters or missing references.",
            ],
            how_to_fix=[
                "Start from export_model_json() output instead of hand-written payloads when possible.",
                "Make sure the model includes a valid canonical low-level graph section.",
                "If replay fails on a specific operation, inspect that node's params and compare them to the operation signature and help() output.",
            ],
            error=e,
        )


# ---------------------------------------------------------------------------
# Replay executor
# ---------------------------------------------------------------------------

# Registry mapping op names to factory functions.
# Each factory takes (params_dict) -> shape or list of shapes.
_OP_REGISTRY: Dict[str, Any] = {
    "make_cut_rsolid": lambda p: None,  # handled specially below
    "make_union_rsolid": lambda p: None,  # handled specially below
    "make_intersect_rsolid": lambda p: None,  # handled specially below
}

_SKETCH_CONSTRAINT_KIND_BY_OP: Dict[str, str] = {
    "make_constrain_coincident_rsketch": "coincident",
    "make_constrain_point_on_rsketch": "point_on",
    "make_constrain_horizontal_rsketch": "horizontal",
    "make_constrain_vertical_rsketch": "vertical",
    "make_constrain_parallel_rsketch": "parallel",
    "make_constrain_perpendicular_rsketch": "perpendicular",
    "make_constrain_collinear_rsketch": "collinear",
    "make_constrain_tangent_rsketch": "tangent",
    "make_constrain_concentric_rsketch": "concentric",
    "make_constrain_midpoint_rsketch": "midpoint",
    "make_constrain_symmetric_rsketch": "symmetric",
    "make_constrain_equal_length_rsketch": "equal_length",
    "make_constrain_equal_radius_rsketch": "equal_radius",
    "make_constrain_distance_rsketch": "distance",
    "make_constrain_distance_x_rsketch": "distance_x",
    "make_constrain_distance_y_rsketch": "distance_y",
    "make_constrain_length_rsketch": "length",
    "make_constrain_angle_rsketch": "angle",
    "make_constrain_radius_rsketch": "radius",
    "make_constrain_diameter_rsketch": "diameter",
    "make_constrain_fix_rsketch": "fix",
}


def _normalize_output(result: Any) -> List[Any]:
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def _replay_primitive_or_simple(
    ctx: _ReplayContext,
    node,
    params: Dict[str, Any],
) -> Any:
    op_name = node.op
    node_id = node.node_id
    if op_name == "load_brep_region_rsolid":
        ctx.require_params(node_id, op_name, params, ("path", "sha256"))
        safe_path = ops._brep_region_path(str(params["path"]), for_graph=True)
        return ops._load_brep_region_rshape(
            safe_path,
            str(params["sha256"]),
            root_kind="solid",
            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
            replay_root=Path.cwd(),
        )
    if op_name == "load_brep_region_rshell":
        ctx.require_params(node_id, op_name, params, ("path", "sha256"))
        safe_path = ops._brep_region_path(str(params["path"]), for_graph=True)
        return ops._load_brep_region_rshape(
            safe_path,
            str(params["sha256"]),
            root_kind="shell",
            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
            replay_root=Path.cwd(),
        )
    if op_name == "make_sketch_rsketch":
        ctx.require_params(node_id, op_name, params, ("sketch_id",))
        return ops.make_sketch_rsketch(
            params.get("name"),
            plane=params.get("plane", "XY"),
            sketch_id=str(params["sketch_id"]),
        )
    if op_name == "make_point_rvertex":
        ctx.require_params(node_id, op_name, params, ("x", "y", "z"))
        return ops.make_point_rvertex(params["x"], params["y"], params["z"])
    if op_name == "make_line_redge":
        ctx.require_params(node_id, op_name, params, ("start", "end"))
        return ops.make_line_redge(tuple(params["start"]), tuple(params["end"]))
    if op_name == "make_circle_redge":
        ctx.require_params(node_id, op_name, params, ("center", "radius", "normal"))
        return ops.make_circle_redge(
            tuple(params["center"]), params["radius"], tuple(params["normal"])
        )
    if op_name == "make_three_point_arc_redge":
        ctx.require_params(node_id, op_name, params, ("start", "middle", "end"))
        return ops.make_three_point_arc_redge(
            tuple(params["start"]), tuple(params["middle"]), tuple(params["end"])
        )
    if op_name == "make_angle_arc_redge":
        ctx.require_params(
            node_id,
            op_name,
            params,
            ("center", "radius", "start_angle", "end_angle", "normal"),
        )
        return ops.make_angle_arc_redge(
            tuple(params["center"]),
            params["radius"],
            params["start_angle"],
            params["end_angle"],
            tuple(params["normal"]),
        )
    if op_name == "make_spline_redge":
        ctx.require_params(
            node_id,
            op_name,
            params,
            ("control_points", "degree", "knots", "multiplicities"),
        )
        return ops.make_spline_redge(
            control_points=params["control_points"],
            degree=params["degree"],
            knots=params["knots"],
            multiplicities=params["multiplicities"],
            weights=params.get("weights"),
            periodic=bool(params.get("periodic", False)),
        )
    if op_name == "make_interpolated_spline_redge":
        ctx.require_params(
            node_id, op_name, params, ("points", "periodic", "tolerance")
        )
        return ops.make_interpolated_spline_redge(
            points=params["points"],
            periodic=bool(params["periodic"]),
            tolerance=params["tolerance"],
        )
    if op_name == "make_helix_redge":
        ctx.require_params(
            node_id, op_name, params, ("pitch", "height", "radius", "center", "dir")
        )
        return ops.make_helix_redge(
            params["pitch"],
            params["height"],
            params["radius"],
            center=tuple(params["center"]),
            dir=tuple(params["dir"]),
        )
    if op_name == "make_bezier_surface_rface":
        ctx.require_params(node_id, op_name, params, ("control_points",))
        return ops.make_bezier_surface_rface(
            params["control_points"],
            weights=params.get("weights"),
            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
        )
    if op_name == "make_cylindrical_surface_rface":
        ctx.require_params(
            node_id,
            op_name,
            params,
            ("radius", "u_range", "v_range", "origin", "axis", "tolerance"),
        )
        return ops.make_cylindrical_surface_rface(
            params["radius"],
            tuple(params["u_range"]),
            tuple(params["v_range"]),
            origin=tuple(params["origin"]),
            axis=tuple(params["axis"]),
            x_direction=(
                None
                if params.get("x_direction") is None
                else tuple(params["x_direction"])
            ),
            tolerance=float(params["tolerance"]),
            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
        )
    if op_name == "fit_point_grid_rface":
        ctx.require_params(
            node_id,
            op_name,
            params,
            ("points", "tolerance", "degree_min", "degree_max"),
        )
        return ops.fit_point_grid_rface(
            params["points"],
            tolerance=params["tolerance"],
            degree_min=int(params["degree_min"]),
            degree_max=int(params["degree_max"]),
            smoothing=cast(
                Optional[Tuple[float, float, float]], params.get("smoothing")
            ),
            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
        )
    if op_name == "make_box_rsolid":
        ctx.require_params(
            node_id, op_name, params, ("width", "height", "depth", "bottom_face_center")
        )
        return ops.make_box_rsolid(
            params["width"],
            params["height"],
            params["depth"],
            bottom_face_center=tuple(params["bottom_face_center"]),
        )
    if op_name == "make_cylinder_rsolid":
        ctx.require_params(
            node_id, op_name, params, ("radius", "height", "bottom_face_center", "axis")
        )
        return ops.make_cylinder_rsolid(
            params["radius"],
            params["height"],
            bottom_face_center=tuple(params["bottom_face_center"]),
            axis=tuple(params["axis"]),
        )
    if op_name == "make_cone_rsolid":
        ctx.require_params(
            node_id,
            op_name,
            params,
            ("bottom_radius", "top_radius", "height", "bottom_face_center", "axis"),
        )
        return ops.make_cone_rsolid(
            params["bottom_radius"],
            params["height"],
            top_radius=params["top_radius"],
            bottom_face_center=tuple(params["bottom_face_center"]),
            axis=tuple(params["axis"]),
        )
    if op_name == "make_sphere_rsolid":
        ctx.require_params(node_id, op_name, params, ("radius", "center"))
        return ops.make_sphere_rsolid(params["radius"], center=tuple(params["center"]))
    factory = _OP_REGISTRY.get(op_name)
    if factory:
        return factory(params)
    ctx.fail(f"No replay handler registered for graph node '{node_id}' ({op_name})")


def _shape_topo_ref_dict(shape: AnyShape) -> Dict[str, Any]:
    runtime_ref = shape._get_runtime("topo.ref")
    if isinstance(runtime_ref, TopoRef):
        return topo_ref_to_dict(runtime_ref)
    topo_ref = shape.get_metadata("topo_ref")
    return topo_ref if isinstance(topo_ref, dict) else {}


def _distance3(
    a: Optional[Tuple[float, float, float]], b: Optional[Tuple[float, float, float]]
) -> float:
    if a is None or b is None:
        return 1e6
    return math.dist(a, b)


def _tuple3_from_any(value: Any) -> Optional[Tuple[float, float, float]]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    return None


def _shape_kind_token(shape: AnyShape) -> str:
    if isinstance(shape, Vertex):
        return "vertex"
    if isinstance(shape, Edge):
        return "edge"
    if isinstance(shape, Wire):
        return "wire"
    if isinstance(shape, Face):
        return "face"
    if isinstance(shape, Shell):
        return "shell"
    if isinstance(shape, Solid):
        return "solid"
    if isinstance(shape, Compound):
        return "compound"
    return type(shape).__name__.lower()


def _dedupe_shapes(shapes: Sequence[AnyShape]) -> List[AnyShape]:
    result: List[AnyShape] = []
    seen: set[str] = set()
    for shape in shapes:
        topo_id = getattr(shape, "topo_id", None)
        marker = f"{_shape_kind_token(shape)}:{topo_id}" if topo_id else str(id(shape))
        if marker in seen:
            continue
        seen.add(marker)
        result.append(shape)
    return result


def _candidate_shapes_for_geo_selection(source: AnyShape, kind: str) -> List[AnyShape]:
    kind = str(kind).lower()
    if kind == "solid":
        return [source] if isinstance(source, Solid) else []
    if kind == "shell":
        if isinstance(source, Compound):
            return [
                cast(AnyShape, child)
                for child in source.get_children()
                if isinstance(child, Shell)
            ]
        return [source] if isinstance(source, Shell) else []
    if kind == "face":
        if isinstance(source, (Shell, Solid)):
            return list(source._iter_faces())
        return [source] if isinstance(source, Face) else []
    if kind == "edge":
        if hasattr(source, "get_edges"):
            return _dedupe_shapes(cast(Sequence[AnyShape], source._iter_edges()))
        return [source] if isinstance(source, Edge) else []
    if kind == "wire":
        wires: List[AnyShape] = []
        if isinstance(source, Face):
            wires.append(source.get_outer_wire())
            wires.extend(source._iter_inner_wires())
        elif isinstance(source, Solid):
            for face in source._iter_faces():
                wires.append(face.get_outer_wire())
                wires.extend(face._iter_inner_wires())
        elif hasattr(source, "get_children"):
            wires.extend(
                cast(AnyShape, child)
                for child in source.get_children()
                if isinstance(child, Wire)
            )
        elif isinstance(source, Wire):
            wires.append(source)
        return _dedupe_shapes(wires)
    if kind == "vertex":
        vertices: List[AnyShape] = []
        if isinstance(source, Edge):
            vertices.extend(cast(Sequence[AnyShape], source.get_children()))
        elif hasattr(source, "get_edges"):
            for edge in source._iter_edges():
                vertices.extend(cast(Sequence[AnyShape], edge.get_children()))
        elif hasattr(source, "get_children"):
            vertices.extend(
                cast(AnyShape, child)
                for child in source.get_children()
                if isinstance(child, Vertex)
            )
        elif isinstance(source, Vertex):
            vertices.append(source)
        return _dedupe_shapes(vertices)
    return []


def _shape_geom_type(shape: AnyShape) -> Optional[str]:
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.GeomAbs import (
            GeomAbs_BSplineCurve,
            GeomAbs_BSplineSurface,
            GeomAbs_BezierCurve,
            GeomAbs_BezierSurface,
            GeomAbs_Circle,
            GeomAbs_Cone,
            GeomAbs_Cylinder,
            GeomAbs_Line,
            GeomAbs_Plane,
            GeomAbs_Sphere,
            GeomAbs_Torus,
        )

        if isinstance(shape, Edge):
            curve_type = BRepAdaptor_Curve(shape.wrapped).GetType()
            mapping = {
                GeomAbs_Line: "LINE",
                GeomAbs_Circle: "CIRCLE",
                GeomAbs_BSplineCurve: "BSPLINE",
                GeomAbs_BezierCurve: "BEZIER",
            }
            return mapping.get(
                curve_type,
                str(curve_type).replace("GeomAbs_CurveType.GeomAbs_", "").upper(),
            )
        if isinstance(shape, Face):
            surface_type = BRepAdaptor_Surface(shape.wrapped).GetType()
            mapping = {
                GeomAbs_Plane: "PLANE",
                GeomAbs_Cylinder: "CYLINDER",
                GeomAbs_Cone: "CONE",
                GeomAbs_Sphere: "SPHERE",
                GeomAbs_Torus: "TORUS",
                GeomAbs_BSplineSurface: "BSPLINE",
                GeomAbs_BezierSurface: "BEZIER",
            }
            return mapping.get(
                surface_type,
                str(surface_type).replace("GeomAbs_SurfaceType.GeomAbs_", "").upper(),
            )
    except Exception:
        return None
    return None


def _bbox_score(shape: AnyShape, selector: Dict[str, Any]) -> float:
    bbox = selector.get("bbox")
    if not isinstance(bbox, dict):
        return 0.0
    try:
        actual = bounding_box(shape.wrapped)
        expected_min = _tuple3_from_any(bbox.get("min"))
        expected_max = _tuple3_from_any(bbox.get("max"))
        if expected_min is None or expected_max is None:
            return 1e6
        return _distance3(
            (actual.xmin, actual.ymin, actual.zmin), expected_min
        ) + _distance3((actual.xmax, actual.ymax, actual.zmax), expected_max)
    except Exception:
        return 1e6


def _geo_selector_score(
    shape: AnyShape,
    selector: Dict[str, Any],
    *,
    candidate_index: Optional[int] = None,
) -> float:
    if _shape_kind_token(shape) != str(selector.get("kind", "")).lower():
        return 1e12

    score = _bbox_score(shape, selector) * 10.0
    expected_geom_type = selector.get("geom_type")
    if expected_geom_type is not None:
        actual_geom_type = _shape_geom_type(shape)
        if actual_geom_type is not None and actual_geom_type != str(expected_geom_type):
            score += 1e6

    if isinstance(shape, Vertex):
        score += (
            _distance3(
                tuple(shape.get_coordinates()),
                _tuple3_from_any(selector.get("coordinates")),
            )
            * 10.0
        )
    elif isinstance(shape, Edge):
        if "length" in selector:
            score += abs(float(shape.get_length()) - float(selector["length"])) * 10.0
        center = shape.get_center()
        score += (
            _distance3(
                (float(center.x), float(center.y), float(center.z)),
                _tuple3_from_any(selector.get("center")),
            )
            * 10.0
        )
        try:
            start = cast(
                Tuple[float, float, float],
                tuple(
                    float(value) for value in shape.get_start_vertex().get_coordinates()
                ),
            )
            end = cast(
                Tuple[float, float, float],
                tuple(
                    float(value) for value in shape.get_end_vertex().get_coordinates()
                ),
            )
            expected_start = _tuple3_from_any(selector.get("start"))
            expected_end = _tuple3_from_any(selector.get("end"))
            if expected_start is not None and expected_end is not None:
                direct = _distance3(start, expected_start) + _distance3(
                    end, expected_end
                )
                reverse = _distance3(start, expected_end) + _distance3(
                    end, expected_start
                )
                score += min(direct, reverse)
        except Exception:
            pass
    elif isinstance(shape, Wire):
        if "edge_count" in selector:
            score += abs(len(shape._iter_edges()) - int(selector["edge_count"])) * 10.0
        if "closed" in selector and bool(shape.is_closed()) != bool(selector["closed"]):
            score += 10.0
    elif isinstance(shape, Face):
        if "area" in selector:
            score += abs(float(shape.get_area()) - float(selector["area"]))
        center = shape.get_center()
        score += (
            _distance3(
                (float(center.x), float(center.y), float(center.z)),
                _tuple3_from_any(selector.get("center")),
            )
            * 10.0
        )
        normal = shape.get_normal_at()
        score += (
            _distance3(
                (float(normal.x), float(normal.y), float(normal.z)),
                _tuple3_from_any(selector.get("normal")),
            )
            * 5.0
        )
        if "edge_count" in selector:
            score += abs(len(shape._iter_edges()) - int(selector["edge_count"])) * 10.0
        if "inner_wire_count" in selector:
            score += (
                abs(len(shape._iter_inner_wires()) - int(selector["inner_wire_count"]))
                * 10.0
            )
    elif isinstance(shape, Shell):
        if "face_count" in selector:
            score += abs(len(shape._iter_faces()) - int(selector["face_count"])) * 10.0
    elif isinstance(shape, Solid):
        if "volume" in selector:
            score += abs(float(shape.get_volume()) - float(selector["volume"]))
    return score


def _resolve_shape_from_geo_selector(
    source: AnyShape, selector: Dict[str, Any]
) -> AnyShape:
    kind = str(selector.get("kind") or selector.get("target_kind") or "").lower()
    candidates = _candidate_shapes_for_geo_selection(source, kind)
    if not candidates:
        raise ValueError(f"geo selector found no {kind} candidates in source")

    brep_region_ref = selector.get("brep_region_ref")
    if isinstance(brep_region_ref, dict):
        expected = (
            str(brep_region_ref.get("artifact_sha256", "")),
            str(brep_region_ref.get("source_face_id", "")),
        )
        candidates = [
            candidate
            for candidate in candidates
            if isinstance(candidate, Face)
            and isinstance(candidate.get_metadata("provenance"), dict)
            and (
                str(candidate.get_metadata("provenance").get("artifact_sha256", "")),
                str(candidate.get_metadata("provenance").get("source_face_id", "")),
            )
            == expected
        ]
        if len(candidates) != 1:
            raise ValueError(
                "BREP region face selector did not resolve exactly one provenance identity"
            )

    ranked = sorted(
        enumerate(candidates),
        key=lambda item: _geo_selector_score(
            item[1], selector, candidate_index=int(item[0])
        ),
    )
    best_index, best_shape = ranked[0]
    best_score = _geo_selector_score(best_shape, selector, candidate_index=best_index)
    if best_score > 1e-4:
        raise ValueError(
            f"geo selector did not match a stable {kind} candidate; best score={best_score:.6g}"
        )
    return best_shape


def _edge_hint_score(edge: Edge, hint: Dict[str, Any]) -> float:
    score = 0.0
    if "length" in hint:
        score += abs(float(edge.get_length()) - float(hint["length"])) * 10.0

    start: Optional[Tuple[float, float, float]] = None
    end: Optional[Tuple[float, float, float]] = None
    try:
        start = cast(
            Tuple[float, float, float],
            tuple(float(v) for v in edge.get_start_vertex().get_coordinates()),
        )
        end = cast(
            Tuple[float, float, float],
            tuple(float(v) for v in edge.get_end_vertex().get_coordinates()),
        )
    except Exception:
        pass

    hint_start = hint.get("start")
    hint_end = hint.get("end")
    hint_start_tuple = _tuple3_from_any(hint_start)
    hint_end_tuple = _tuple3_from_any(hint_end)
    if (
        start is not None
        and end is not None
        and hint_start_tuple is not None
        and hint_end_tuple is not None
    ):
        direct = _distance3(start, hint_start_tuple) + _distance3(end, hint_end_tuple)
        reverse = _distance3(start, hint_end_tuple) + _distance3(end, hint_start_tuple)
        score += min(direct, reverse)
    elif hint.get("center") is not None:
        center = edge.get_center()
        center_tuple = (float(center.x), float(center.y), float(center.z))
        score += _distance3(center_tuple, _tuple3_from_any(hint["center"]))

    if "tags" in hint:
        hint_tags = set(hint["tags"])
        common = len(hint_tags & set(edge._list_tags()))
        score -= common * 0.1
    return score


def _face_hint_score(face: Face, hint: Dict[str, Any]) -> float:
    score = 0.0
    if "area" in hint:
        score += abs(float(face.get_area()) - float(hint["area"]))

    center = face.get_center()
    center_tuple = (float(center.x), float(center.y), float(center.z))
    hint_center = hint.get("center")
    hint_center_tuple = _tuple3_from_any(hint_center)
    if hint_center_tuple is not None:
        score += _distance3(center_tuple, hint_center_tuple) * 10.0

    hint_normal = hint.get("normal")
    hint_normal_tuple = _tuple3_from_any(hint_normal)
    if hint_normal_tuple is not None:
        normal = face.get_normal_at()
        normal_tuple = (float(normal.x), float(normal.y), float(normal.z))
        score += _distance3(normal_tuple, hint_normal_tuple) * 5.0

    if "tags" in hint:
        hint_tags = set(hint["tags"])
        common = len(hint_tags & set(face._list_tags()))
        score -= common * 0.1
    return score


def _resolve_edges_from_selector_hints(
    solid: Solid, refs: Sequence[Dict[str, Any]]
) -> List[Edge]:
    edges = solid._iter_edges()
    remaining = list(edges)
    resolved: List[Edge] = []
    for ref_dict in refs:
        hint = ref_dict.get("selector_hint")
        if not isinstance(hint, dict) or not remaining:
            continue
        best = min(
            remaining,
            key=lambda edge: _edge_hint_score(edge, cast(Dict[str, Any], hint)),
        )
        resolved.append(best)
        remaining.remove(best)
    return resolved


def _resolve_faces_from_selector_hints(
    solid: Solid, refs: Sequence[Dict[str, Any]]
) -> List[Face]:
    faces = solid._iter_faces()
    remaining = list(faces)
    resolved: List[Face] = []
    for ref_dict in refs:
        hint = ref_dict.get("selector_hint")
        if not isinstance(hint, dict) or not remaining:
            continue
        best = min(
            remaining,
            key=lambda face: _face_hint_score(face, cast(Dict[str, Any], hint)),
        )
        resolved.append(best)
        remaining.remove(best)
    return resolved


def _resolve_edges_from_refs(
    solid: Solid, refs: Sequence[Dict[str, Any]]
) -> List[Edge]:
    if not refs:
        return []
    edge_map = {
        _shape_topo_ref_dict(edge).get("topo_id"): edge
        for edge in solid._iter_edges()
        if _shape_topo_ref_dict(edge)
    }
    resolved: List[Edge] = []
    for ref_dict in refs:
        ref = topo_ref_from_dict(ref_dict)
        edge = edge_map.get(ref.topo_id)
        if edge is not None:
            resolved.append(edge)
    return resolved


def _resolve_faces_from_refs(
    solid: Solid, refs: Sequence[Dict[str, Any]]
) -> List[Face]:
    if not refs:
        return []
    face_map = {
        _shape_topo_ref_dict(face).get("topo_id"): face
        for face in solid._iter_faces()
        if _shape_topo_ref_dict(face)
    }
    resolved: List[Face] = []
    for ref_dict in refs:
        ref = topo_ref_from_dict(ref_dict)
        face = face_map.get(ref.topo_id)
        if face is not None:
            resolved.append(face)
    return resolved


def _resolve_edges_from_indices(solid: Solid, indices: Sequence[int]) -> List[Edge]:
    edges = solid._iter_edges()
    return [edges[idx] for idx in indices if 0 <= idx < len(edges)]


def _resolve_faces_from_indices(solid: Solid, indices: Sequence[int]) -> List[Face]:
    faces = solid._iter_faces()
    return [faces[idx] for idx in indices if 0 <= idx < len(faces)]


def _resolve_selector_scope(
    selector_payload: Dict[str, Any],
    default_scope: Solid,
    outputs: Dict[str, List[AnyShape]],
) -> Any:
    source_node_id = selector_payload.get("source_node_id")
    if source_node_id is None:
        return default_scope
    source_outputs = outputs.get(str(source_node_id), [])
    source_output_slot = int(selector_payload.get("source_output_slot", 0))
    if source_output_slot < 0 or source_output_slot >= len(source_outputs):
        raise ValueError(
            f"SelectionSpec source {source_node_id}:{source_output_slot} has no replay output"
        )
    return source_outputs[source_output_slot]


def _resolve_feature_selection(
    ctx: _ReplayContext,
    *,
    node,
    solid: Solid,
    params: Dict[str, Any],
    kind: str,
    outputs: Dict[str, List[AnyShape]],
) -> List[Any]:
    if kind == "edge":
        refs_param = "selected_edges"
        indices_param = "selected_edge_indices"
        node_ids_param = "selected_edge_node_ids"
        resolve_refs = _resolve_edges_from_refs
        resolve_indices = _resolve_edges_from_indices
        resolve_hints = _resolve_edges_from_selector_hints
    elif kind == "face":
        refs_param = "selected_faces"
        indices_param = "selected_face_indices"
        node_ids_param = "selected_face_node_ids"
        resolve_refs = _resolve_faces_from_refs
        resolve_indices = _resolve_faces_from_indices
        resolve_hints = _resolve_faces_from_selector_hints
    else:
        raise ValueError(f"unsupported selection kind: {kind}")

    selected_refs = cast(Sequence[Dict[str, Any]], params.get(refs_param, []))
    selection_node_ids = [str(node_id) for node_id in params.get(node_ids_param, [])]
    if selection_node_ids:
        resolved_from_nodes: List[AnyShape] = []
        for node_id in selection_node_ids:
            node_outputs = outputs.get(node_id, [])
            if not node_outputs:
                if ctx.strict:
                    ctx.fail(
                        f"Graph node '{node.node_id}' ({node.op}) selection node '{node_id}' has no replay output"
                    )
                continue
            resolved_from_nodes.extend(node_outputs)
        if resolved_from_nodes:
            return list(resolved_from_nodes)

    selection_query = params.get("selection_query")
    if isinstance(selection_query, dict):
        scope = _resolve_selector_scope(selection_query, solid, outputs)
        resolved = list(selector_from_dict(selection_query).resolve(scope))
        return resolved

    if selected_refs:
        resolved = resolve_refs(solid, selected_refs)
        if len(resolved) == len(selected_refs):
            return list(resolved)

    indices = cast(Sequence[int], params.get(indices_param, []))
    if indices:
        resolved = resolve_indices(solid, indices)
        if len(resolved) == len(indices):
            return list(resolved)

    if selected_refs:
        resolved = resolve_hints(solid, selected_refs)
        if len(resolved) == len(selected_refs):
            return list(resolved)

    return []


class _ReplayContext:
    def __init__(self, *, strict: bool) -> None:
        self.strict = bool(strict)

    def fail(self, message: str) -> None:
        raise ValueError(message)

    def require_params(
        self, node_id: str, op_name: str, params: Dict[str, Any], names: Sequence[str]
    ) -> None:
        missing = [name for name in names if name not in params]
        if missing:
            self.fail(
                f"Graph node '{node_id}' ({op_name}) is missing required parameter(s): "
                + ", ".join(missing)
            )


def _param(
    ctx: _ReplayContext,
    node_id: str,
    op_name: str,
    params: Dict[str, Any],
    name: str,
    default: Any = None,
) -> Any:
    if name in params:
        return params[name]
    if ctx.strict:
        ctx.fail(
            f"Graph node '{node_id}' ({op_name}) is missing required parameter '{name}'"
        )
    return default


def _input_outputs(
    ctx: _ReplayContext,
    outputs: Dict[str, List[Any]],
    node: Any,
    index: int,
) -> List[Any]:
    if len(node.inputs) <= index:
        if not ctx.strict:
            return []
        ctx.fail(
            f"Graph node '{node.node_id}' ({node.op}) is missing required input #{index}"
        )
    input_node = node.inputs[index]
    result = outputs.get(input_node.node_id)
    if not result:
        if not ctx.strict:
            return []
        ctx.fail(
            f"Graph node '{node.node_id}' ({node.op}) input '{input_node.node_id}' has no replay output"
        )
    return result


def _all_input_outputs(
    ctx: _ReplayContext,
    outputs: Dict[str, List[Any]],
    node: Any,
) -> List[Any]:
    result: List[Any] = []
    for input_node in node.inputs:
        input_outputs = outputs.get(input_node.node_id)
        if not input_outputs:
            if not ctx.strict:
                continue
            ctx.fail(
                f"Graph node '{node.node_id}' ({node.op}) input '{input_node.node_id}' has no replay output"
            )
        result.extend(input_outputs)
    return result


def _ordered_input_shapes(
    ctx: _ReplayContext,
    graph: OperationGraph,
    outputs: Dict[str, List[Any]],
    node: Any,
    params: Dict[str, Any],
) -> List[AnyShape]:
    raw_refs = params.get("input_refs")
    if not isinstance(raw_refs, list):
        if ctx.strict:
            ctx.fail(
                f"Graph node '{node.node_id}' ({node.op}) is missing ordered input_refs"
            )
        return cast(List[AnyShape], _all_input_outputs(ctx, outputs, node))
    direct_input_ids = {input_node.node_id for input_node in node.inputs}
    resolved: List[AnyShape] = []
    for index, raw_ref in enumerate(raw_refs):
        if not isinstance(raw_ref, dict):
            ctx.fail(
                f"Graph node '{node.node_id}' ({node.op}) input_refs[{index}] must be an object"
            )
        ref_graph_id = str(raw_ref.get("graph_id", ""))
        ref_node_id = str(raw_ref.get("node_id", ""))
        ref_slot = int(raw_ref.get("output_slot", 0))
        ref_kind = str(raw_ref.get("kind", "")).lower().split(".", 1)[-1]
        if ref_graph_id != graph.graph_id:
            ctx.fail(
                f"Graph node '{node.node_id}' ({node.op}) input_refs[{index}] belongs to foreign graph '{ref_graph_id}'"
            )
        if ref_node_id in direct_input_ids:
            candidates = outputs.get(ref_node_id, [])
            if ref_slot < 0 or ref_slot >= len(candidates):
                ctx.fail(
                    f"Graph node '{node.node_id}' ({node.op}) input_refs[{index}] references missing output slot {ref_slot}"
                )
            shape = candidates[ref_slot]
        else:
            semantic_input_ids = [
                direct_input_id
                for direct_input_id in direct_input_ids
                if _is_upstream_node(graph, direct_input_id, ref_node_id)
            ]
            matches = []
            for semantic_input_id in semantic_input_ids:
                for candidate in outputs.get(semantic_input_id, []):
                    if not isinstance(
                        candidate, (Vertex, Edge, Wire, Face, Shell, Solid, Compound)
                    ):
                        continue
                    topo_ref = _shape_topo_ref_dict(candidate)
                    candidate_kind = str(
                        topo_ref.get("kind", _shape_kind_token(candidate))
                    ).lower().split(".", 1)[-1]
                    if (
                        str(topo_ref.get("graph_id", "")) == ref_graph_id
                        and str(topo_ref.get("node_id", "")) == ref_node_id
                        and int(topo_ref.get("output_slot", 0)) == ref_slot
                        and (not ref_kind or candidate_kind == ref_kind)
                    ):
                        matches.append(candidate)
            if len(matches) != 1:
                ctx.fail(
                    f"Graph node '{node.node_id}' ({node.op}) input_refs[{index}] "
                    "does not resolve through exactly one direct semantic input"
                )
            shape = matches[0]
        if not isinstance(shape, (Vertex, Edge, Wire, Face, Shell, Solid, Compound)):
            ctx.fail(
                f"Graph node '{node.node_id}' ({node.op}) input_refs[{index}] does not resolve to geometry"
            )
        if ref_kind and _shape_kind_token(shape) != ref_kind:
            ctx.fail(
                f"Graph node '{node.node_id}' ({node.op}) input_refs[{index}] kind does not match replay output"
            )
        resolved.append(cast(AnyShape, shape))
    return resolved


def _semantic_view_origin(
    ctx: _ReplayContext,
    graph: OperationGraph,
    consumer: Any,
    semantic_node: Any,
) -> tuple[str, int]:
    current = semantic_node
    seen: set[str] = set()
    while current.op == "apply_tag_rselection":
        if current.node_id in seen:
            ctx.fail(
                f"Graph node '{consumer.node_id}' ({consumer.op}) has a cyclic semantic input chain"
            )
        seen.add(current.node_id)
        raw_binding = current.params.get("tag_binding")
        if not isinstance(raw_binding, dict):
            ctx.fail(
                f"Graph node '{consumer.node_id}' ({consumer.op}) direct semantic input has no tag binding"
            )
        binding = TagBinding.from_dict(raw_binding)
        scope_node_id = binding.scope.node_id
        if scope_node_id is None:
            ctx.fail(
                f"Graph node '{consumer.node_id}' ({consumer.op}) semantic input scope has no node_id"
            )
        scope_node = graph.get_node(scope_node_id)
        if scope_node is None:
            ctx.fail(
                f"Graph node '{consumer.node_id}' ({consumer.op}) semantic input scope references an unknown node"
            )
        if scope_node.op != "apply_tag_rselection":
            return scope_node_id, binding.scope.output_slot
        if binding.scope.output_slot != 0:
            ctx.fail(
                f"Graph node '{consumer.node_id}' ({consumer.op}) semantic view references an invalid semantic output slot"
            )
        current = scope_node
    ctx.fail(
        f"Graph node '{consumer.node_id}' ({consumer.op}) direct semantic input is not a semantic view"
    )


def _resolve_tag_binding_targets(
    scope: AnyShape, binding: TagBinding
) -> List[AnyShape]:
    if binding.target.kind == TagTargetKind.SCOPE_ROOT:
        return [scope]
    if binding.target.kind == TagTargetKind.SELECTION_QUERY:
        if binding.target.selector is None:
            raise ValueError("selection_query tag target is missing its selector")
        return cast(
            List[AnyShape],
            selector_from_dict(binding.target.selector).resolve(scope),
        )
    if binding.target.kind != TagTargetKind.EXPLICIT_REFS:
        raise ValueError(
            f"tag target kind '{binding.target.kind.value}' is not replayable"
        )

    resolved: List[AnyShape] = []
    for ref in binding.target.refs:
        topo_id = str(ref.get("topo_id", ""))
        kind = str(ref.get("kind", "")).lower()
        if not topo_id or not kind:
            raise ValueError("explicit tag target refs require kind and topo_id")
        if kind.startswith("topokind."):
            kind = kind.split(".", 1)[1]
        wrappers = [
            wrapper
            for entity in scope._topology_cache.entities()
            if entity.kind.lower() == kind
            for wrapper in entity.wrappers
            if isinstance(wrapper, (Vertex, Edge, Wire, Face, Shell, Solid, Compound))
            and (
                wrapper.topo_id == topo_id
                or str(_shape_topo_ref_dict(wrapper).get("topo_id", "")) == topo_id
            )
        ]
        unique = {item.topo_id: item for item in wrappers}
        if len(unique) != 1:
            raise ValueError(
                f"explicit tag target '{kind}:{topo_id}' does not resolve uniquely"
            )
        resolved.append(cast(AnyShape, next(iter(unique.values()))))
    return resolved


def _validate_tag_binding_evidence(
    binding: TagBinding,
    selected: Sequence[AnyShape],
) -> None:
    selected_count = binding.evidence.data.get("selected_count")
    if selected_count is not None and int(selected_count) != len(selected):
        raise ValueError(
            f"tag assignment expected {int(selected_count)} selected target(s), got {len(selected)}"
        )
    expected_refs = binding.evidence.data.get("selected_refs")
    if not isinstance(expected_refs, list):
        return
    expected = {
        (str(ref.get("kind", "")).lower(), str(ref.get("topo_id", "")))
        for ref in expected_refs
        if isinstance(ref, dict)
    }
    actual = set()
    for item in selected:
        topo_ref = _shape_topo_ref_dict(item)
        actual.add(
            (
                str(topo_ref.get("kind", item.__class__.__name__)).lower(),
                str(topo_ref.get("topo_id", item.topo_id)),
            )
        )
    if expected and expected != actual:
        raise ValueError(
            "tag assignment target evidence drifted during replay: "
            f"expected={sorted(expected)}, actual={sorted(actual)}"
        )


def _is_upstream_node(graph: OperationGraph, node_id: str, source_node_id: str) -> bool:
    pending = list(graph.upstream_nodes(node_id))
    seen = set()
    while pending:
        current = pending.pop()
        if current == source_node_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(graph.upstream_nodes(current))
    return False


def _canonical_shape_ref(shape: AnyShape) -> Tuple[str, str, int, str, str]:
    ref = _shape_topo_ref_dict(shape)
    return (
        str(ref.get("graph_id", "")),
        str(ref.get("node_id", "")),
        int(ref.get("output_slot", 0)),
        str(ref.get("kind", shape.__class__.__name__)).lower(),
        str(ref.get("topo_id", shape.topo_id)),
    )


def _canonical_topo_ref(ref: TopoRef) -> Tuple[str, str, int, str, str]:
    return (
        ref.graph_id,
        ref.node_id,
        ref.output_slot,
        ref.kind.name.lower(),
        ref.topo_id,
    )


def _validate_replayed_topology_roles(
    graph: OperationGraph,
    node: Any,
    result_list: Sequence[Any],
) -> None:
    if node.topo_delta is None or not node.topo_delta.roles:
        return

    role_specs = dict(ops._OPERATION_OUTPUT_ROLE_CARDINALITY.get(node.op, ()))
    serialized: Dict[str, set[Tuple[str, str, int, str, str]]] = {}
    for entry in node.topo_delta.roles:
        if entry.role not in role_specs:
            raise ValueError(
                f"Graph node '{node.node_id}' ({node.op}) contains unsupported output role '{entry.role}'"
            )
        if entry.ref.graph_id != graph.graph_id or entry.ref.node_id != node.node_id:
            raise ValueError(
                f"Graph node '{node.node_id}' ({node.op}) output role '{entry.role}' has foreign result ownership"
            )
        if entry.ref.output_slot >= len(result_list):
            raise ValueError(
                f"Graph node '{node.node_id}' ({node.op}) output role '{entry.role}' references missing output slot {entry.ref.output_slot}"
            )
        if (
            str(entry.metadata.get("coverage", "complete")).lower() != "complete"
            or str(entry.metadata.get("status", "proven")).lower() != "proven"
        ):
            continue
        serialized.setdefault(entry.role, set()).add(_canonical_topo_ref(entry.ref))

    runtime: Dict[str, set[Tuple[str, str, int, str, str]]] = {}
    for output in result_list:
        if not isinstance(output, (Solid, Compound, Face, Shell)):
            continue
        candidates: List[AnyShape] = []
        if hasattr(output, "get_faces"):
            candidates.extend(output._iter_faces())
        if hasattr(output, "get_edges"):
            candidates.extend(output._iter_edges())
        if hasattr(output, "get_wires"):
            candidates.extend(output._iter_wires())
        for candidate in candidates:
            track = candidate.get_metadata("track")
            if not isinstance(track, dict):
                continue
            for role in track.get("result_roles", ()):
                role_name = str(role).strip().lower()
                if role_name in role_specs:
                    runtime.setdefault(role_name, set()).add(
                        _canonical_shape_ref(candidate)
                    )

    if serialized != runtime:
        raise ValueError(
            f"Graph node '{node.node_id}' ({node.op}) topology output-role evidence drifted during replay"
        )


def _validate_operation_output_evidence(
    graph: OperationGraph,
    node: Any,
    binding: TagBinding,
    selected: Sequence[AnyShape],
    outputs: Dict[str, List[Any]],
) -> None:
    raw = binding.evidence.data.get("operation_output_role")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ValueError("operation_output_role evidence must be an object")

    source_node_id = str(raw.get("source_node_id", ""))
    source_output_slot = int(raw.get("source_output_slot", 0))
    operation = str(raw.get("operation", ""))
    role = str(raw.get("role", "")).strip().lower()
    cardinality = str(raw.get("cardinality", ""))
    if not source_node_id or not operation or not role:
        raise ValueError("operation_output_role evidence is incomplete")
    if not _is_upstream_node(graph, node.node_id, source_node_id):
        raise ValueError(
            f"operation output role source '{source_node_id}' is not upstream of '{node.node_id}'"
        )

    source_node = graph.get_node(source_node_id)
    if source_node is None or source_node.op != operation:
        raise ValueError(
            f"operation output role source '{source_node_id}' does not match operation '{operation}'"
        )
    role_specs = dict(ops._OPERATION_OUTPUT_ROLE_CARDINALITY.get(operation, ()))
    if role not in role_specs or role_specs[role] != cardinality:
        raise ValueError(
            f"operation output role '{role}' with cardinality '{cardinality}' is unsupported for '{operation}'"
        )
    if source_node.topo_delta is None:
        raise ValueError(
            f"operation output role source '{source_node_id}' has no topology-role evidence"
        )

    serialized_refs = {
        _canonical_topo_ref(entry.ref)
        for entry in source_node.topo_delta.roles
        if entry.role == role
        and str(entry.metadata.get("coverage", "complete")).lower() == "complete"
        and str(entry.metadata.get("status", "proven")).lower() == "proven"
    }
    serialized_kinds = {ref[3] for ref in serialized_refs}
    if len(serialized_kinds) != 1:
        raise ValueError(
            f"operation output role '{role}' does not resolve to one topology kind"
        )
    source_outputs = outputs.get(source_node_id, [])
    if source_output_slot >= len(source_outputs):
        raise ValueError(
            f"operation output role source '{source_node_id}:{source_output_slot}' has no replay output"
        )
    source = cast(AnyShape, source_outputs[source_output_slot])
    target_kind = next(iter(serialized_kinds))
    if target_kind == "face":
        runtime_items = source._iter_faces()
    elif target_kind == "edge":
        runtime_items = source._iter_edges()
    elif target_kind == "wire":
        runtime_items = source._iter_wires()
    elif target_kind == "vertex":
        runtime_items = source._iter_vertices()
    else:
        raise ValueError(
            f"operation output role '{role}' uses unsupported topology kind '{target_kind}'"
        )
    runtime_candidates = [item for item in runtime_items if output_role(role)(item)]
    runtime_refs = {_canonical_shape_ref(face) for face in runtime_candidates}
    selected_refs = {_canonical_shape_ref(item) for item in selected}

    if cardinality == "one" and len(runtime_refs) != 1:
        raise ValueError(
            f"operation output role '{role}' expected exactly one replay result, got {len(runtime_refs)}"
        )
    if cardinality == "many" and not runtime_refs:
        raise ValueError(f"operation output role '{role}' resolved no replay results")
    if serialized_refs != runtime_refs:
        raise ValueError(
            f"operation output role '{role}' topology evidence drifted during replay"
        )
    if selected_refs != runtime_refs:
        raise ValueError(
            f"operation output role '{role}' binding targets do not match its proven results"
        )


def _execute_graph(
    graph: OperationGraph,
    leaf_node_ids: Optional[Sequence[str]] = None,
    *,
    strict: bool = True,
    external_definitions: Mapping[str, Part | Assembly] | None = None,
) -> List[Any]:
    ctx = _ReplayContext(strict=strict)
    if graph.node_count == 0:
        return []

    topo_order = graph.topological_order()

    # Store per-node outputs
    outputs: Dict[str, List[Any]] = {}
    materials_by_id: Dict[str, Material] = {}

    def _store_outputs(node, result: Any) -> None:
        result_list = _normalize_output(result)
        if ctx.strict and len(result_list) != node.output_count:
            ctx.fail(
                f"Graph node '{node.node_id}' ({node.op}) declared {node.output_count} output(s), replay produced {len(result_list)}"
            )
        for idx, output in enumerate(result_list):
            attach_graph_node(
                output,
                node,
                output_slot=idx,
                graph_id=graph.graph_id,
            )
        if ctx.strict:
            _validate_replayed_topology_roles(graph, node, result_list)
        outputs[node.node_id] = result_list

    def _store_semantic_outputs(node, result: Any) -> None:
        result_list = _normalize_output(result)
        if ctx.strict and len(result_list) != node.output_count:
            ctx.fail(
                f"Graph node '{node.node_id}' ({node.op}) declared {node.output_count} output(s), replay produced {len(result_list)}"
            )
        for idx, output in enumerate(result_list):
            attach_semantic_graph_node(
                output,
                node,
                output_slot=idx,
                graph_id=graph.graph_id,
            )
        outputs[node.node_id] = result_list

    with suspend_graph_recording():
        for node in topo_order:
            op_name = node.op
            params = node.params
            context_manager = (
                use_coordinate_system(node.context)
                if isinstance(node.context, dict)
                else nullcontext()
            )

            try:
                with context_manager:
                    if op_name == "reference_definition":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            (
                                "definition_kind",
                                "definition_id",
                                "revision",
                                "content_hash",
                            ),
                        )
                        definition_id = str(params["definition_id"])
                        value = (external_definitions or {}).get(definition_id)
                        if value is None:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) cannot resolve definition {definition_id!r}"
                            )
                        expected_kind = (
                            "single_solid" if isinstance(value, Part) else "assembly"
                        )
                        actual_id = (
                            value.part_id
                            if isinstance(value, Part)
                            else value.assembly_id
                        )
                        if (
                            actual_id != definition_id
                            or expected_kind != params["definition_kind"]
                            or value._get_runtime("definition.content_hash")
                            != params["content_hash"]
                        ):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) resolved definition identity differs"
                            )
                        _store_semantic_outputs(node, value)
                        continue

                    if op_name == "evaluate_assembly_definition":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            (
                                "solver_profile",
                                "component_placements",
                                "constraint_report",
                            ),
                        )
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        if assembly_outputs:
                            authored = cast(Assembly, assembly_outputs[0])
                            placements = params["component_placements"]
                            if not isinstance(placements, list):
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) component_placements must be an array"
                                )
                            by_id: dict[str, Mapping[str, Any]] = {}
                            for item in placements:
                                if not isinstance(item, dict) or set(item) != {
                                    "instance_id",
                                    "placement",
                                }:
                                    ctx.fail(
                                        f"Graph node '{node.node_id}' ({op_name}) has invalid placement record"
                                    )
                                instance_id = str(item["instance_id"])
                                if instance_id in by_id or not isinstance(
                                    item["placement"], Mapping
                                ):
                                    ctx.fail(
                                        f"Graph node '{node.node_id}' ({op_name}) has invalid placement record"
                                    )
                                by_id[instance_id] = item["placement"]
                            if set(by_id) != set(authored.component_ids()):
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) placement ids differ from the assembly"
                                )
                            authored_placements = authored._get_runtime(
                                "assembly.authored_component_placements"
                            )
                            if authored_placements is None:
                                authored_placements = {
                                    component.component_id: component.placement.to_dict()
                                    for component in authored.components
                                }
                            occurrence_placements = params.get("occurrence_placements")
                            if occurrence_placements is not None:
                                if not isinstance(occurrence_placements, list):
                                    ctx.fail(
                                        f"Graph node '{node.node_id}' ({op_name}) occurrence_placements must be an array"
                                    )
                                result = _restore_component_occurrence_placements(
                                    authored,
                                    occurrence_placements,
                                )
                                if any(
                                    placement_ticks(
                                        result.get_component(component_id).placement
                                    )
                                    != placement_ticks(by_id[component_id])
                                    for component_id in authored.component_ids()
                                ):
                                    ctx.fail(
                                        f"Graph node '{node.node_id}' ({op_name}) top-level and occurrence placements differ"
                                    )
                            else:
                                result = authored
                                for component_id in authored.component_ids():
                                    result = result.with_component_placement(
                                        component_id,
                                        Placement(**dict(by_id[component_id])),
                                    )
                            report = ops.inspect_assembly_constraints_rconstraintreport(
                                assembly=result
                            )
                            if not constraint_reports_match(
                                report.to_dict(), params["constraint_report"]
                            ):
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) residual report differs"
                                )
                            result._set_runtime(
                                "assembly.authored_component_placements",
                                authored_placements,
                            )
                            _store_semantic_outputs(node, result)
                        continue
                    if op_name == "apply_tag_rselection":
                        ctx.require_params(
                            node.node_id, op_name, params, ("tag_binding",)
                        )
                        raw_binding = params["tag_binding"]
                        if not isinstance(raw_binding, dict):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) tag_binding must be an object"
                            )
                        binding = TagBinding.from_dict(raw_binding)
                        if ctx.strict and binding.producer.node_id != node.node_id:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) does not match binding producer '{binding.producer.node_id}'"
                            )
                        scope_node_id = binding.scope.node_id
                        if scope_node_id is None:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) binding scope has no node_id"
                            )
                        if ctx.strict and scope_node_id not in {
                            item.node_id for item in node.inputs
                        }:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) binding scope '{scope_node_id}' is not an input"
                            )
                        scope_outputs = outputs.get(str(scope_node_id), [])
                        output_slot = binding.scope.output_slot
                        if output_slot >= len(scope_outputs):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) binding scope '{scope_node_id}:{output_slot}' has no replay output"
                            )
                        scope = cast(AnyShape, scope_outputs[output_slot])
                        result = clone_semantic_shape_view(scope)
                        selected = _resolve_tag_binding_targets(result, binding)
                        selected_by_id = {item.topo_id: item for item in selected}
                        if len(selected_by_id) != len(selected):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) resolved duplicate tag targets"
                            )
                        selected = list(selected_by_id.values())
                        if not selected:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) resolved no tag targets"
                            )
                        if ctx.strict:
                            _validate_tag_binding_evidence(binding, selected)
                            _validate_operation_output_evidence(
                                graph, node, binding, selected, outputs
                            )
                        for selected_shape in selected:
                            selected_shape._add_tag_binding(binding)
                        _store_semantic_outputs(node, result)
                        continue

                    if op_name == "add_point_rsketch":
                        ctx.require_params(
                            node.node_id, op_name, params, ("point_id", "x", "y")
                        )
                        sketch_outputs = _input_outputs(ctx, outputs, node, 0)
                        if sketch_outputs:
                            result = ops.add_point_rsketch(
                                cast(Sketch, sketch_outputs[0]),
                                str(params["point_id"]),
                                params["x"],
                                params["y"],
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "add_line_rsketch":
                        ctx.require_params(
                            node.node_id, op_name, params, ("entity_id", "start", "end")
                        )
                        sketch_outputs = _input_outputs(ctx, outputs, node, 0)
                        if sketch_outputs:
                            result = ops.add_line_rsketch(
                                cast(Sketch, sketch_outputs[0]),
                                str(params["entity_id"]),
                                str(params["start"]),
                                str(params["end"]),
                                construction=bool(params.get("construction", False)),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "add_circle_rsketch":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("entity_id", "center", "radius"),
                        )
                        sketch_outputs = _input_outputs(ctx, outputs, node, 0)
                        if sketch_outputs:
                            result = ops.add_circle_rsketch(
                                cast(Sketch, sketch_outputs[0]),
                                str(params["entity_id"]),
                                str(params["center"]),
                                params["radius"],
                                construction=bool(params.get("construction", False)),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "add_arc_rsketch":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("entity_id", "start", "end", "center"),
                        )
                        sketch_outputs = _input_outputs(ctx, outputs, node, 0)
                        if sketch_outputs:
                            result = ops.add_arc_rsketch(
                                cast(Sketch, sketch_outputs[0]),
                                str(params["entity_id"]),
                                str(params["start"]),
                                str(params["end"]),
                                str(params["center"]),
                                construction=bool(params.get("construction", False)),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "add_bspline_rsketch":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("entity_id", "start", "end", "control_points", "degree"),
                        )
                        sketch_outputs = _input_outputs(ctx, outputs, node, 0)
                        if sketch_outputs:
                            result = ops.add_bspline_rsketch(
                                cast(Sketch, sketch_outputs[0]),
                                str(params["entity_id"]),
                                str(params["start"]),
                                str(params["end"]),
                                control_points=params["control_points"],
                                degree=int(params.get("degree", 3)),
                                knots=cast(Any, params.get("knots")),
                                multiplicities=cast(Any, params.get("multiplicities")),
                                weights=cast(Any, params.get("weights")),
                                periodic=bool(params.get("periodic", False)),
                                construction=bool(params.get("construction", False)),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name in _SKETCH_CONSTRAINT_KIND_BY_OP:
                        ctx.require_params(node.node_id, op_name, params, ("targets",))
                        sketch_outputs = _input_outputs(ctx, outputs, node, 0)
                        if sketch_outputs:
                            result = ops._constrain_rsketch(
                                cast(Sketch, sketch_outputs[0]),
                                _SKETCH_CONSTRAINT_KIND_BY_OP[op_name],
                                [str(target) for target in params.get("targets", [])],
                                value=params.get("value"),
                                constraint_id=params.get("constraint_id"),
                                driving=bool(params.get("driving", True)),
                                metadata=cast(
                                    Dict[str, Any], params.get("metadata", {})
                                ),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_wire_from_sketch_rwire":
                        sketch_outputs = _input_outputs(ctx, outputs, node, 0)
                        if sketch_outputs:
                            result = ops.make_wire_from_sketch_rwire(
                                cast(Sketch, sketch_outputs[0]),
                                profile=params.get("profile", 0),
                                require_fully_constrained=bool(
                                    params.get("require_fully_constrained", False)
                                ),
                                strict=bool(params.get("strict", True)),
                                tolerance=float(params.get("tolerance", 1e-7)),
                                max_iterations=int(params.get("max_iterations", 80)),
                            )
                            if ctx.strict and not isinstance(
                                params.get("solve_snapshot"), dict
                            ):
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) is missing required solve_snapshot"
                                )
                            if ctx.strict:
                                actual = result.get_metadata("sketch_solve", {})
                                ops._assert_sketch_solve_snapshot_dict_matches(
                                    cast(Dict[str, Any], actual),
                                    cast(Dict[str, Any], params["solve_snapshot"]),
                                    tolerance=float(params.get("tolerance", 1e-7)),
                                )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_face_from_sketch_rface":
                        sketch_outputs = _input_outputs(ctx, outputs, node, 0)
                        if sketch_outputs:
                            result = ops.make_face_from_sketch_rface(
                                cast(Sketch, sketch_outputs[0]),
                                profile=params.get("profile", 0),
                                inner_profiles=cast(
                                    Sequence[int | str],
                                    params.get("inner_profiles", ()),
                                ),
                                require_fully_constrained=bool(
                                    params.get("require_fully_constrained", False)
                                ),
                                strict=bool(params.get("strict", True)),
                                tolerance=float(params.get("tolerance", 1e-7)),
                                max_iterations=int(params.get("max_iterations", 80)),
                            )
                            if ctx.strict and not isinstance(
                                params.get("solve_snapshot"), dict
                            ):
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) is missing required solve_snapshot"
                                )
                            if ctx.strict:
                                actual = result.get_metadata("sketch_solve", {})
                                ops._assert_sketch_solve_snapshot_dict_matches(
                                    cast(Dict[str, Any], actual),
                                    cast(Dict[str, Any], params["solve_snapshot"]),
                                    tolerance=float(params.get("tolerance", 1e-7)),
                                )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_material_rmaterial":
                        ctx.require_params(
                            node.node_id, op_name, params, ("material_id",)
                        )
                        result = ops.make_material_rmaterial(
                            str(params["material_id"]),
                            name=cast(Optional[str], params.get("name")),
                            density=cast(Optional[float], params.get("density")),
                            density_unit=cast(
                                Optional[str], params.get("density_unit")
                            ),
                            color=(
                                cast(Any, tuple(params["color"]))
                                if params.get("color") is not None
                                else None
                            ),
                        )
                        materials_by_id[result.material_id] = result
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_placement_rplacement":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("origin", "x_axis", "y_axis"),
                        )
                        result = ops.make_placement_rplacement(
                            cast(Any, tuple(params["origin"])),
                            x_axis=cast(Any, tuple(params["x_axis"])),
                            y_axis=cast(Any, tuple(params["y_axis"])),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_identity_placement_rplacement":
                        result = ops.identity_placement_rplacement()
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_part_rpart":
                        ctx.require_params(node.node_id, op_name, params, ("part_id",))
                        body_outputs = _input_outputs(ctx, outputs, node, 0)
                        if body_outputs:
                            result = ops.make_part_rpart(
                                str(params["part_id"]),
                                cast(Solid, body_outputs[0]),
                                name=cast(Optional[str], params.get("name")),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_assign_material_rpart":
                        part_outputs = _input_outputs(ctx, outputs, node, 0)
                        material_outputs = (
                            _input_outputs(ctx, outputs, node, 1)
                            if len(node.inputs) > 1
                            else []
                        )
                        if not material_outputs:
                            material_payload = params.get("material")
                            if isinstance(material_payload, dict):
                                material_id = str(material_payload["material_id"])
                                material = materials_by_id.get(material_id)
                                if material is None:
                                    material = ops.make_material_rmaterial(
                                        material_id,
                                        name=cast(
                                            Optional[str], material_payload.get("name")
                                        ),
                                        density=cast(
                                            Optional[float],
                                            material_payload.get("density"),
                                        ),
                                        density_unit=cast(
                                            Optional[str],
                                            material_payload.get("density_unit"),
                                        ),
                                        color=(
                                            cast(Any, tuple(material_payload["color"]))
                                            if material_payload.get("color") is not None
                                            else None
                                        ),
                                    )
                                    materials_by_id[material_id] = material
                                material_outputs = [material]
                            elif params.get("material_id"):
                                material_id = str(params["material_id"])
                                material = materials_by_id.get(material_id)
                                if material is None:
                                    material = ops.make_material_rmaterial(material_id)
                                    materials_by_id[material_id] = material
                                material_outputs = [material]
                            elif ctx.strict:
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) is missing material data"
                                )
                        if part_outputs and material_outputs:
                            result = ops.assign_material_rpart(
                                cast(Part, part_outputs[0]),
                                cast(Material, material_outputs[0]),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_assembly_rassembly":
                        ctx.require_params(
                            node.node_id, op_name, params, ("assembly_id",)
                        )
                        result = ops.make_assembly_rassembly(
                            str(params["assembly_id"]),
                            name=cast(Optional[str], params.get("name")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_add_component_rassembly":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("component_id",),
                        )
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        item_outputs = _input_outputs(ctx, outputs, node, 1)
                        placement = None
                        if len(node.inputs) > 2:
                            placement_outputs = _input_outputs(ctx, outputs, node, 2)
                            if placement_outputs:
                                placement = cast(Placement, placement_outputs[0])
                        if placement is None:
                            raw_placement = params.get("placement")
                            if not isinstance(raw_placement, Mapping):
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) is missing placement data"
                                )
                            placement = Placement(**dict(raw_placement))
                        if assembly_outputs and item_outputs:
                            result = ops.add_component_rassembly(
                                assembly_outputs[0],
                                item_outputs[0],
                                component_id=str(params["component_id"]),
                                placement=placement,
                                name=cast(Optional[str], params.get("name")),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_place_component_rassembly":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("component_id",),
                        )
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        placement = None
                        if len(node.inputs) > 1:
                            placement_outputs = _input_outputs(ctx, outputs, node, 1)
                            if placement_outputs:
                                placement = cast(Placement, placement_outputs[0])
                        if placement is None:
                            raw_placement = params.get("placement")
                            if not isinstance(raw_placement, Mapping):
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) is missing placement data"
                                )
                            placement = Placement(**dict(raw_placement))
                        if assembly_outputs:
                            result = ops.place_component_rassembly(
                                cast(Assembly, assembly_outputs[0]),
                                str(params["component_id"]),
                                placement,
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_compound_from_assembly_rcompound":
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        if assembly_outputs:
                            result = ops.make_compound_from_assembly_rcompound(
                                cast(Assembly, assembly_outputs[0])
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name in {
                        "make_face_connector_rconnector",
                        "make_edge_connector_rconnector",
                        "make_vertex_connector_rconnector",
                    }:
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("connector_id", "geometry_ref"),
                        )
                        shape_outputs = _input_outputs(ctx, outputs, node, 0)
                        if shape_outputs:
                            shape = shape_outputs[0]
                            geo_ref_data = cast(Dict[str, Any], params["geometry_ref"])
                            geometry_ref = GeometryRef(
                                kind=str(geo_ref_data["kind"]),
                                source_node_id=cast(
                                    Optional[str], geo_ref_data.get("source_node_id")
                                ),
                                geo_selector=cast(
                                    Dict[str, Any], geo_ref_data.get("geo_selector", {})
                                ),
                                flip=bool(geo_ref_data.get("flip", False)),
                            )
                            connector = Connector(
                                str(params["connector_id"]),
                                geometry_ref,
                                name=cast(Optional[str], params.get("name")),
                            )
                            _store_outputs(node, connector)
                        continue

                    if op_name == "make_placement_connector_rconnector":
                        ctx.require_params(
                            node.node_id, op_name, params, ("connector_id",)
                        )
                        placement_outputs = _input_outputs(ctx, outputs, node, 0)
                        placement = None
                        if placement_outputs:
                            placement = cast(Placement, placement_outputs[0])
                        elif isinstance(params.get("placement"), dict):
                            placement_data = cast(Dict[str, Any], params["placement"])
                            placement = Placement(
                                cast(
                                    Any,
                                    tuple(
                                        placement_data.get("origin", (0.0, 0.0, 0.0))
                                    ),
                                ),
                                x_axis=cast(
                                    Any,
                                    tuple(
                                        placement_data.get("x_axis", (1.0, 0.0, 0.0))
                                    ),
                                ),
                                y_axis=cast(
                                    Any,
                                    tuple(
                                        placement_data.get("y_axis", (0.0, 1.0, 0.0))
                                    ),
                                ),
                            )
                        if placement is not None:
                            result = ops.make_placement_connector_rconnector(
                                str(params["connector_id"]),
                                placement,
                                name=cast(Optional[str], params.get("name")),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_add_connector_rpart":
                        part_outputs = _input_outputs(ctx, outputs, node, 0)
                        connector_outputs = _input_outputs(ctx, outputs, node, 1)
                        if part_outputs and connector_outputs:
                            result = ops.add_connector_rpart(
                                cast(Part, part_outputs[0]),
                                cast(Connector, connector_outputs[0]),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_set_public_connector_rassembly":
                        allowed_params = {
                            "assembly_id",
                            "public_connector_id",
                            "source_component_id",
                            "source_connector_id",
                            "name",
                        }
                        unexpected = sorted(set(params) - allowed_params)
                        if unexpected:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) contains unsupported parameter(s): "
                                + ", ".join(unexpected)
                            )
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            (
                                "public_connector_id",
                                "source_component_id",
                                "source_connector_id",
                            ),
                        )
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        if assembly_outputs:
                            result = ops.set_public_connector_rassembly(
                                assembly=cast(Assembly, assembly_outputs[0]),
                                public_connector_id=str(
                                    params["public_connector_id"]
                                ),
                                source_component_id=str(
                                    params["source_component_id"]
                                ),
                                source_connector_id=str(
                                    params["source_connector_id"]
                                ),
                                name=cast(Optional[str], params.get("name")),
                            )
                            _store_outputs(node, result)
                        continue


                    if op_name == "make_connector_ref_rconnectorref":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("component_id", "connector_id"),
                        )
                        result = ops.make_connector_ref_rconnectorref(
                            str(params["component_id"]),
                            str(params["connector_id"]),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_scalar_limit_rscalarlimit":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("lower_value", "upper_value"),
                        )
                        result = ops.make_scalar_limit_rscalarlimit(
                            cast(float, params["lower_value"]),
                            cast(float, params["upper_value"]),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_ground_component_rassembly":
                        ctx.require_params(
                            node.node_id, op_name, params, ("component_id",)
                        )
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        if assembly_outputs:
                            result = ops.ground_component_rassembly(
                                cast(Assembly, assembly_outputs[0]),
                                str(params["component_id"]),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_unground_component_rassembly":
                        ctx.require_params(
                            node.node_id, op_name, params, ("component_id",)
                        )
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        if assembly_outputs:
                            result = ops.unground_component_rassembly(
                                cast(Assembly, assembly_outputs[0]),
                                str(params["component_id"]),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name in {
                        "make_fixed_constraint_rassembly",
                        "make_revolute_constraint_rassembly",
                        "make_prismatic_constraint_rassembly",
                    }:
                        ctx.require_params(
                            node.node_id, op_name, params, ("constraint_id",)
                        )
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        connector_a_outputs = _input_outputs(ctx, outputs, node, 1)
                        connector_b_outputs = _input_outputs(ctx, outputs, node, 2)
                        limit_outputs = (
                            _input_outputs(ctx, outputs, node, 3)
                            if len(node.inputs) > 3
                            else []
                        )
                        if (
                            assembly_outputs
                            and connector_a_outputs
                            and connector_b_outputs
                        ):
                            assembly = cast(Assembly, assembly_outputs[0])
                            connector_a = cast(ConnectorRef, connector_a_outputs[0])
                            connector_b = cast(ConnectorRef, connector_b_outputs[0])
                            if op_name == "make_fixed_constraint_rassembly":
                                result = ops.add_fixed_constraint_rassembly(
                                    assembly,
                                    str(params["constraint_id"]),
                                    connector_a,
                                    connector_b,
                                    name=cast(Optional[str], params.get("name")),
                                )
                            elif op_name == "make_revolute_constraint_rassembly":
                                result = ops.add_revolute_constraint_rassembly(
                                    assembly,
                                    str(params["constraint_id"]),
                                    connector_a,
                                    connector_b,
                                    drive_angle_degrees=cast(
                                        Optional[float],
                                        params.get("drive_angle_degrees"),
                                    ),
                                    angle_limit=cast(
                                        Optional[ScalarLimit],
                                        limit_outputs[0] if limit_outputs else None,
                                    ),
                                    name=cast(Optional[str], params.get("name")),
                                )
                            else:
                                result = ops.add_prismatic_constraint_rassembly(
                                    assembly,
                                    str(params["constraint_id"]),
                                    connector_a,
                                    connector_b,
                                    drive_distance=cast(
                                        Optional[float], params.get("drive_distance")
                                    ),
                                    distance_limit=cast(
                                        Optional[ScalarLimit],
                                        limit_outputs[0] if limit_outputs else None,
                                    ),
                                    name=cast(Optional[str], params.get("name")),
                                )
                            _store_outputs(node, result)
                        continue

                    if op_name in {
                        "make_gear_constraint_rassembly",
                        "make_belt_constraint_rassembly",
                        "make_rack_pinion_constraint_rassembly",
                    }:
                        ctx.require_params(
                            node.node_id, op_name, params, ("constraint_id",)
                        )
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        connector_a_outputs = _input_outputs(ctx, outputs, node, 1)
                        connector_b_outputs = _input_outputs(ctx, outputs, node, 2)
                        if (
                            assembly_outputs
                            and connector_a_outputs
                            and connector_b_outputs
                        ):
                            assembly = cast(Assembly, assembly_outputs[0])
                            connector_a = cast(ConnectorRef, connector_a_outputs[0])
                            connector_b = cast(ConnectorRef, connector_b_outputs[0])
                            if op_name == "make_gear_constraint_rassembly":
                                ctx.require_params(
                                    node.node_id,
                                    op_name,
                                    params,
                                    ("pitch_radius_a", "pitch_radius_b"),
                                )
                                result = ops.add_gear_constraint_rassembly(
                                    assembly,
                                    str(params["constraint_id"]),
                                    connector_a,
                                    connector_b,
                                    float(params["pitch_radius_a"]),
                                    float(params["pitch_radius_b"]),
                                    phase_offset=cast(
                                        Optional[float], params.get("phase_offset")
                                    ),
                                    name=cast(Optional[str], params.get("name")),
                                )
                            elif op_name == "make_belt_constraint_rassembly":
                                ctx.require_params(
                                    node.node_id,
                                    op_name,
                                    params,
                                    ("pulley_radius_a", "pulley_radius_b"),
                                )
                                result = ops.add_belt_constraint_rassembly(
                                    assembly,
                                    str(params["constraint_id"]),
                                    connector_a,
                                    connector_b,
                                    float(params["pulley_radius_a"]),
                                    float(params["pulley_radius_b"]),
                                    phase_offset=cast(
                                        Optional[float], params.get("phase_offset")
                                    ),
                                    name=cast(Optional[str], params.get("name")),
                                )
                            else:
                                ctx.require_params(
                                    node.node_id,
                                    op_name,
                                    params,
                                    ("pitch_radius",),
                                )
                                result = ops.add_rack_pinion_constraint_rassembly(
                                    assembly,
                                    str(params["constraint_id"]),
                                    connector_a,
                                    connector_b,
                                    float(params["pitch_radius"]),
                                    phase_offset=cast(
                                        Optional[float], params.get("phase_offset")
                                    ),
                                    name=cast(Optional[str], params.get("name")),
                                )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_solve_assembly_constraints_rassembly":
                        assembly_outputs = _input_outputs(ctx, outputs, node, 0)
                        if assembly_outputs:
                            result = ops.solve_assembly_constraints_rassembly(
                                cast(Assembly, assembly_outputs[0]),
                                strict=bool(params.get("strict", True)),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name in {
                        "make_select_rvertex",
                        "make_select_redge",
                        "make_select_rwire",
                        "make_select_rface",
                        "make_select_rshell",
                        "make_select_rsolid",
                    }:
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("target_kind", "geo_selector"),
                        )
                        source_outputs = _input_outputs(ctx, outputs, node, 0)
                        if source_outputs:
                            result = _resolve_shape_from_geo_selector(
                                source_outputs[0],
                                cast(Dict[str, Any], params["geo_selector"]),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_ruled_surface_rface":
                        ordered = _ordered_input_shapes(
                            ctx, graph, outputs, node, params
                        )
                        if len(ordered) != 2 or not all(
                            isinstance(item, Edge) for item in ordered
                        ):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires exactly two Edge inputs"
                            )
                        result = ops.make_ruled_surface_rface(
                            cast(Edge, ordered[0]),
                            cast(Edge, ordered[1]),
                            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_gordon_surface_rface":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("profile_count", "guide_count", "tolerance"),
                        )
                        ordered = _ordered_input_shapes(
                            ctx, graph, outputs, node, params
                        )
                        profile_count = int(params["profile_count"])
                        guide_count = int(params["guide_count"])
                        if len(ordered) != profile_count + guide_count or not all(
                            isinstance(item, Edge) for item in ordered
                        ):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) input counts or kinds do not match"
                            )
                        result = ops.make_gordon_surface_rface(
                            cast(Sequence[Edge], ordered[:profile_count]),
                            cast(Sequence[Edge], ordered[profile_count:]),
                            tolerance=float(params["tolerance"]),
                            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_surface_patch_rface":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            (
                                "boundary_count",
                                "hole_count",
                                "boundaries",
                                "points",
                                "settings",
                            ),
                        )
                        ordered = _ordered_input_shapes(
                            ctx, graph, outputs, node, params
                        )
                        raw_boundaries = params["boundaries"]
                        boundary_count = int(params["boundary_count"])
                        hole_count = int(params["hole_count"])
                        if (
                            not isinstance(raw_boundaries, list)
                            or len(raw_boundaries) != boundary_count
                        ):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) boundary metadata count does not match"
                            )
                        cursor = 0
                        boundaries: List[Any] = []
                        for boundary_index, raw_boundary in enumerate(raw_boundaries):
                            if not isinstance(raw_boundary, dict):
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) boundaries[{boundary_index}] must be an object"
                                )
                            if cursor >= len(ordered) or not isinstance(
                                ordered[cursor], Edge
                            ):
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) boundary edge input is missing or invalid"
                                )
                            edge = cast(Edge, ordered[cursor])
                            cursor += 1
                            support: Optional[Face] = None
                            if bool(raw_boundary.get("has_support", False)):
                                if cursor >= len(ordered) or not isinstance(
                                    ordered[cursor], Face
                                ):
                                    ctx.fail(
                                        f"Graph node '{node.node_id}' ({op_name}) boundary support input is missing or invalid"
                                    )
                                support = cast(Face, ordered[cursor])
                                cursor += 1
                            boundaries.append(
                                ops.SurfaceBoundary(
                                    edge=edge,
                                    continuity=str(
                                        raw_boundary.get("continuity", "C0")
                                    ),
                                    support=support,
                                )
                            )
                        holes = ordered[cursor:]
                        if len(holes) != hole_count or not all(
                            isinstance(item, Wire) for item in holes
                        ):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) hole inputs do not match hole_count"
                            )
                        settings_payload = params["settings"]
                        if not isinstance(settings_payload, dict):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) settings must be an object"
                            )
                        result = ops.make_surface_patch_rface(
                            cast(Sequence[ops.SurfaceBoundary], boundaries),
                            points=cast(Sequence[Sequence[float]], params["points"]),
                            settings=ops.SurfaceFillingSettings(**settings_payload),
                            holes=cast(Sequence[Wire], holes),
                            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "trim_surface_rface":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("hole_count", "tolerance"),
                        )
                        ordered = _ordered_input_shapes(ctx, graph, outputs, node, params)
                        hole_count = int(params["hole_count"])
                        if (
                            len(ordered) != 2 + hole_count
                            or not isinstance(ordered[0], Face)
                            or not isinstance(ordered[1], Wire)
                            or not all(isinstance(item, Wire) for item in ordered[2:])
                        ):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires one Face, one outer Wire, and hole_count Wires"
                            )
                        result = ops.trim_surface_rface(
                            cast(Face, ordered[0]),
                            cast(Wire, ordered[1]),
                            holes=cast(Sequence[Wire], ordered[2:]),
                            tolerance=float(params["tolerance"]),
                            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_loft_rshell":
                        ctx.require_params(
                            node.node_id, op_name, params, ("section_count", "ruled")
                        )
                        ordered = _ordered_input_shapes(
                            ctx, graph, outputs, node, params
                        )
                        if len(ordered) != int(params["section_count"]) or not all(
                            isinstance(item, (Wire, Vertex)) for item in ordered
                        ):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) section inputs do not match section_count"
                            )
                        result = ops.loft_rshell(
                            cast(Sequence[Wire | Vertex], ordered),
                            ruled=bool(params["ruled"]),
                            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "sew_faces_rshell":
                        ctx.require_params(
                            node.node_id, op_name, params, ("face_count", "tolerance")
                        )
                        ordered = _ordered_input_shapes(
                            ctx, graph, outputs, node, params
                        )
                        if len(ordered) != int(params["face_count"]) or not all(
                            isinstance(item, Face) for item in ordered
                        ):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) face inputs do not match face_count"
                            )
                        result = ops.sew_faces_rshell(
                            cast(Sequence[Face], ordered),
                            tolerance=float(params["tolerance"]),
                            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_solid_from_shell_rsolid":
                        ordered = _ordered_input_shapes(ctx, graph, outputs, node, params)
                        if len(ordered) != 1 or not isinstance(ordered[0], Shell):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires exactly one Shell input"
                            )
                        result = ops.make_solid_from_shell_rsolid(
                            cast(Shell, ordered[0]),
                            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "free_boundaries_rwirelist":
                        ctx.require_params(
                            node.node_id, op_name, params, ("tolerance",)
                        )
                        shell_outputs = _input_outputs(ctx, outputs, node, 0)
                        if len(shell_outputs) != 1 or not isinstance(
                            shell_outputs[0], Shell
                        ):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires exactly one Shell input"
                            )
                        result = ops.free_boundaries_rwirelist(
                            cast(Shell, shell_outputs[0]),
                            tolerance=float(params["tolerance"]),
                        )
                        if ctx.strict and len(result) != int(node.output_count):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) expected {node.output_count} outputs, got {len(result)}"
                            )
                        _store_outputs(node, result)
                        continue

                    if op_name == "fill_holes_rshell":
                        ctx.require_params(
                            node.node_id, op_name, params, ("tolerance", "settings")
                        )
                        ordered = _ordered_input_shapes(
                            ctx, graph, outputs, node, params
                        )
                        if len(ordered) != 1 or not isinstance(ordered[0], Shell):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires exactly one Shell input"
                            )
                        settings_payload = params["settings"]
                        if not isinstance(settings_payload, dict):
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) settings must be an object"
                            )
                        raw_indices = params.get("hole_indices")
                        result = ops.fill_holes_rshell(
                            cast(Shell, ordered[0]),
                            hole_indices=(
                                None
                                if raw_indices is None
                                else [
                                    int(index)
                                    for index in cast(Sequence[int], raw_indices)
                                ]
                            ),
                            tolerance=float(params["tolerance"]),
                            settings=ops.SurfaceFillingSettings(**settings_payload),
                            tag_prefix=cast(Optional[str], params.get("tag_prefix")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_cut_rsolid":
                        ctx.require_params(
                            node.node_id, op_name, params, ("tool_count",)
                        )
                        if len(node.inputs) < 2:
                            if ctx.strict:
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) requires at least two inputs"
                                )
                            continue
                        body_list = _input_outputs(ctx, outputs, node, 0)
                        tool_outputs: List[AnyShape] = []
                        for index in range(1, len(node.inputs)):
                            tool_outputs.extend(
                                _input_outputs(ctx, outputs, node, index)
                            )
                        if not body_list or not tool_outputs:
                            continue
                        result = ops.cut_rsolid(
                            cast(Solid, body_list[0]),
                            [cast(Solid, tool) for tool in tool_outputs],
                            skip_non_intersecting=bool(
                                _param(
                                    ctx,
                                    node.node_id,
                                    op_name,
                                    params,
                                    "skip_non_intersecting",
                                    False,
                                )
                            ),
                            tracking_policy=str(params.get("tracking_policy", "full")),
                        )
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_union_rsolid":
                        if ctx.strict:
                            ctx.require_params(
                                node.node_id,
                                op_name,
                                params,
                                ("input_count", "clean", "glue", "tol"),
                            )
                        all_solids = [
                            cast(Solid, shape)
                            for shape in _all_input_outputs(ctx, outputs, node)
                        ]
                        if len(all_solids) >= 2:
                            result = ops.union_rsolid(
                                all_solids,
                                clean=bool(
                                    _param(
                                        ctx,
                                        node.node_id,
                                        op_name,
                                        params,
                                        "clean",
                                        True,
                                    )
                                ),
                                glue=bool(
                                    _param(
                                        ctx, node.node_id, op_name, params, "glue", True
                                    )
                                ),
                                tol=cast(
                                    Optional[float],
                                    _param(
                                        ctx, node.node_id, op_name, params, "tol", None
                                    ),
                                ),
                                tracking_policy=str(
                                    params.get("tracking_policy", "full")
                                ),
                            )
                            _store_outputs(node, result)
                        elif all_solids and not ctx.strict:
                            _store_outputs(node, all_solids[0])
                        elif ctx.strict:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires at least two solid inputs"
                            )
                        continue

                    if op_name == "make_intersect_rsolid":
                        ctx.require_params(
                            node.node_id, op_name, params, ("input_count",)
                        )
                        all_solids = [
                            cast(Solid, shape)
                            for shape in _all_input_outputs(ctx, outputs, node)
                        ]
                        if len(all_solids) >= 2:
                            result = ops.intersect_rsolid(all_solids[0], all_solids[1:])
                            _store_outputs(node, result)
                        elif ctx.strict:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires at least two solid inputs"
                            )
                        continue

                    if op_name == "make_2d_cut_rface":
                        face_outputs = _all_input_outputs(ctx, outputs, node)
                        if len(face_outputs) >= 2:
                            result = ops.make_2d_cut_rface(
                                face_outputs[0],
                                face_outputs[1],
                            )
                            _store_outputs(node, result)
                        elif ctx.strict:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires two face inputs"
                            )
                        continue

                    if op_name == "make_2d_union_rface":
                        face_outputs = _all_input_outputs(ctx, outputs, node)
                        if len(face_outputs) >= 2:
                            result = ops.make_2d_union_rface(
                                face_outputs[0],
                                face_outputs[1],
                            )
                            _store_outputs(node, result)
                        elif ctx.strict:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires two face inputs"
                            )
                        continue

                    if op_name == "make_2d_intersect_rface":
                        face_outputs = _all_input_outputs(ctx, outputs, node)
                        if len(face_outputs) >= 2:
                            result = ops.make_2d_intersect_rface(
                                face_outputs[0],
                                face_outputs[1],
                            )
                            _store_outputs(node, result)
                        elif ctx.strict:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires two face inputs"
                            )
                        continue

                    if op_name == "make_face_from_wire_rface":
                        ctx.require_params(node.node_id, op_name, params, ("normal",))
                        wire_outputs = _input_outputs(ctx, outputs, node, 0)
                        if wire_outputs:
                            result = ops.make_face_from_wire_rface(
                                wire_outputs[0],
                                normal=cast(Any, tuple(params["normal"])),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_face_from_wires_rface":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("normal", "inner_wire_count"),
                        )
                        wire_outputs = _all_input_outputs(ctx, outputs, node)
                        if wire_outputs:
                            result = ops.make_face_from_wires_rface(
                                wire_outputs[0],
                                cast(Any, wire_outputs[1:]),
                                normal=cast(Any, tuple(params["normal"])),
                            )
                            _store_outputs(node, result)
                        elif ctx.strict:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires wire inputs"
                            )
                        continue

                    if op_name == "make_wire_from_edges_rwire":
                        ctx.require_params(
                            node.node_id, op_name, params, ("edge_count",)
                        )
                        edge_outputs = _all_input_outputs(ctx, outputs, node)
                        if edge_outputs:
                            result = ops.make_wire_from_edges_rwire(
                                cast(Any, edge_outputs)
                            )
                            _store_outputs(node, result)
                        elif ctx.strict:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires edge inputs"
                            )
                        continue

                    if op_name == "make_translate_rshape":
                        ctx.require_params(node.node_id, op_name, params, ("vector",))
                        input_outputs = _input_outputs(ctx, outputs, node, 0)
                        if input_outputs:
                            result = ops.translate_shape(
                                cast(AnyShape, input_outputs[0]),
                                cast(Any, tuple(params["vector"])),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_rotate_rshape":
                        ctx.require_params(
                            node.node_id, op_name, params, ("angle", "axis", "origin")
                        )
                        input_outputs = _input_outputs(ctx, outputs, node, 0)
                        if input_outputs:
                            result = ops.rotate_shape(
                                cast(AnyShape, input_outputs[0]),
                                params["angle"],
                                axis=cast(Any, tuple(params["axis"])),
                                origin=cast(Any, tuple(params["origin"])),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_draft_rsolid":
                        ctx.require_params(node.node_id, op_name, params, ("angle", "selected_face_count", "plane_origin", "plane_normal"))
                        values = _input_outputs(ctx, outputs, node, 0)
                        if values:
                            solid = values[0]
                            faces = _resolve_feature_selection(ctx, node=node, solid=solid,
                                params=params, kind="face", outputs=outputs)
                            if ctx.strict and len(faces) != params["selected_face_count"]:
                                ctx.fail(f"Graph node '{node.node_id}' expected {params['selected_face_count']} draft faces, got {len(faces)}")
                            result = ops.draft_rsolid(solid=solid, faces_to_draft=faces, angle=params["angle"],
                                plane_origin=params["plane_origin"], plane_normal=params["plane_normal"])
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_extrude_until_rsolid":
                        ctx.require_params(node.node_id, op_name, params, ("direction", "until", "target_count"))
                        count = int(params["target_count"])
                        values = [_input_outputs(ctx, outputs, node, i)[0] for i in range(count + 1)]
                        result = ops.extrude_until_rsolid(profile=values[0], target=values[1:],
                            direction=params["direction"], until=params["until"])
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_extrude_taper_rsolid":
                        ctx.require_params(node.node_id, op_name, params, ("vector", "taper"))
                        input_values = _input_outputs(ctx, outputs, node, 0)
                        if input_values:
                            result = ops.extrude_taper_rsolid(profile=input_values[0], vector=params["vector"],
                                taper=params["taper"], flip_inner=params.get("flip_inner", True))
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_sweep_multisection_rsolid":
                        ctx.require_params(node.node_id, op_name, params, ("profile_count", "is_frenet"))
                        count = int(params["profile_count"])
                        values = [_input_outputs(ctx, outputs, node, i)[0] for i in range(count + 1)]
                        binormal = _input_outputs(ctx, outputs, node, count + 1)[0] if params.get("binormal_is_wire") else params.get("binormal")
                        result = ops.sweep_multisection_rsolid(profiles=values[:count], path=values[count],
                            is_frenet=params["is_frenet"], binormal=binormal)
                        _store_outputs(node, result)
                        continue

                    if op_name == "make_transform_rsolid":
                        ctx.require_params(node.node_id, op_name, params, ("matrix",))
                        inputs = _input_outputs(ctx, outputs, node, 0)
                        if inputs:
                            result = ops.transform_rsolid(solid=inputs[0], matrix=params["matrix"])
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_scale_rsolid":
                        ctx.require_params(node.node_id, op_name, params, ("factors", "center"))
                        inputs = _input_outputs(ctx, outputs, node, 0)
                        if inputs:
                            result = ops.scale_rsolid(solid=inputs[0], factors=params["factors"], center=params["center"])
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_offset_rsolid":
                        ctx.require_params(node.node_id, op_name, params, ("amount", "removed_face_count"))
                        inputs = _input_outputs(ctx, outputs, node, 0)
                        if inputs:
                            solid = inputs[0]
                            faces = _resolve_feature_selection(ctx, node=node, solid=solid,
                                params=params, kind="face", outputs=outputs) if params["removed_face_count"] else []
                            if ctx.strict and len(faces) != params["removed_face_count"]:
                                ctx.fail(f"Graph node '{node.node_id}' expected {params['removed_face_count']} opening faces, got {len(faces)}")
                            result = ops.offset_rsolid(solid=solid, amount=params["amount"], openings=faces,
                                tolerance=params.get("tolerance", 1e-4), kind=params.get("kind", "ARC"))
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_extrude_rsolid":
                        ctx.require_params(
                            node.node_id, op_name, params, ("direction", "distance")
                        )
                        profile_outputs = _input_outputs(ctx, outputs, node, 0)
                        if profile_outputs:
                            result = ops.extrude_rsolid(
                                profile_outputs[0],
                                cast(Any, tuple(params["direction"])),
                                params["distance"],
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_revolve_rsolid":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("axis", "angle", "origin"),
                        )
                        profile_outputs = _input_outputs(ctx, outputs, node, 0)
                        if profile_outputs:
                            result = ops.revolve_rsolid(
                                profile_outputs[0],
                                axis=cast(Any, tuple(params["axis"])),
                                angle=params["angle"],
                                origin=cast(Any, tuple(params["origin"])),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_loft_rsolid":
                        ctx.require_params(
                            node.node_id, op_name, params, ("profile_count", "ruled")
                        )
                        profile_outputs = _all_input_outputs(ctx, outputs, node)
                        if profile_outputs:
                            result = ops.loft_rsolid(
                                cast(Any, profile_outputs),
                                ruled=bool(params["ruled"]),
                                tracking_policy=str(
                                    params.get("tracking_policy", "full")
                                ),
                            )
                            _store_outputs(node, result)
                        elif ctx.strict:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires profile inputs"
                            )
                        continue

                    if op_name == "make_sweep_rsolid":
                        ctx.require_params(
                            node.node_id, op_name, params, ("is_frenet",)
                        )
                        profile_outputs = _input_outputs(ctx, outputs, node, 0)
                        path_outputs = _input_outputs(ctx, outputs, node, 1)
                        if profile_outputs and path_outputs:
                            result = ops.sweep_rsolid(
                                profile_outputs[0],
                                path_outputs[0],
                                is_frenet=bool(params["is_frenet"]),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_twisted_sweep_rsolid":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            (
                                "axis",
                                "origin",
                                "distance",
                                "twist_angle",
                                "guide_radius",
                            ),
                        )
                        if ctx.strict and len(node.inputs) != 1:
                            ctx.fail(
                                f"Graph node '{node.node_id}' ({op_name}) requires exactly one profile input"
                            )
                        profile_outputs = _input_outputs(ctx, outputs, node, 0)
                        if profile_outputs:
                            result = ops.twisted_sweep_rsolid(
                                profile_outputs[0],
                                distance=params["distance"],
                                twist_angle=params["twist_angle"],
                                axis=cast(Any, tuple(params["axis"])),
                                origin=cast(Any, tuple(params["origin"])),
                                guide_radius=params["guide_radius"],
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_mirror_rshape":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("plane_origin", "plane_normal"),
                        )
                        input_outputs = _input_outputs(ctx, outputs, node, 0)
                        if input_outputs:
                            result = ops.mirror_shape(
                                input_outputs[0],
                                cast(Any, tuple(params["plane_origin"])),
                                cast(Any, tuple(params["plane_normal"])),
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_fillet_rsolid":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("radius", "edge_count"),
                        )
                        input_outputs = _input_outputs(ctx, outputs, node, 0)
                        if input_outputs:
                            solid = cast(Solid, input_outputs[0])
                            edges = cast(
                                List[Edge],
                                _resolve_feature_selection(
                                    ctx,
                                    node=node,
                                    solid=solid,
                                    params=params,
                                    kind="edge",
                                    outputs=outputs,
                                ),
                            )
                            expected = int(params["edge_count"])
                            if ctx.strict and len(edges) != expected:
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) expected {expected} selected edge(s), got {len(edges)}"
                                )
                            result = ops.fillet_rsolid(solid, edges, params["radius"])
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_chamfer_rsolid":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("distance", "edge_count"),
                        )
                        input_outputs = _input_outputs(ctx, outputs, node, 0)
                        if input_outputs:
                            solid = cast(Solid, input_outputs[0])
                            edges = cast(
                                List[Edge],
                                _resolve_feature_selection(
                                    ctx,
                                    node=node,
                                    solid=solid,
                                    params=params,
                                    kind="edge",
                                    outputs=outputs,
                                ),
                            )
                            expected = int(params["edge_count"])
                            if ctx.strict and len(edges) != expected:
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) expected {expected} selected edge(s), got {len(edges)}"
                                )
                            result = ops.chamfer_rsolid(
                                solid, edges, params["distance"]
                            )
                            _store_outputs(node, result)
                        continue

                    if op_name == "make_shell_rsolid":
                        ctx.require_params(
                            node.node_id,
                            op_name,
                            params,
                            ("thickness", "removed_face_count"),
                        )
                        input_outputs = _input_outputs(ctx, outputs, node, 0)
                        if input_outputs:
                            solid = cast(Solid, input_outputs[0])
                            faces = cast(
                                List[Face],
                                _resolve_feature_selection(
                                    ctx,
                                    node=node,
                                    solid=solid,
                                    params=params,
                                    kind="face",
                                    outputs=outputs,
                                ),
                            )
                            expected = int(params["removed_face_count"])
                            if ctx.strict and len(faces) != expected:
                                ctx.fail(
                                    f"Graph node '{node.node_id}' ({op_name}) expected {expected} selected face(s), got {len(faces)}"
                                )
                            result = ops.shell_rsolid(solid, faces, params["thickness"])
                            _store_outputs(node, result)
                        continue

                    result = _replay_primitive_or_simple(ctx, node, params)
                    _store_outputs(node, result)
            except Exception as exc:
                raise ValueError(
                    f"Failed to replay graph node '{node.node_id}' ({op_name}): {exc}"
                ) from exc

    leaf_results: List[Any] = []
    if leaf_node_ids is None:
        target_leaf_ids = [leaf.node_id for leaf in graph.leaf_nodes()]
    else:
        target_leaf_ids = [str(node_id) for node_id in leaf_node_ids]
    for node_id in target_leaf_ids:
        if node_id not in outputs:
            if ctx.strict:
                ctx.fail(f"Leaf node '{node_id}' has no replay output")
            continue
        leaf_results.extend(outputs[node_id])

    return leaf_results


def replay_feature_graph(
    artifact: Any,
    *,
    strict: bool = True,
    external_definitions: Mapping[str, Any] | None = None,
) -> List[Any]:
    """Replay a durable FeatureGraphArtifact with immutable child definitions."""

    from ..artifacts.assembly_definition import AssemblyDefinition
    from ..artifacts.assembly_io import materialize_definition
    from ..artifacts.feature_graph import FeatureGraphArtifact
    from ..artifacts.part_definition import PartDefinition

    if not isinstance(artifact, FeatureGraphArtifact):
        raise TypeError("artifact must be a FeatureGraphArtifact")
    provided = dict(external_definitions or {})
    expected = {
        str(item["definition_id"]): item for item in artifact.external_definitions
    }
    if set(provided) != set(expected):
        raise ValueError("external definition resolver keys differ from feature graph")
    runtime: Dict[str, Part | Assembly] = {}
    for definition_id, record in expected.items():
        definition = provided[definition_id]
        if not isinstance(definition, (PartDefinition, AssemblyDefinition)):
            raise TypeError("external resolver values must be durable definitions")
        actual = {
            "definition_kind": definition.definition_kind,
            "definition_id": definition.definition_id,
            "revision": definition.revision,
            "content_hash": definition.content_hash,
        }
        if actual != dict(record):
            raise ValueError(
                f"external definition {definition_id!r} identity differs from feature graph"
            )
        runtime[definition_id] = materialize_definition(definition)
    return _execute_graph(
        OperationGraph.from_dict(dict(artifact.graph)),
        artifact.result_node_ids,
        strict=strict,
        external_definitions=runtime,
    )


def replay_graph(graph: OperationGraph, *, strict: bool = True) -> List[Any]:
    """Replay an OperationGraph to rebuild the model.

    Executes nodes in topological order. Primitives are created from their
    parameters; boolean operations consume upstream outputs.

    Args:
        graph: The graph to replay.

    Returns:
        List of leaf-node outputs. These may be solids, faces, wires, edges,
        or vertices depending on the workflow.
    """

    return _execute_graph(graph, strict=strict)

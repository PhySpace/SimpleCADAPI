"""
SimpleCADAPI on OpenCASCADE, implemented in C++ (pybind11).
"""
from . import _brep_region
from . import _internal_mesh
from . import _occt
from . import std
from __future__ import annotations
from simplecadapi import math
from simplecadapi import ql
from simplecadapi import surface
from simplecadapi.core import Compound
from simplecadapi.core import CoordinateSystem
from simplecadapi.core import Edge
from simplecadapi.core import Face
from simplecadapi.core import Shell
from simplecadapi.core import SimpleWorkplane
from simplecadapi.core import SimpleWorkplane as Workplane
from simplecadapi.core import Solid
from simplecadapi.core import Vertex
from simplecadapi.core import Wire
from simplecadapi.core import get_current_cs
from simplecadapi.core import use_coordinate_system
from simplecadapi.kernel.ocp_properties import Vec3
from simplecadapi.math import BSplineFitResult
from simplecadapi.math import fit_cubic_bspline_control_points
from simplecadapi.operators._diagnostics import BlendDiagnosis
from simplecadapi.operators._diagnostics import BooleanDiagnosis
from simplecadapi.operators._diagnostics import assert_blend_volume_monotonic
from simplecadapi.operators._diagnostics import diagnose_blend_failure
from simplecadapi.operators._diagnostics import diagnose_boolean_failure
from simplecadapi.operators._diagnostics import raise_loft_failure_if_diagnosed
from simplecadapi.operators.boolean import boolean_rsolidlist
from simplecadapi.operators.boolean import cut_rsolid
from simplecadapi.operators.boolean import cut_rsolid_list
from simplecadapi.operators.boolean import intersect_rsolid
from simplecadapi.operators.boolean import make_2d_cut_rface
from simplecadapi.operators.boolean import make_2d_intersect_rface
from simplecadapi.operators.boolean import make_2d_union_rface
from simplecadapi.operators.boolean import union_rsolid
from simplecadapi.operators.features import chamfer_rsolid
from simplecadapi.operators.features import draft_rsolid
from simplecadapi.operators.features import extrude_rsolid
from simplecadapi.operators.features import extrude_taper_rsolid
from simplecadapi.operators.features import extrude_until_rsolid
from simplecadapi.operators.features import fillet_rsolid
from simplecadapi.operators.features import helical_sweep_rsolid
from simplecadapi.operators.features import loft_rsolid
from simplecadapi.operators.features import offset_rsolid
from simplecadapi.operators.features import revolve_rsolid
from simplecadapi.operators.features import shell_rsolid
from simplecadapi.operators.features import sweep_multisection_rsolid
from simplecadapi.operators.features import sweep_rsolid
from simplecadapi.operators.features import twisted_sweep_rsolid
from simplecadapi.operators.geometry import load_brep_region_rshell
from simplecadapi.operators.geometry import load_brep_region_rsolid
from simplecadapi.operators.geometry import make_angle_arc_redge
from simplecadapi.operators.geometry import make_angle_arc_redge as create_angle_arc
from simplecadapi.operators.geometry import make_angle_arc_rwire
from simplecadapi.operators.geometry import make_angle_arc_rwire as create_angle_arc_wire
from simplecadapi.operators.geometry import make_box_rsolid
from simplecadapi.operators.geometry import make_box_rsolid as create_box
from simplecadapi.operators.geometry import make_circle_redge
from simplecadapi.operators.geometry import make_circle_redge as create_circle_edge
from simplecadapi.operators.geometry import make_circle_rface
from simplecadapi.operators.geometry import make_circle_rface as create_circle_face
from simplecadapi.operators.geometry import make_circle_rwire
from simplecadapi.operators.geometry import make_circle_rwire as create_circle_wire
from simplecadapi.operators.geometry import make_cone_rsolid
from simplecadapi.operators.geometry import make_cylinder_rsolid
from simplecadapi.operators.geometry import make_cylinder_rsolid as create_cylinder
from simplecadapi.operators.geometry import make_ellipse_redge
from simplecadapi.operators.geometry import make_ellipse_rface
from simplecadapi.operators.geometry import make_ellipse_rwire
from simplecadapi.operators.geometry import make_face_from_wire_rface
from simplecadapi.operators.geometry import make_face_from_wire_rface as create_face_from_wire
from simplecadapi.operators.geometry import make_face_from_wires_rface
from simplecadapi.operators.geometry import make_face_from_wires_rface as create_face_from_wires
from simplecadapi.operators.geometry import make_helix_redge
from simplecadapi.operators.geometry import make_helix_redge as create_helix
from simplecadapi.operators.geometry import make_helix_rwire
from simplecadapi.operators.geometry import make_helix_rwire as create_helix_wire
from simplecadapi.operators.geometry import make_interpolated_spline_redge
from simplecadapi.operators.geometry import make_interpolated_spline_redge as create_interpolated_spline
from simplecadapi.operators.geometry import make_interpolated_spline_rwire
from simplecadapi.operators.geometry import make_interpolated_spline_rwire as create_interpolated_spline_wire
from simplecadapi.operators.geometry import make_line_redge
from simplecadapi.operators.geometry import make_line_redge as create_line
from simplecadapi.operators.geometry import make_periodic_spline_rwire
from simplecadapi.operators.geometry import make_periodic_spline_rwire as create_periodic_spline_wire
from simplecadapi.operators.geometry import make_point_rvertex
from simplecadapi.operators.geometry import make_point_rvertex as create_point
from simplecadapi.operators.geometry import make_polyline_rwire
from simplecadapi.operators.geometry import make_polyline_rwire as create_polyline_wire
from simplecadapi.operators.geometry import make_rectangle_rface
from simplecadapi.operators.geometry import make_rectangle_rface as create_rectangle_face
from simplecadapi.operators.geometry import make_rectangle_rwire
from simplecadapi.operators.geometry import make_rectangle_rwire as create_rectangle_wire
from simplecadapi.operators.geometry import make_segment_redge
from simplecadapi.operators.geometry import make_segment_redge as create_segment
from simplecadapi.operators.geometry import make_segment_rwire
from simplecadapi.operators.geometry import make_segment_rwire as create_segment_wire
from simplecadapi.operators.geometry import make_sphere_rsolid
from simplecadapi.operators.geometry import make_sphere_rsolid as create_sphere
from simplecadapi.operators.geometry import make_spline_redge
from simplecadapi.operators.geometry import make_spline_redge as create_spline
from simplecadapi.operators.geometry import make_spline_rwire
from simplecadapi.operators.geometry import make_spline_rwire as create_spline_wire
from simplecadapi.operators.geometry import make_three_point_arc_redge
from simplecadapi.operators.geometry import make_three_point_arc_redge as create_arc
from simplecadapi.operators.geometry import make_three_point_arc_rwire
from simplecadapi.operators.geometry import make_three_point_arc_rwire as create_arc_wire
from simplecadapi.operators.geometry import make_wire_from_edges_rwire
from simplecadapi.operators.geometry import make_wire_from_edges_rwire as create_wire_from_edges
from simplecadapi.operators.product import add_belt_constraint_rassembly
from simplecadapi.operators.product import add_component_rassembly
from simplecadapi.operators.product import add_connector_rpart
from simplecadapi.operators.product import add_fixed_constraint_rassembly
from simplecadapi.operators.product import add_gear_constraint_rassembly
from simplecadapi.operators.product import add_prismatic_constraint_rassembly
from simplecadapi.operators.product import add_rack_pinion_constraint_rassembly
from simplecadapi.operators.product import add_revolute_constraint_rassembly
from simplecadapi.operators.product import assign_material_rpart
from simplecadapi.operators.product import ground_component_rassembly
from simplecadapi.operators.product import identity_placement_rplacement
from simplecadapi.operators.product import inspect_assembly_constraints_rconstraintreport
from simplecadapi.operators.product import make_assembly_rassembly
from simplecadapi.operators.product import make_compound_from_assembly_rcompound
from simplecadapi.operators.product import make_connector_ref_rconnectorref
from simplecadapi.operators.product import make_edge_connector_rconnector
from simplecadapi.operators.product import make_face_connector_rconnector
from simplecadapi.operators.product import make_material_rmaterial
from simplecadapi.operators.product import make_part_rpart
from simplecadapi.operators.product import make_placement_connector_rconnector
from simplecadapi.operators.product import make_placement_rplacement
from simplecadapi.operators.product import make_scalar_limit_rscalarlimit
from simplecadapi.operators.product import make_vertex_connector_rconnector
from simplecadapi.operators.product import measure_constraint_residual_rconstraintresidual
from simplecadapi.operators.product import place_component_rassembly
from simplecadapi.operators.product import set_public_connector_rassembly
from simplecadapi.operators.product import solve_assembly_constraints_rassembly
from simplecadapi.operators.product import unground_component_rassembly
from simplecadapi.operators.selection import apply_tag
from simplecadapi.operators.selection import apply_tag_rselection
from simplecadapi.operators.selection import explain_tag
from simplecadapi.operators.selection import list_tags
from simplecadapi.operators.selection import select_edges_by_tag
from simplecadapi.operators.selection import select_faces_by_tag
from simplecadapi.operators.sketch import add_arc_rsketch
from simplecadapi.operators.sketch import add_bspline_rsketch
from simplecadapi.operators.sketch import add_circle_rsketch
from simplecadapi.operators.sketch import add_ellipse_rsketch
from simplecadapi.operators.sketch import add_line_rsketch
from simplecadapi.operators.sketch import add_point_rsketch
from simplecadapi.operators.sketch import constrain_angle_rsketch
from simplecadapi.operators.sketch import constrain_coincident_rsketch
from simplecadapi.operators.sketch import constrain_collinear_rsketch
from simplecadapi.operators.sketch import constrain_concentric_rsketch
from simplecadapi.operators.sketch import constrain_connect_rsketch
from simplecadapi.operators.sketch import constrain_diameter_rsketch
from simplecadapi.operators.sketch import constrain_distance_rsketch
from simplecadapi.operators.sketch import constrain_distance_x_rsketch
from simplecadapi.operators.sketch import constrain_distance_y_rsketch
from simplecadapi.operators.sketch import constrain_equal_length_rsketch
from simplecadapi.operators.sketch import constrain_equal_radius_rsketch
from simplecadapi.operators.sketch import constrain_fix_rsketch
from simplecadapi.operators.sketch import constrain_horizontal_rsketch
from simplecadapi.operators.sketch import constrain_length_rsketch
from simplecadapi.operators.sketch import constrain_line_distance_rsketch
from simplecadapi.operators.sketch import constrain_major_radius_rsketch
from simplecadapi.operators.sketch import constrain_midpoint_points_rsketch
from simplecadapi.operators.sketch import constrain_midpoint_rsketch
from simplecadapi.operators.sketch import constrain_minor_radius_rsketch
from simplecadapi.operators.sketch import constrain_mirror_rsketch
from simplecadapi.operators.sketch import constrain_normal_rsketch
from simplecadapi.operators.sketch import constrain_parallel_rsketch
from simplecadapi.operators.sketch import constrain_perpendicular_rsketch
from simplecadapi.operators.sketch import constrain_point_on_rsketch
from simplecadapi.operators.sketch import constrain_points_horizontal_rsketch
from simplecadapi.operators.sketch import constrain_points_vertical_rsketch
from simplecadapi.operators.sketch import constrain_radius_rsketch
from simplecadapi.operators.sketch import constrain_symmetric_rsketch
from simplecadapi.operators.sketch import constrain_tangent_rsketch
from simplecadapi.operators.sketch import constrain_vertical_rsketch
from simplecadapi.operators.sketch import get_sketch_entity_rsketchref
from simplecadapi.operators.sketch import get_sketch_point_rsketchref
from simplecadapi.operators.sketch import inspect_sketch_rsketchresult
from simplecadapi.operators.sketch import make_face_from_sketch_rface
from simplecadapi.operators.sketch import make_sketch_rsketch
from simplecadapi.operators.sketch import make_wire_from_sketch_rwire
from simplecadapi.operators.transform import linear_pattern_rsolidlist
from simplecadapi.operators.transform import mirror_shape
from simplecadapi.operators.transform import radial_pattern_rsolidlist
from simplecadapi.operators.transform import rotate_shape
from simplecadapi.operators.transform import scale_rsolid
from simplecadapi.operators.transform import transform_rsolid
from simplecadapi.operators.transform import translate_shape
from simplecadapi.params.expr import Const
from simplecadapi.params.expr import DimensionTolerance
from simplecadapi.params.expr import Expr
from simplecadapi.params.expr import ExpressionGraph
from simplecadapi.params.expr import Var
from simplecadapi.params.expr import acos
from simplecadapi.params.expr import asin
from simplecadapi.params.expr import atan
from simplecadapi.params.expr import atan2
from simplecadapi.params.expr import canonicalize_params
from simplecadapi.params.expr import const
from simplecadapi.params.expr import cos
from simplecadapi.params.expr import evaluate_scalar
from simplecadapi.params.expr import evaluate_value
from simplecadapi.params.expr import lift_scalar
from simplecadapi.params.expr import referenced_expressions
from simplecadapi.params.expr import sin
from simplecadapi.params.expr import sqrt
from simplecadapi.params.expr import tan
from simplecadapi.params.expr import var
from simplecadapi.params.frame import FrameGraph
from simplecadapi.params.frame import FrameNode
from simplecadapi.params.units import Dimension
from simplecadapi.params.units import Unit
from simplecadapi.params.units import canonical_unit_for_dimension
from simplecadapi.params.units import convert_value
from simplecadapi.params.units import expression_uses_units
from simplecadapi.params.units import get_unit
from simplecadapi.params.units import infer_dimension
from simplecadapi.params.units import unit_from_payload
from simplecadapi.params.units import unit_to_payload
from simplecadapi.product.assembly import Assembly
from simplecadapi.product.assembly import Component
from simplecadapi.product.assembly import PublicConnectorRef
from simplecadapi.product.connector import Connector
from simplecadapi.product.connector import ConnectorAnchor
from simplecadapi.product.connector import ConnectorRef
from simplecadapi.product.connector import GeometryRef
from simplecadapi.product.connector import resolve_connector
from simplecadapi.product.connector import resolve_connector_placement
from simplecadapi.product.connector import resolve_connector_ref_placement
from simplecadapi.product.connector import resolve_item_connector
from simplecadapi.product.connector import resolve_item_connector_placement
from simplecadapi.product.constraint import Constraint
from simplecadapi.product.constraint import ConstraintReport
from simplecadapi.product.constraint import ConstraintResidual
from simplecadapi.product.constraint import ScalarLimit
from simplecadapi.product.material import Material
from simplecadapi.product.part import Part
from simplecadapi.product.placement import Placement
from simplecadapi.product.solver import inspect_assembly_constraints
from simplecadapi.product.solver import solve_assembly_constraints
from simplecadapi.recording.graph import GraphSession
from simplecadapi.recording.graph import get_active_session
from simplecadapi.recording.graph import isolated_recording
from simplecadapi.recording.graph import record_operation_if_active
from simplecadapi.recording.graph import suspend_graph_recording
from simplecadapi.sketch import Sketch
from simplecadapi.sketch import SketchConstraint
from simplecadapi.sketch import SketchConstraintDiagnostic
from simplecadapi.sketch import SketchEntity
from simplecadapi.sketch import SketchRef
from simplecadapi.sketch import SketchSolveResult
from simplecadapi.surface import SurfaceBoundary
from simplecadapi.surface import SurfaceFillingSettings
from simplecadapi.surface import fill_holes_rshell
from simplecadapi.surface import fit_point_grid_rface
from simplecadapi.surface import free_boundaries_rwirelist
from simplecadapi.surface import loft_rshell
from simplecadapi.surface import make_bezier_surface_rface
from simplecadapi.surface import make_cylindrical_surface_rface
from simplecadapi.surface import make_gordon_surface_rface
from simplecadapi.surface import make_ruled_surface_rface
from simplecadapi.surface import make_solid_from_shell_rsolid
from simplecadapi.surface import make_surface_patch_rface
from simplecadapi.surface import sew_faces_rshell
from simplecadapi.surface import trim_surface_rface
from simplecadapi.topology import tagging
from simplecadapi.topology.model import OperationGraph
from simplecadapi.topology.model import OperationNode
from simplecadapi.topology.model import SemanticDelta
from simplecadapi.topology.model import SemanticRef
from simplecadapi.topology.model import same_node_content
from simplecadapi.topology.model import upstream_closure
from simplecadapi.topology.tagging import LineageDerivation
from simplecadapi.topology.tagging import LineagePolicy
from simplecadapi.topology.tagging import TagAttachment
from simplecadapi.topology.tagging import TagBinding
from simplecadapi.topology.tagging import TagBindingScope
from simplecadapi.topology.tagging import TagCertainty
from simplecadapi.topology.tagging import TagEvidence
from simplecadapi.topology.tagging import TagEvidenceKind
from simplecadapi.topology.tagging import TagLifecycle
from simplecadapi.topology.tagging import TagLineageWitness
from simplecadapi.topology.tagging import TagPolicy
from simplecadapi.topology.tagging import TagProducer
from simplecadapi.topology.tagging import TagProducerKind
from simplecadapi.topology.tagging import TagPropagation
from simplecadapi.topology.tagging import TagScope
from simplecadapi.topology.tagging import TagTarget
from simplecadapi.topology.tagging import TagTargetKind
from simplecadapi.topology.tagging import TopologyPropagation
from simplecadapi.topology.tracking import TrackingPolicy
from simplecadapi.topology.tracking import current_tracking_policy
import collections.abc
import numpy
import numpy.typing
import simplecadapi.core
import simplecadapi.params.units
import typing
__all__: list[str] = ['ANGLE', 'AREA', 'AnyShape', 'Assembly', 'BSplineFitResult', 'BlendDiagnosis', 'BooleanDiagnosis', 'CM', 'CUBIC_CM', 'CUBIC_FOOT', 'CUBIC_INCH', 'CUBIC_M', 'CUBIC_MM', 'Component', 'Compound', 'Connector', 'ConnectorAnchor', 'ConnectorRef', 'Const', 'Constraint', 'ConstraintReport', 'ConstraintResidual', 'CoordinateSystem', 'DEGREE', 'DIMENSIONLESS', 'Dimension', 'DimensionTolerance', 'Edge', 'ExecutorRegistry', 'Expr', 'ExprBase', 'ExpressionGraph', 'FOOT', 'Face', 'FrameGraph', 'FrameNode', 'GeometryRef', 'GraphSession', 'INCH', 'LENGTH', 'LineageDerivation', 'LineagePolicy', 'M', 'MM', 'Material', 'Mesh', 'NodeFailure', 'ONE', 'OperationGraph', 'OperationNode', 'PERCENT', 'Part', 'Placement', 'PublicConnectorRef', 'RADIAN', 'RecomputeReport', 'RenderFrame', 'RenderPanel', 'RenderScene', 'SQUARE_CM', 'SQUARE_FOOT', 'SQUARE_INCH', 'SQUARE_M', 'SQUARE_MM', 'ScalarLimit', 'SemanticDelta', 'SemanticRef', 'Shell', 'SimpleWorkplane', 'Sketch', 'SketchConstraint', 'SketchConstraintDiagnostic', 'SketchEntity', 'SketchRef', 'SketchSolveResult', 'SketchSolverBackend', 'SketchSolverOptions', 'Solid', 'StaleLineageError', 'SurfaceBoundary', 'SurfaceFillingSettings', 'TagAttachment', 'TagBinding', 'TagBindingScope', 'TagCertainty', 'TagEvidence', 'TagEvidenceKind', 'TagLifecycle', 'TagLineageWitness', 'TagPolicy', 'TagProducer', 'TagProducerKind', 'TagPropagation', 'TagScope', 'TagTarget', 'TagTargetKind', 'TopologyPropagation', 'TrackingPolicy', 'Unit', 'UnitValidationError', 'VOLUME', 'Var', 'Vec3', 'Vertex', 'WORLD_CS', 'Wire', 'Workplane', 'acos', 'add_arc_rsketch', 'add_belt_constraint_rassembly', 'add_bspline_rsketch', 'add_circle_rsketch', 'add_component_rassembly', 'add_connector_rpart', 'add_ellipse_rsketch', 'add_fixed_constraint_rassembly', 'add_gear_constraint_rassembly', 'add_line_rsketch', 'add_point_rsketch', 'add_prismatic_constraint_rassembly', 'add_rack_pinion_constraint_rassembly', 'add_revolute_constraint_rassembly', 'apply_tag', 'apply_tag_rselection', 'asin', 'assert_blend_volume_monotonic', 'assign_material_rpart', 'atan', 'atan2', 'boolean_rsolidlist', 'canonical_brep_bytes', 'canonical_bytes', 'canonical_hash', 'canonical_unit_for_dimension', 'canonicalize_params', 'chamfer_rsolid', 'clone_semantic_view', 'const', 'constrain_angle_rsketch', 'constrain_coincident_rsketch', 'constrain_collinear_rsketch', 'constrain_concentric_rsketch', 'constrain_connect_rsketch', 'constrain_diameter_rsketch', 'constrain_distance_rsketch', 'constrain_distance_x_rsketch', 'constrain_distance_y_rsketch', 'constrain_equal_length_rsketch', 'constrain_equal_radius_rsketch', 'constrain_fix_rsketch', 'constrain_horizontal_rsketch', 'constrain_length_rsketch', 'constrain_line_distance_rsketch', 'constrain_major_radius_rsketch', 'constrain_midpoint_points_rsketch', 'constrain_midpoint_rsketch', 'constrain_minor_radius_rsketch', 'constrain_mirror_rsketch', 'constrain_normal_rsketch', 'constrain_parallel_rsketch', 'constrain_perpendicular_rsketch', 'constrain_point_on_rsketch', 'constrain_points_horizontal_rsketch', 'constrain_points_vertical_rsketch', 'constrain_radius_rsketch', 'constrain_symmetric_rsketch', 'constrain_tangent_rsketch', 'constrain_vertical_rsketch', 'constraint_reports_match', 'convert_value', 'cos', 'create_angle_arc', 'create_angle_arc_wire', 'create_arc', 'create_arc_wire', 'create_box', 'create_circle_edge', 'create_circle_face', 'create_circle_wire', 'create_cylinder', 'create_face_from_wire', 'create_face_from_wires', 'create_helix', 'create_helix_wire', 'create_interpolated_spline', 'create_interpolated_spline_wire', 'create_line', 'create_periodic_spline_wire', 'create_point', 'create_polyline_wire', 'create_rectangle_face', 'create_rectangle_wire', 'create_segment', 'create_segment_wire', 'create_sphere', 'create_spline', 'create_spline_wire', 'create_wire_from_edges', 'current_tracking_policy', 'cut_rsolid', 'cut_rsolid_list', 'deserialize_shape', 'diagnose_blend_failure', 'diagnose_boolean_failure', 'draft_rsolid', 'evaluate_scalar', 'evaluate_value', 'explain_tag', 'export_brep', 'export_glb', 'export_obj', 'export_step', 'export_step_assembly', 'export_stl', 'expression_uses_units', 'extrude_rsolid', 'extrude_taper_rsolid', 'extrude_until_rsolid', 'fill_holes_rshell', 'fillet_rsolid', 'find_registered_node', 'fit_cubic_bspline_control_points', 'fit_point_grid_rface', 'forget_graph_nodes', 'free_boundaries_rwirelist', 'from_brep', 'get_active_session', 'get_current_cs', 'get_default_sketch_solver_backend', 'get_sketch_entity_rsketchref', 'get_sketch_point_rsketchref', 'get_sketch_solver_backend', 'get_unit', 'global_executor_registry', 'ground_component_rassembly', 'helical_sweep_rsolid', 'identity_placement_rplacement', 'import_brep', 'import_step', 'import_stl', 'import_stl_shape', 'infer_dimension', 'inspect_assembly_constraints', 'inspect_assembly_constraints_rconstraintreport', 'inspect_sketch_rsketchresult', 'intersect_rsolid', 'isolated_recording', 'lift_scalar', 'linear_pattern_rsolidlist', 'list_tags', 'load_brep_region_rshell', 'load_brep_region_rsolid', 'loft_rshell', 'loft_rsolid', 'make_2d_cut_rface', 'make_2d_intersect_rface', 'make_2d_union_rface', 'make_angle_arc_redge', 'make_angle_arc_rwire', 'make_assembly_rassembly', 'make_bezier_surface_rface', 'make_box_rsolid', 'make_circle_redge', 'make_circle_rface', 'make_circle_rwire', 'make_compound_from_assembly_rcompound', 'make_cone_rsolid', 'make_connector_ref_rconnectorref', 'make_cylinder_rsolid', 'make_cylindrical_surface_rface', 'make_edge_connector_rconnector', 'make_ellipse_redge', 'make_ellipse_rface', 'make_ellipse_rwire', 'make_face_connector_rconnector', 'make_face_from_sketch_rface', 'make_face_from_wire_rface', 'make_face_from_wires_rface', 'make_gordon_surface_rface', 'make_helix_redge', 'make_helix_rwire', 'make_interpolated_spline_redge', 'make_interpolated_spline_rwire', 'make_line_redge', 'make_material_rmaterial', 'make_param_spec', 'make_part_rpart', 'make_periodic_spline_rwire', 'make_placement_connector_rconnector', 'make_placement_rplacement', 'make_point_rvertex', 'make_polyline_rwire', 'make_rectangle_rface', 'make_rectangle_rwire', 'make_ruled_surface_rface', 'make_scalar_limit_rscalarlimit', 'make_segment_redge', 'make_segment_rwire', 'make_sketch_rsketch', 'make_solid_from_shell_rsolid', 'make_sphere_rsolid', 'make_spline_redge', 'make_spline_rwire', 'make_surface_patch_rface', 'make_three_point_arc_redge', 'make_three_point_arc_rwire', 'make_vertex_connector_rconnector', 'make_wire_from_edges_rwire', 'make_wire_from_sketch_rwire', 'math', 'measure_constraint_residual_rconstraintresidual', 'mesh', 'mirror_shape', 'offset_rsolid', 'parse_ui_comment', 'place_component_rassembly', 'ql', 'radial_pattern_rsolidlist', 'raise_loft_failure_if_diagnosed', 'record_operation_if_active', 'recording_active', 'referenced_expressions', 'register_executor', 'register_graph_nodes', 'register_node', 'register_sketch_solver_backend', 'render_auto_view', 'render_default_threads', 'render_edge_polylines', 'render_scene', 'render_view_preset', 'resolve_connector', 'resolve_connector_placement', 'resolve_connector_ref_placement', 'resolve_item_connector', 'resolve_item_connector_placement', 'revolve_rsolid', 'rotate_shape', 'same_node_content', 'scale_rsolid', 'select_edges_by_tag', 'select_faces_by_tag', 'serialize_shape', 'set_default_sketch_solver_backend', 'set_producer_version', 'set_public_connector_rassembly', 'sew_faces_rshell', 'shell_rsolid', 'sin', 'sketch_solver_backend', 'solve_assembly_constraints', 'solve_assembly_constraints_rassembly', 'sqrt', 'std', 'step_bytes', 'surface', 'suspend_graph_recording', 'sweep_multisection_rsolid', 'sweep_rsolid', 'tagging', 'tan', 'tessellate_solid', 'tracking_policy_scope', 'transform_rsolid', 'translate_shape', 'trim_surface_rface', 'twisted_sweep_rsolid', 'unground_component_rassembly', 'union_rsolid', 'unit_from_payload', 'unit_to_payload', 'upstream_closure', 'use_coordinate_system', 'var']
class AnyShape:
    """
    Tag mixin that provides tagging support for geometry objects.
    """
    @staticmethod
    def from_brep(data: bytes, require_valid: bool = False) -> typing.Any:
        """
        from_brep(data: bytes) -> Shape
        The shape (Solid, Face, ...) stored in BinTools or ASCII BRep bytes.
        """
    def __reduce__(self) -> tuple[typing.Any, tuple[bytes]]:
        ...
    def _add_tag_binding(self, binding: TagBinding) -> None:
        ...
    def _add_tag_lineage(self, binding: TagBinding, *, derivation: str, source_topo_id: str, evidence: TagEvidence, coverage: str = 'complete') -> None:
        ...
    def _apply_user_tag(self, tag: str, *, topology_propagation: str = ..., lineage_policy: str = ..., producer_node_id: str | None = None) -> TagBinding:
        ...
    def _bounds(self) -> tuple[float, float, float, float, float, float]:
        """
        (xmin, ymin, zmin, xmax, ymax, zmax) of the shape.
        """
    def _copy_semantic_state_from(self, source: AnyShape) -> None:
        ...
    def _copy_tag_state_from(self, source: AnyShape) -> None:
        ...
    def _geom_type(self) -> typing.Any:
        """
        The geometric type of a face's surface or an edge's curve, or None.
        """
    def _geometry(self) -> typing.Any:
        """
        The analytic parameters of a face's surface (cylinder, sphere, torus) or an edge's curve, or None.
        """
    def _inherited_tag_bindings(self) -> list[TagBinding]:
        ...
    def _keep_topology_owner(self) -> None:
        """
        Before a tag node re-attributes the shape: its contents stay named by the nodes that made them.
        """
    def _legacy_effective_bindings(self) -> list[TagBinding]:
        ...
    def _lineage_tag_bindings(self) -> list[TagBinding]:
        ...
    def _list_tag_bindings(self, scope: str = ...) -> list[TagBinding]:
        ...
    def _local_tag_bindings(self) -> list[TagBinding]:
        ...
    def _metadata_dict(self) -> typing.Any:
        ...
    def _orientation(self) -> str:
        """
        The orientation of this occurrence in its container: forward, reversed, internal or external.
        """
    def _polyline(self, linear: typing.SupportsFloat | typing.SupportsIndex, angular: typing.SupportsFloat | typing.SupportsIndex) -> list:
        ...
    def _refresh_tag_cache(self, *, recursive: bool = False) -> None:
        ...
    def _remove_tag(self, tag: str, *, matching_producer: typing.Any = ...) -> int:
        ...
    def _remove_tag_binding(self, binding_id: str) -> bool:
        ...
    def _replace_local_tag_bindings(self, bindings: collections.abc.Sequence[TagBinding]) -> None:
        ...
    def _runtime_dict(self) -> typing.Any:
        ...
    def _shape_key(self) -> tuple[int, int, float, int, float, float, float, float, float, float, float, float, float, float, float, float]:
        """
        Identity key of the underlying OCCT shape (see the memo in artifacts' geometry interface).
        """
    def _topo_ref(self) -> typing.Any:
        """
        The durable reference (graph, node, slot, kind, topo id) of an entity of a recorded output, or None.
        """
    def to_brep(self) -> bytes:
        """
        to_brep() -> bytes
        BinTools binary, format version 4, geometry only (no triangulation): bit-exact doubles, readable by every
        OpenCASCADE >= 7.3.  Hand these bytes to OCP with BinTools.Read_s(shape, io.BytesIO(data)).
        """
    @property
    def _tag_bindings(self) -> list[TagBinding]:
        ...
    @property
    def _tag_lineage(self) -> list[TagLineageWitness]:
        ...
    @property
    def _tags(self) -> set:
        ...
    @_tags.setter
    def _tags(self, arg1: typing.Any) -> None:
        ...
    @property
    def topo_id(self) -> str:
        ...
class ExecutorRegistry:
    def __init__(self, builtins: bool = True) -> None:
        ...
    def add(self, op: str, executor: collections.abc.Callable) -> None:
        """
        Register fn(params, inputs, scalars) -> outputs for an operation name.
        """
    def contains(self, op: str) -> bool:
        ...
    def operations(self) -> list[str]:
        ...
    def remove(self, op: str) -> bool:
        ...
    def replace(self, op: str, executor: collections.abc.Callable) -> None:
        ...
class ExprBase(_ExprNode):
    """
    Base class for scalar expression nodes.
    """
    def __abs__(self) -> ...:
        ...
    def __add__(self, arg0: typing.Any) -> ...:
        ...
    def __bool__(self) -> bool:
        ...
    def __eq__(self, arg0: typing.Any) -> bool:
        ...
    def __float__(self) -> float:
        ...
    def __hash__(self) -> int:
        ...
    def __mul__(self, arg0: typing.Any) -> ...:
        ...
    def __neg__(self) -> ...:
        ...
    def __pow__(self, arg0: typing.Any) -> ...:
        ...
    def __radd__(self, arg0: typing.Any) -> ...:
        ...
    def __repr__(self) -> str:
        ...
    def __rmul__(self, arg0: typing.Any) -> ...:
        ...
    def __rpow__(self, arg0: typing.Any) -> ...:
        ...
    def __rsub__(self, arg0: typing.Any) -> ...:
        ...
    def __rtruediv__(self, arg0: typing.Any) -> ...:
        ...
    def __sub__(self, arg0: typing.Any) -> ...:
        ...
    def __truediv__(self, arg0: typing.Any) -> ...:
        ...
    def evaluate(self, bindings: typing.Any = None) -> float:
        ...
    @property
    def expr_id(self) -> str:
        ...
class Mesh:
    """
    A triangle mesh: float32 vertices (n, 3), per-vertex normals (n, 3), uint32 triangles (m, 3) and the face
    index of each triangle (m,).  The arrays are read-only views of the mesh's own memory (no copy); they keep
    the mesh alive.
    """
    def __repr__(self) -> str:
        ...
    @property
    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        ...
    @property
    def face_ids(self) -> numpy.ndarray:
        ...
    @property
    def face_ranges(self) -> numpy.ndarray:
        """
        (face_index, first_triangle, triangle_count) for every face, in face order.
        """
    @property
    def normals(self) -> numpy.ndarray:
        ...
    @property
    def triangle_count(self) -> int:
        ...
    @property
    def triangles(self) -> numpy.ndarray:
        ...
    @property
    def vertex_count(self) -> int:
        ...
    @property
    def vertices(self) -> numpy.ndarray:
        ...
class NodeFailure:
    def __repr__(self) -> str:
        ...
    @property
    def message(self) -> str:
        ...
    @property
    def node_id(self) -> str:
        ...
    @property
    def op(self) -> str:
        ...
class RecomputeReport:
    def __repr__(self) -> str:
        ...
    @property
    def blocked(self) -> list[str]:
        ...
    @property
    def changed(self) -> list[str]:
        ...
    @property
    def executed(self) -> list[str]:
        ...
    @property
    def failed(self) -> list[NodeFailure]:
        ...
    @property
    def memoized(self) -> list[str]:
        ...
    @property
    def ok(self) -> bool:
        ...
    @property
    def unchanged(self) -> list[str]:
        ...
class RenderFrame:
    """
    A rendered image: rgba (h, w, 4) uint8, depth (h, w) float32 (+inf = background), mesh_id and
    face_id (h, w) int32 (-1 = background), the panels and their projected anchors.  Arrays are
    read-only views of the frame's memory.
    """
    @property
    def depth(self) -> numpy.ndarray:
        ...
    @property
    def face_id(self) -> numpy.ndarray:
        ...
    @property
    def height(self) -> int:
        ...
    @property
    def ink_diameter(self) -> float:
        ...
    @property
    def mesh_id(self) -> numpy.ndarray:
        ...
    @property
    def panels(self) -> list[RenderPanel]:
        ...
    @property
    def render_ms(self) -> float:
        ...
    @property
    def resolve_ms(self) -> float:
        ...
    @property
    def rgba(self) -> numpy.ndarray:
        ...
    @property
    def width(self) -> int:
        ...
class RenderPanel:
    def project(self, point: tuple[float, float, float]) -> tuple[float, float, float, bool]:
        """
        (x, y, depth, in_view) of a world point in output pixels.
        """
    @property
    def anchors(self) -> list:
        """
        One (x, y, depth, in_view, visible) per requested anchor; x, y in output pixels (y down).
        """
    @property
    def axes_tips(self) -> list:
        ...
    @property
    def camera(self) -> dict:
        ...
    @property
    def height(self) -> int:
        ...
    @property
    def label(self) -> str:
        ...
    @property
    def width(self) -> int:
        ...
    @property
    def x(self) -> int:
        ...
    @property
    def y(self) -> int:
        ...
class RenderScene:
    """
    The input of the software renderer: surface meshes (with per-face colours), line sets and point sets.
    """
    def __init__(self) -> None:
        ...
    def add_edges(self, shape: AnyShape, color: typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"] = [0.16, 0.21, 0.27], ink: bool = False, width_px: typing.SupportsFloat | typing.SupportsIndex | None = 4.5, deflection: typing.SupportsFloat | typing.SupportsIndex = 0.04, sample_count: typing.SupportsInt | typing.SupportsIndex = 0) -> int:
        """
        Add the edges of `shape` (an edge, a wire, a solid ...) as depth-tested lines of `width_px` output pixels (or ink).
        """
    def add_mesh(self, mesh: Mesh, color: typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"] = [0.55, 0.64, 0.73], opacity: typing.SupportsFloat | typing.SupportsIndex = 1.0, studio_material: bool = False, lit: bool = True, face_colors: typing.Annotated[numpy.typing.ArrayLike, numpy.float32] | None = None) -> int:
        """
        Add a Mesh (the result of mesh(shape)); returns its index in the id buffer.  face_colors is an (n, 4) float array indexed by
        face id; a NaN alpha means 'use color'.
        """
    def add_mesh_arrays(self, vertices: typing.Annotated[numpy.typing.ArrayLike, numpy.float32], normals: typing.Annotated[numpy.typing.ArrayLike, numpy.float32], triangles: typing.Annotated[numpy.typing.ArrayLike, numpy.uint32], face_ids: typing.Annotated[numpy.typing.ArrayLike, numpy.uint32], color: typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"] = [0.55, 0.64, 0.73], opacity: typing.SupportsFloat | typing.SupportsIndex = 1.0, studio_material: bool = False, lit: bool = True, face_colors: typing.Annotated[numpy.typing.ArrayLike, numpy.float32] | None = None) -> int:
        ...
    def add_points(self, points: typing.Annotated[numpy.typing.ArrayLike, numpy.float32], color: typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"] = [0.78, 0.0, 0.0], size_px: typing.SupportsFloat | typing.SupportsIndex = 15.0) -> int:
        ...
    def add_polylines(self, points: typing.Annotated[numpy.typing.ArrayLike, numpy.float32], starts: typing.Annotated[numpy.typing.ArrayLike, numpy.uint32] | None = None, color: typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"] = [0.16, 0.21, 0.27], ink: bool = False, width_px: typing.SupportsFloat | typing.SupportsIndex | None = 4.5, depth_bias: typing.SupportsFloat | typing.SupportsIndex | None = None) -> int:
        ...
    def add_shape(self, shape: AnyShape, color: typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"] = [0.55, 0.64, 0.73], opacity: typing.SupportsFloat | typing.SupportsIndex = 1.0, studio_material: bool = False, lit: bool = True, face_colors: typing.Annotated[numpy.typing.ArrayLike, numpy.float32] | None = None, linear_deflection: typing.SupportsFloat | typing.SupportsIndex = 0.35, angular_deflection: typing.SupportsFloat | typing.SupportsIndex = 0.22, edges: bool = True, edge_color: typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"] = [0.16, 0.21, 0.27], ink: bool = True, edge_width_px: typing.SupportsFloat | typing.SupportsIndex | None = None, edge_deflection: typing.SupportsFloat | typing.SupportsIndex | None = None) -> int:
        """
        Tessellate `shape` and (by default) add its B-rep edges as ink.  Returns the mesh index.
        """
    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        ...
    @property
    def mesh_count(self) -> int:
        ...
    @property
    def triangle_count(self) -> int:
        ...
class SketchSolverBackend:
    def solve(self, sketch: ..., *, options: SketchSolverOptions) -> SketchSolveResult:
        ...
    @property
    def name(self) -> str:
        ...
    @property
    def version(self) -> str:
        ...
class SketchSolverOptions:
    def __init__(self, tolerance: typing.SupportsFloat | typing.SupportsIndex = 1e-07, max_iterations: typing.SupportsInt | typing.SupportsIndex = 80) -> None:
        ...
    @property
    def max_iterations(self) -> int:
        ...
    @property
    def tolerance(self) -> float:
        ...
class _CoordinateSystemScope:
    def __enter__(self) -> None:
        ...
    def __exit__(self, arg0: typing.Any, arg1: typing.Any, arg2: typing.Any) -> None:
        ...
class _ExprNode:
    pass
class _IsolatedRecording:
    def __enter__(self) -> typing.Any:
        ...
    def __exit__(self, arg0: typing.Any, arg1: typing.Any, arg2: typing.Any) -> None:
        ...
class _SketchSolverBackendContext:
    def __enter__(self) -> SketchSolverBackend:
        ...
    def __exit__(self, *args) -> bool:
        ...
class _SuspendGraphRecording:
    def __enter__(self) -> typing.Any:
        ...
    def __exit__(self, arg0: typing.Any, arg1: typing.Any, arg2: typing.Any) -> None:
        ...
class _TrackingPolicyScope:
    def __enter__(self) -> _TrackingPolicyScope:
        ...
    def __exit__(self, *args) -> None:
        ...
def _brep_region_path(path: typing.Any, *, for_graph: bool) -> str:
    """
    The checks on a .scadbrep locator (graph replay: relative, no drive, no '..', '/' separators).
    """
def _bspline_curve_of(edge: AnyShape) -> dict:
    """
    Poles, degree, knots, multiplicities, weights of an edge's B-spline curve.
    """
def _constrain_rsketch(sketch: Sketch, kind: str, targets: collections.abc.Sequence[SketchRef | str], *, value: float | Expr | None = None, constraint_id: str | None = None, driving: bool = True, metadata: typing.Any = None, expected: typing.Any = None) -> Sketch:
    """
    Any constraint kind by name (graph replay); `expected` is accepted and not used.
    """
def _from_occt(shape: TopoDS_Shape) -> typing.Any:
    """
    A native shape for an OCCT shape (the way back from `.wrapped`).
    """
def _guided_loft_recipe(shape: AnyShape) -> typing.Any:
    """
    Boundary profiles and guide curves of the B-spline faces of a loft (translator recipe), or None.
    """
def _interpolated_bspline_edge(points: collections.abc.Sequence[typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"]], *, periodic: bool = False, tolerance: typing.SupportsFloat | typing.SupportsIndex = 1e-06) -> Edge:
    """
    An interpolating B-spline edge through the points (GeomAPI_Interpolate).
    """
def _sample_edge_points(edge: AnyShape, samples: typing.SupportsInt | typing.SupportsIndex = 16) -> list[typing.Annotated[list[float], "FixedSize(3)"]]:
    """
    Points along an edge, evenly in parameter.
    """
def _set_diagnostic_image_provider(provider: typing.Any) -> None:
    """
    Install provider(kind, operation, view, caption, dedup_key, shapes, payload) -> evidence dict or None: it draws the pictures a failing operation asks for.  None removes it.
    """
def canonical_brep_bytes(shape: AnyShape) -> bytes:
    """
    The deterministic BREP encoding to hash (artifacts.brep.write_brep_bytes): the smallest member of the
    encode/decode cycle.
    """
def canonical_bytes(value: typing.Any, safe_ints: bool = False) -> typing.Any:
    """
    RFC 8785 bytes of a JSON-like Python value (what artifacts.canonical.canonical_bytes returns), or None when the value needs the Python implementation (it raises the error). safe_ints: integers outside +-(2**53-1) become the string 'int:<n>' (geometry_interface._json_safe).
    """
def canonical_hash(value: typing.Any, omit: typing.Any = None, safe_ints: bool = False) -> typing.Any:
    """
    'sha256:<hex>' of the canonical bytes of `value` without the top-level keys in `omit` (artifacts.canonical.content_hash), or None when the value needs the Python implementation.
    """
def clone_semantic_view(shape: AnyShape) -> typing.Any:
    """
    A new root over the same geometry in which every entity carries a copy of the source entity's complete state
    (tags, bindings, lineage, metadata, graph attachments) under the same topo id.
    """
def constraint_reports_match(actual: typing.Any, expected: typing.Any) -> bool:
    """
    Two ConstraintReport dicts agree within the solver tolerances.
    """
def deserialize_shape(data: bytes) -> typing.Any:
    """
    Inverse of serialize_shape.
    """
def export_brep(shape: AnyShape, path: os.PathLike | str | bytes) -> None:
    """
    Write BinTools V4 BREP bytes to a file.
    """
def export_glb(shapes: typing.Any, path: os.PathLike | str | bytes, *, linear_deflection: typing.SupportsFloat | typing.SupportsIndex = 0.1, angular_deflection: typing.SupportsFloat | typing.SupportsIndex = 0.5, relative: bool = False) -> None:
    """
    Write a glTF 2.0 binary (.glb): one mesh, positions + normals + triangle indices.
    Defaults are the kernel exporter's (0.1 linear, 0.5 rad angular).
    """
def export_obj(shapes: typing.Any, path: os.PathLike | str | bytes, *, linear_deflection: typing.SupportsFloat | typing.SupportsIndex = 0.1, angular_deflection_degrees: typing.SupportsFloat | typing.SupportsIndex = 20.0, relative: bool = False) -> dict:
    ...
def export_step(shapes: typing.Any, path: os.PathLike | str | bytes) -> None:
    """
    Write a shape, or a list of shapes (as one compound), to a STEP file.
    """
def export_step_assembly(definitions: collections.abc.Sequence, root_id: str, path: os.PathLike | str | bytes, *, schema: str = 'AP242DIS', metadata_properties: bool = True) -> dict:
    """
    AP242 STEP of a product structure (XCAF names, colours, materials, metadata properties).
    """
def export_stl(shapes: typing.Any, path: os.PathLike | str | bytes, *, linear_deflection: typing.SupportsFloat | typing.SupportsIndex = 0.1, angular_deflection_degrees: typing.SupportsFloat | typing.SupportsIndex = 20.0, relative: bool = False, ascii: bool = False) -> typing.Any:
    """
    Binary STL of the solids' surface (vertices welded per solid) and a report dict; ascii=True writes
    unwelded ASCII facets (kernel export_stl_shape) and returns None.
    """
def find_registered_node(graph_id: str, node_id: str) -> typing.Any:
    """
    The node a shared-lineage session recorded (or that register_graph_nodes added), by graph and node id.
    """
def forget_graph_nodes(graph_id: str) -> None:
    ...
def from_brep(data: bytes, require_valid: bool = False) -> typing.Any:
    """
    from_brep(data: bytes) -> Shape
    The shape (Solid, Face, ...) stored in BinTools or ASCII BRep bytes.
    """
def get_default_sketch_solver_backend() -> SketchSolverBackend:
    ...
def get_sketch_solver_backend(name: str | None = None) -> SketchSolverBackend:
    ...
def global_executor_registry() -> ExecutorRegistry:
    ...
def import_brep(path: os.PathLike | str | bytes, require_valid: bool = False) -> typing.Any:
    ...
def import_step(path: os.PathLike | str | bytes, *, require_single_root: bool = False, require_valid: bool = False) -> typing.Any:
    """
    Read a STEP file: the single root, or a compound of every root.
    """
def import_stl(path: os.PathLike | str | bytes) -> Mesh:
    """
    Read a binary or ASCII STL as a Mesh (coincident vertices merged).
    """
def import_stl_shape(path: os.PathLike | str | bytes, sewing_tolerance: typing.SupportsFloat | typing.SupportsIndex = 1e-06) -> typing.Any:
    """
    Read an STL as a faceted BREP (a Solid when the triangles close up).
    """
def make_param_spec(name: str, kind: str, default: typing.Any, ui: typing.Any = None, declared: str = 'literal') -> typing.Any:
    ...
def mesh(shape: AnyShape, linear_deflection: typing.SupportsFloat | typing.SupportsIndex = 0.35, angular_deflection: typing.SupportsFloat | typing.SupportsIndex = 0.22, *, relative: bool = False, parallel: bool = True) -> Mesh:
    """
    Tessellate `shape` (copy-on-mesh: the argument is not modified) into a Mesh.
    Faces keep their own vertices, so normals stay sharp across edges; triangles wind outward.
    """
def parse_ui_comment(text: str) -> typing.Any:
    """
    Parse the text of a `# ui:` comment (slider(1, 5, step=1, unit='mm')).
    """
def recording_active() -> bool:
    """
    Whether a session is active and not suspended (an operation would be recorded).
    """
def register_executor(op: str, executor: collections.abc.Callable) -> None:
    ...
def register_graph_nodes(graph: OperationGraph) -> None:
    """
    Make the nodes of a restored graph findable by shared-lineage sessions.
    """
def register_node(node: OperationNode) -> None:
    """
    Make one node findable by shared-lineage sessions.
    """
def register_sketch_solver_backend(backend: typing.Any, *, replace: bool = False) -> None:
    ...
def render_auto_view(spans: tuple[float, float, float]) -> tuple[float, float]:
    """
    The 'auto' view for a model with these x/y/z extents.
    """
def render_default_threads() -> int:
    ...
def render_edge_polylines(shape: AnyShape, deflection: typing.SupportsFloat | typing.SupportsIndex = 0.04, sample_count: typing.SupportsInt | typing.SupportsIndex = 0) -> tuple[numpy.typing.NDArray[numpy.float32], numpy.typing.NDArray[numpy.uint32]]:
    """
    (points (n,3) float32, starts (k+1,) uint32): each unique B-rep edge of `shape` as a polyline.
    """
def render_scene(scene: RenderScene, width: typing.SupportsInt | typing.SupportsIndex = 1400, height: typing.SupportsInt | typing.SupportsIndex = 900, supersample: typing.SupportsInt | typing.SupportsIndex = 2, style: str = 'studio', views: collections.abc.Sequence[tuple[typing.SupportsFloat | typing.SupportsIndex, typing.SupportsFloat | typing.SupportsIndex, str]] = [(28.0, -45.0, 'isometric')], legend_panel_fraction: typing.SupportsFloat | typing.SupportsIndex = 0.0, view_up: tuple[float, float, float] | None = None, zoom: typing.SupportsFloat | typing.SupportsIndex = 1.0, edge_width_scale: typing.SupportsFloat | typing.SupportsIndex = 0.0019, show_axes: bool = False, anchors: collections.abc.Sequence[tuple[float, float, float]] = [], threads: typing.SupportsInt | typing.SupportsIndex = 0, resolve: str = 'lanczos', background_top: typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"] | None = None, background_bottom: typing.Annotated[collections.abc.Sequence[typing.SupportsFloat | typing.SupportsIndex], "FixedSize(3)"] | None = None, occlusion_tolerance: typing.SupportsFloat | typing.SupportsIndex = 0.002) -> RenderFrame:
    """
    Render `scene` into a grid of (elevation_deg, azimuth_deg, label) views (orthographic, supersampled, depth-tested).
    `zoom` multiplies the SDK's 0.92 fit; a single-view screenshot with the SDK's zoom=4 default is zoom=1.
    """
def render_view_preset(name: str) -> tuple[float, float]:
    """
    (elevation, azimuth) of a named view ('iso', 'top', 'front_right', ...).
    """
def serialize_shape(shape: AnyShape) -> bytes:
    """
    Geometry (BinTools V4) plus the tags, bindings, lineage, metadata and runtime values of every entity, in the
    versioned 'SCADSHAP' container (docs/io.md).
    """
def set_default_sketch_solver_backend(backend: typing.Any) -> None:
    ...
def set_producer_version(version: str) -> None:
    ...
def sketch_solver_backend(backend: typing.Any) -> _SketchSolverBackendContext:
    ...
def step_bytes(shapes: typing.Any) -> bytes:
    ...
def tessellate_solid(shape: AnyShape, *, linear_deflection: typing.SupportsFloat | typing.SupportsIndex = 0.1, angular_deflection_degrees: typing.SupportsFloat | typing.SupportsIndex = 20.0, relative: bool = False) -> tuple[numpy.typing.NDArray[numpy.float64], numpy.typing.NDArray[numpy.int32]]:
    """
    (vertices Nx3 float64, triangles Mx3 int32): the shape's surface tessellated, vertices welded.
    """
def tracking_policy_scope(policy: typing.Any) -> _TrackingPolicyScope:
    """
    Run a block with graph-only or full topology tracking.
    """
ANGLE: simplecadapi.params.units.Dimension  # value = Dimension(length=0, angle=1)
AREA: simplecadapi.params.units.Dimension  # value = Dimension(length=2, angle=0)
CM: simplecadapi.params.units.Unit  # value = Unit(symbol='cm', dimension=Dimension(length=1, angle=0), scale_to_canonical=10.0)
CUBIC_CM: simplecadapi.params.units.Unit  # value = Unit(symbol='cm^3', dimension=Dimension(length=3, angle=0), scale_to_canonical=1000.0)
CUBIC_FOOT: simplecadapi.params.units.Unit  # value = Unit(symbol='ft^3', dimension=Dimension(length=3, angle=0), scale_to_canonical=28316846.592000004)
CUBIC_INCH: simplecadapi.params.units.Unit  # value = Unit(symbol='in^3', dimension=Dimension(length=3, angle=0), scale_to_canonical=16387.064)
CUBIC_M: simplecadapi.params.units.Unit  # value = Unit(symbol='m^3', dimension=Dimension(length=3, angle=0), scale_to_canonical=1000000000.0)
CUBIC_MM: simplecadapi.params.units.Unit  # value = Unit(symbol='mm^3', dimension=Dimension(length=3, angle=0), scale_to_canonical=1.0)
DEGREE: simplecadapi.params.units.Unit  # value = Unit(symbol='deg', dimension=Dimension(length=0, angle=1), scale_to_canonical=1.0)
DIMENSIONLESS: simplecadapi.params.units.Dimension  # value = Dimension(length=0, angle=0)
FOOT: simplecadapi.params.units.Unit  # value = Unit(symbol='ft', dimension=Dimension(length=1, angle=0), scale_to_canonical=304.8)
INCH: simplecadapi.params.units.Unit  # value = Unit(symbol='in', dimension=Dimension(length=1, angle=0), scale_to_canonical=25.4)
LENGTH: simplecadapi.params.units.Dimension  # value = Dimension(length=1, angle=0)
M: simplecadapi.params.units.Unit  # value = Unit(symbol='m', dimension=Dimension(length=1, angle=0), scale_to_canonical=1000.0)
MM: simplecadapi.params.units.Unit  # value = Unit(symbol='mm', dimension=Dimension(length=1, angle=0), scale_to_canonical=1.0)
ONE: simplecadapi.params.units.Unit  # value = Unit(symbol='1', dimension=Dimension(length=0, angle=0), scale_to_canonical=1.0)
PERCENT: simplecadapi.params.units.Unit  # value = Unit(symbol='%', dimension=Dimension(length=0, angle=0), scale_to_canonical=0.01)
RADIAN: simplecadapi.params.units.Unit  # value = Unit(symbol='rad', dimension=Dimension(length=0, angle=1), scale_to_canonical=57.29577951308232)
SQUARE_CM: simplecadapi.params.units.Unit  # value = Unit(symbol='cm^2', dimension=Dimension(length=2, angle=0), scale_to_canonical=100.0)
SQUARE_FOOT: simplecadapi.params.units.Unit  # value = Unit(symbol='ft^2', dimension=Dimension(length=2, angle=0), scale_to_canonical=92903.04000000001)
SQUARE_INCH: simplecadapi.params.units.Unit  # value = Unit(symbol='in^2', dimension=Dimension(length=2, angle=0), scale_to_canonical=645.16)
SQUARE_M: simplecadapi.params.units.Unit  # value = Unit(symbol='m^2', dimension=Dimension(length=2, angle=0), scale_to_canonical=1000000.0)
SQUARE_MM: simplecadapi.params.units.Unit  # value = Unit(symbol='mm^2', dimension=Dimension(length=2, angle=0), scale_to_canonical=1.0)
VOLUME: simplecadapi.params.units.Dimension  # value = Dimension(length=3, angle=0)
WORLD_CS: simplecadapi.core.CoordinateSystem  # value = CoordinateSystem(origin=(0, 0, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0))

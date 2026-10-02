"""Shared imports, constants, and helpers for operator modules."""

from __future__ import annotations

import re

import uuid

from pathlib import Path

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    NoReturn,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    cast,
)

from dataclasses import dataclass, asdict

import math

import numpy as np

from .._internal.vendor_warning_filters import suppress_vendor_deprecation_warnings

from ..errors import (
    ErrorEvidence,
    ErrorMeasurement,
    InventoryEntry,
    SimpleCADError,
    raise_harness_error,
)

suppress_vendor_deprecation_warnings()

from OCP.BRepCheck import BRepCheck_Analyzer

from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex

from OCP.Precision import Precision

from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from OCP.TopoDS import TopoDS

from ..core import (
    Vertex,
    Edge,
    Wire,
    Face,
    Shell,
    Solid,
    Compound,
    AnyShape,
    WORLD_CS,
    clone_semantic_shape_view,
    _same_semantic_topology,
    get_current_cs,
    use_coordinate_system,
)

from ..topology.autotag import apply_tracking_tags_to_delta

from ..params.expr import ScalarLike, evaluate_scalar, evaluate_value

from ..params.units import DIMENSIONLESS, LENGTH, expression_uses_units, infer_dimension

from ..recording.graph import (
    attach_graph_node,
    attach_semantic_graph_node,
    get_active_session,
    record_operation,
    record_operation_if_active,
    suspend_graph_recording,
)

from ..ql import ShapeSelector, output_role

from ..product.assembly import Assembly, Component, PublicConnectorRef

from ..product.solver import (
    coupling_phase_offset,
    inspect_assembly_constraints,
    measure_constraint_residual,
    solve_assembly_constraints,
)

from ..product.connector import Connector, ConnectorAnchor, ConnectorRef, GeometryRef

from ..product.constraint import Constraint, ConstraintReport, ConstraintResidual, ScalarLimit

from ..product.material import Material

from ..product.part import Part

from ..product.placement import Placement, compose_placements, identity_placement

from ..sketch import Sketch, SketchRef, SketchSolveResult

from ..topology.tagging import (
    LineagePolicy,
    SemanticCapabilityError,
    TagBinding,
    TagBindingScope,
    TagCertainty,
    TagEvidence,
    TagLifecycle,
    TagProducer,
    TagProducerKind,
    TagPropagation,
    TagScope,
    TagTarget,
    TagTargetKind,
    TagEvidenceKind,
    TopologyPropagation,
    lineage_policy_allows,
    normalize_tag,
    normalize_tag_scope,
)

from ..topology.model import (
    SemanticDelta,
    SemanticRef,
    TopoDelta,
    TopoRoleEntry,
    TopoEntry,
    TopoKind,
    TopoRef,
    OperationNode,
    StaleLineageError,
    topo_ref_to_dict,
)

from ..topology.tracking import (
    TrackingPolicy,
    TrackedBooleanResult,
    TrackedResult,
    _topo_id,
    current_tracking_policy,
    tracked_box,
    tracked_chamfer,
    tracked_cone,
    tracked_cylinder,
    tracked_cut,
    tracked_extrude,
    tracked_fillet,
    tracked_intersect,
    tracked_mirror,
    tracked_loft,
    tracked_revolve,
    tracked_rotate,
    tracked_shell,
    tracked_sweep,
    tracked_twisted_sweep,
    tracked_translate,
    track_union_history,
)

from ..kernel.ocp_builders import (
    make_sphere_solid,
)

from .._internal.brep_region import read_artifact

from ..kernel.ocp_curves import (
    make_arc_angle_edge,
    make_arc_three_point_edge,
    make_bspline_edge,
    make_circle_edge,
    make_ellipse_edge,
    make_helix_wire,
    make_interpolated_bspline_edge,
    make_line_edge,
    make_polyline_wire,
    make_wire_from_edges as make_wire_from_edges_ocp,
)

from ..kernel.ocp_features import (
    make_face_from_wire as make_face_from_wire_ocp,
    make_face_from_wires as make_face_from_wires_ocp,
    make_helical_sweep_solid,
    make_loft_solid,
    make_sweep_solid,
)

from ..kernel.ocp_transforms import (
    mirror_shape_ocp,
    rotate_shape_ocp,
    place_shape_ocp,
    translate_shape_ocp,
)

from ..kernel.ocp_booleans import (
    common_shapes,
    cut_shapes,
    fuse_shapes,
    fuse_shapes_with_history,
    solids_of,
)

from ..kernel.ocp_topology import faces_of as faces_of_ocp

from ..kernel.ocp_export import make_compound_always

from ..kernel.ocp_surfaces import (
    fill_shell_holes as fill_shell_holes_ocp,
    fit_point_grid_surface,
    free_boundaries as free_boundaries_ocp,
    make_bezier_surface,
    make_cylindrical_surface,
    make_filling_face,
    make_gordon_surface,
    make_loft_shell,
    make_ruled_face,
    sew_faces_with_history as sew_faces_with_history_ocp,
    shell_from_face,
    trim_surface_face,
)

from ..kernel.ocp_mesh import solid_from_shell

from ..kernel.ocp_mesh import tessellate_face

from ..kernel.ocp_properties import bounding_box, distance as ocp_distance

_DEFAULT_UNION_GLUE = False

_DEFAULT_UNION_TOL_FACTOR = 1e-7

_DEFAULT_UNION_TOL_MIN = 1e-7

_DEFAULT_UNION_TOL_MAX = 1e-5

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

_SKETCH_CONSTRAINT_OPS = {
    "coincident": "make_constrain_coincident_rsketch",
    "connect": "make_constrain_coincident_rsketch",
    "point_on": "make_constrain_point_on_rsketch",
    "horizontal": "make_constrain_horizontal_rsketch",
    "vertical": "make_constrain_vertical_rsketch",
    "points_horizontal": "make_constrain_points_horizontal_rsketch",
    "points_vertical": "make_constrain_points_vertical_rsketch",
    "line_distance": "make_constrain_line_distance_rsketch",
    "normal": "make_constrain_normal_rsketch",
    "mirror": "make_constrain_mirror_rsketch",
    "midpoint_points": "make_constrain_midpoint_points_rsketch",
    "parallel": "make_constrain_parallel_rsketch",
    "perpendicular": "make_constrain_perpendicular_rsketch",
    "collinear": "make_constrain_collinear_rsketch",
    "tangent": "make_constrain_tangent_rsketch",
    "concentric": "make_constrain_concentric_rsketch",
    "midpoint": "make_constrain_midpoint_rsketch",
    "symmetric": "make_constrain_symmetric_rsketch",
    "equal_length": "make_constrain_equal_length_rsketch",
    "equal_radius": "make_constrain_equal_radius_rsketch",
    "distance": "make_constrain_distance_rsketch",
    "distance_x": "make_constrain_distance_x_rsketch",
    "distance_y": "make_constrain_distance_y_rsketch",
    "length": "make_constrain_length_rsketch",
    "angle": "make_constrain_angle_rsketch",
    "radius": "make_constrain_radius_rsketch",
    "major_radius": "make_constrain_major_radius_rsketch",
    "minor_radius": "make_constrain_minor_radius_rsketch",
    "diameter": "make_constrain_diameter_rsketch",
    "fix": "make_constrain_fix_rsketch",
}

def _orthonormal_plane_axes(
    normal: Tuple[float, float, float],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    normal_vec = np.array(normal, dtype=float)
    norm = float(np.linalg.norm(normal_vec))
    if norm <= 1e-12:
        raise ValueError("法向量不能是零向量")
    z_axis = normal_vec / norm
    ref_vec = (
        np.array([1.0, 0.0, 0.0]) if abs(z_axis[2]) > 0.9 else np.array([0.0, 0.0, 1.0])
    )
    # In-plane x = ref projected onto the plane (Gram-Schmidt): for a +z normal
    # the frame is exactly the global (x, y, z), matching make_box_rsolid's
    # width-along-x convention. The ref branch above keeps ref away from z, so
    # the projection never degenerates.
    x_axis = ref_vec - float(ref_vec @ z_axis) * z_axis
    x_norm = float(np.linalg.norm(x_axis))
    if x_norm <= 1e-12:
        raise ValueError("无法根据给定法向量构建局部坐标系")
    x_axis = x_axis / x_norm
    y_axis = np.cross(z_axis, x_axis)
    y_axis = y_axis / float(np.linalg.norm(y_axis))
    return z_axis, x_axis, y_axis

def _sketch_plane_in_current_coordinates(
    plane: Any,
) -> Dict[str, Tuple[float, float, float]]:
    if isinstance(plane, str):
        token = plane.upper()
        frames = {
            "XY": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            "XZ": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            "YZ": ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        }
        if token not in frames:
            raise ValueError(
                "Sketch plane must be 'XY', 'XZ', 'YZ', or a plane mapping"
            )
        origin, x_axis, y_axis = frames[token]
    elif isinstance(plane, Mapping):
        origin = tuple(plane.get("origin", (0.0, 0.0, 0.0)))
        x_axis = tuple(plane.get("x_axis", (1.0, 0.0, 0.0)))
        y_axis = tuple(plane.get("y_axis", (0.0, 1.0, 0.0)))
    else:
        raise ValueError("Sketch plane must be 'XY', 'XZ', 'YZ', or a plane mapping")

    cs = get_current_cs()
    global_origin = cs.transform_point(np.asarray(origin, dtype=float))
    global_x_axis = cs.transform_vector(np.asarray(x_axis, dtype=float))
    global_y_axis = cs.transform_vector(np.asarray(y_axis, dtype=float))
    return {
        "origin": tuple(float(value) for value in global_origin),
        "x_axis": tuple(float(value) for value in global_x_axis),
        "y_axis": tuple(float(value) for value in global_y_axis),
    }

def _wrap_public_api_error(
    *,
    operation: str,
    what_happened: str,
    possible_causes: Sequence[str],
    how_to_fix: Sequence[str],
    error: BaseException,
    measurements: Sequence[ErrorMeasurement] = (),
    evidence: Sequence[ErrorEvidence] = (),
    repair: Sequence[str] = (),
    inventory: Sequence[InventoryEntry] = (),
) -> NoReturn:
    raise_harness_error(
        operation=operation,
        what_happened=what_happened,
        possible_causes=possible_causes,
        how_to_fix=how_to_fix,
        error=error,
        measurements=measurements,
        evidence=evidence,
        repair=repair,
        inventory=inventory,
    )

def _semantic_id_registry(kind: str) -> Set[str]:
    session = get_active_session()
    if session is None:
        return set()
    registry = getattr(session, "_simplecad_semantic_ids", None)
    if registry is None:
        registry = {}
        setattr(session, "_simplecad_semantic_ids", registry)
    return cast(Set[str], registry.setdefault(kind, set()))

def _reserve_semantic_id(kind: str, value: str) -> None:
    session = get_active_session()
    if session is None:
        return
    registry = _semantic_id_registry(kind)
    if value in registry:
        raise ValueError(f"duplicate {kind} id in active GraphSession: {value}")
    registry.add(value)

def _semantic_created(
    entity_type: str, entity_id: str, metadata: Optional[Dict[str, Any]] = None
) -> SemanticDelta:
    return SemanticDelta(
        created=(
            SemanticRef(
                graph_id="pending",
                node_id="pending",
                entity_type=entity_type,
                entity_id=entity_id,
            ),
        ),
        metadata=dict(metadata or {}),
    )

def _semantic_modified(
    entity_type: str, entity_id: str, metadata: Optional[Dict[str, Any]] = None
) -> SemanticDelta:
    return SemanticDelta(
        modified=(
            SemanticRef(
                graph_id="pending",
                node_id="pending",
                entity_type=entity_type,
                entity_id=entity_id,
            ),
        ),
        metadata=dict(metadata or {}),
    )

def _material_params(material: Material) -> Dict[str, object]:
    return material.to_dict()

def _part_params(part: Part) -> Dict[str, object]:
    return {"part_id": part.part_id, "name": part.name}

def _assembly_params(assembly: Assembly) -> Dict[str, object]:
    return {"assembly_id": assembly.assembly_id, "name": assembly.name}

def _connector_params(connector: Connector) -> Dict[str, object]:
    return connector.to_dict()

def _connector_ref_params(connector_ref: ConnectorRef) -> Dict[str, object]:
    return connector_ref.to_dict()

def _scalar_limit_params(limit: ScalarLimit) -> Dict[str, object]:
    return limit.to_dict()

def _constraint_params(constraint: Constraint) -> Dict[str, object]:
    return constraint.to_dict()

def _resolve_union_tol(
    solids: Sequence[Solid], tol: Optional[float]
) -> Optional[float]:
    """Resolve and validate the fuzzy tolerance for boolean union.

    The default is scale-aware and intentionally conservative.  An explicit
    tolerance is accepted only when it is finite and non-negative; silently
    forwarding NaN or a negative fuzzy value to OCC makes failures difficult
    to diagnose and can vary across kernel versions.
    """

    if tol is not None:
        resolved = float(tol)
        if not math.isfinite(resolved) or resolved < 0.0:
            raise ValueError("tol must be a finite non-negative number")
        return resolved

    bbox_min = np.array([np.inf, np.inf, np.inf], dtype=float)
    bbox_max = np.array([-np.inf, -np.inf, -np.inf], dtype=float)

    for solid in solids:
        bb = bounding_box(solid.wrapped)
        bbox_min = np.minimum(bbox_min, np.array([bb.xmin, bb.ymin, bb.zmin]))
        bbox_max = np.maximum(bbox_max, np.array([bb.xmax, bb.ymax, bb.zmax]))

    span = float(np.linalg.norm(bbox_max - bbox_min))
    if not np.isfinite(span) or span <= 0:
        return _DEFAULT_UNION_TOL_MIN

    return min(
        max(span * _DEFAULT_UNION_TOL_FACTOR, _DEFAULT_UNION_TOL_MIN),
        _DEFAULT_UNION_TOL_MAX,
    )

def _union_separation_diagnostic(
    results: Sequence[Solid], tol: Optional[float]
) -> Optional[str]:
    """Return a short diagnostic for multi-solid union results."""

    if len(results) < 2:
        return None

    effective_tol = float(tol or 0.0)
    nearest_gap_above_tol: Optional[float] = None

    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            gap = float(ocp_distance(results[i].wrapped, results[j].wrapped))
            if gap > effective_tol:
                if nearest_gap_above_tol is None or gap < nearest_gap_above_tol:
                    nearest_gap_above_tol = gap

    if nearest_gap_above_tol is None:
        return None

    return (
        f"union produced {len(results)} separated solids; "
        f"nearest detected gap is about {nearest_gap_above_tol:.6g}, "
        f"which exceeds tol={effective_tol:.6g}"
    )

def _require_union_solid(result_shape: Any, effective_tol: Optional[float]) -> Solid:
    result_shapes = solids_of(result_shape)
    if len(result_shapes) == 1:
        return Solid(result_shapes[0])

    failure_reason = "union did not produce a valid solid"
    diagnostic = _union_separation_diagnostic(
        [Solid(result) for result in result_shapes], effective_tol
    )
    if diagnostic:
        failure_reason = diagnostic
    elif len(result_shapes) > 1:
        failure_reason = (
            f"union produced {len(result_shapes)} solids at zero detected gap; "
            "the inputs likely meet only along an edge, vertex, tangent point, "
            "or tangent curve, which is not one manifold solid"
        )
    raise ValueError(failure_reason)

def _evaluate_tracked_union(
    solids: Sequence[Solid],
    *,
    glue: bool,
    tol: Optional[float],
    clean: bool,
) -> TrackedBooleanResult:
    fused = fuse_shapes_with_history(
        [solid.wrapped for solid in solids],
        glue=glue,
        tol=tol,
        clean=clean,
    )
    result = _require_union_solid(fused.shape, tol)
    return track_union_history(solids, result, fused.history, fused.section_edges)

def _flatten_boolean_solids(
    args: Sequence[Union[Solid, Sequence[Solid]]], operation_name: str
) -> List[Solid]:
    """Flatten nested boolean inputs into a validated solid list."""

    def _flatten(values: Sequence[Union[Solid, Sequence[Solid]]]) -> List[Solid]:
        flattened: List[Solid] = []
        for value in values:
            if isinstance(value, Solid):
                flattened.append(value)
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                flattened.extend(
                    _flatten(cast(Sequence[Union[Solid, Sequence[Solid]]], value))
                )
            else:
                raise ValueError(f"{operation_name}函数只接受Solid类型的对象")
        return flattened

    return _flatten(args)

def _require_single_boolean_solid(
    result_shapes: Sequence[Any],
    *,
    operation: str,
    failure_reason: str,
) -> Solid:
    if not result_shapes:
        raise ValueError(failure_reason)
    if len(result_shapes) != 1:
        raise ValueError(
            f"{operation} 期望得到单个Solid结果，但内核返回了 {len(result_shapes)} 个实体。"
        )
    return Solid(result_shapes[0])

def _merge_topo_deltas(deltas: Sequence[TopoDelta]) -> Optional[TopoDelta]:
    if not deltas:
        return None
    preserved: List[TopoRef] = []
    modified: List[TopoRef] = []
    generated: List[TopoRef] = []
    deleted: List[TopoRef] = []
    section_edges: List[TopoRef] = []
    entries: List[TopoEntry] = []
    raw_event: Dict[str, Any] = {"steps": []}

    for idx, delta in enumerate(deltas):
        preserved.extend(delta.preserved)
        modified.extend(delta.modified)
        generated.extend(delta.generated)
        deleted.extend(delta.deleted)
        section_edges.extend(delta.section_edges)
        entries.extend(delta.entries)
        raw_event["steps"].append(
            {
                "index": idx,
                "preserved": len(delta.preserved),
                "modified": len(delta.modified),
                "generated": len(delta.generated),
                "deleted": len(delta.deleted),
                "section_edges": len(delta.section_edges),
            }
        )

    return TopoDelta(
        preserved=tuple(preserved),
        modified=tuple(modified),
        generated=tuple(generated),
        deleted=tuple(deleted),
        section_edges=tuple(section_edges),
        entries=tuple(entries),
        raw_event=raw_event,
    )

def _copy_runtime_state(source: AnyShape, target: AnyShape) -> AnyShape:
    runtime = getattr(source, "_runtime", None)
    if isinstance(runtime, dict):
        # A transformed BRep owns a new evaluated geometry.  Copy semantic and
        # graph provenance, but never carry the source's geometry-dependent
        # mesh or mesh error into the new wrapper.
        target._runtime = {
            key: value
            for key, value in runtime.items()
            if not key == "mesh.error"
            and not key == "mesh.default"
            and not key.startswith("mesh:")
        }
    return target

def _attach_lineage_from_source(
    source: AnyShape,
    target: AnyShape,
    *,
    derivation: str,
    op: str,
    coverage: str = "complete",
) -> None:
    coverage_rank = {"complete": 0, "partial": 1, "none": 2}

    def aggregate(*values: object) -> str:
        normalized = [str(value) for value in values if value in coverage_rank]
        return (
            max(normalized, key=coverage_rank.__getitem__) if normalized else "complete"
        )

    effective_coverage = aggregate(
        coverage,
        source._get_runtime("semantic.lineage.coverage"),
    )
    bindings = {
        binding.binding_id: (binding, effective_coverage)
        for binding in source._local_tag_bindings()
        if lineage_policy_allows(binding.propagation, derivation)
    }
    for witness in source._tag_lineage:
        if not lineage_policy_allows(
            witness.binding.propagation, witness.derivation
        ) or not lineage_policy_allows(witness.binding.propagation, derivation):
            continue
        existing = bindings.get(witness.binding.binding_id)
        witness_coverage = aggregate(effective_coverage, witness.coverage)
        bindings[witness.binding.binding_id] = (
            witness.binding,
            aggregate(existing[1], witness_coverage) if existing else witness_coverage,
        )
    for binding, binding_coverage in bindings.values():
        evidence = TagEvidence(
            "topology_change",
            {
                "op": op,
                "derivation": derivation,
                "coverage": binding_coverage,
            },
        )
        target._add_tag_lineage(
            binding,
            derivation=derivation,
            source_topo_id=source.topo_id,
            evidence=evidence,
            coverage=binding_coverage,
        )
    target._set_runtime(
        "semantic.lineage.coverage",
        aggregate(
            target._get_runtime("semantic.lineage.coverage"),
            effective_coverage,
        ),
    )

def _current_context_metadata() -> Dict[str, Tuple[float, float, float]]:
    cs = get_current_cs()
    return {
        "origin": (float(cs.origin[0]), float(cs.origin[1]), float(cs.origin[2])),
        "x_axis": (float(cs.x_axis[0]), float(cs.x_axis[1]), float(cs.x_axis[2])),
        "y_axis": (float(cs.y_axis[0]), float(cs.y_axis[1]), float(cs.y_axis[2])),
        "z_axis": (float(cs.z_axis[0]), float(cs.z_axis[1]), float(cs.z_axis[2])),
    }

def _attach_track_summary(
    shape: AnyShape,
    *,
    op: str,
    delta: Optional[object] = None,
    delta_entries: Optional[Dict[str, Dict[str, object]]] = None,
) -> AnyShape:
    track_payload: Dict[str, object] = {"op": op}
    if delta is not None:
        track_payload["has_delta"] = True
        track_payload["preserved"] = len(getattr(delta, "preserved", ()))
        track_payload["modified"] = len(getattr(delta, "modified", ()))
        track_payload["generated"] = len(getattr(delta, "generated", ()))
        track_payload["deleted"] = len(getattr(delta, "deleted", ()))
    if delta_entries:
        track_payload["entry_count"] = len(delta_entries)
    shape.set_metadata("track", track_payload)
    return shape

def _vector_like_to_tuple(value: Any) -> Optional[Tuple[float, float, float]]:
    if value is None:
        return None
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return (float(value.x), float(value.y), float(value.z))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    return None

def _make_selector_hint(shape: AnyShape) -> Dict[str, object]:
    hint: Dict[str, object] = {
        "kind": type(shape).__name__.lower(),
        "tags": shape._list_tags(),
    }

    if isinstance(shape, Edge):
        hint["length"] = float(shape.get_length())
        try:
            hint["start"] = tuple(
                float(v) for v in shape.get_start_vertex().get_coordinates()
            )
            hint["end"] = tuple(
                float(v) for v in shape.get_end_vertex().get_coordinates()
            )
        except Exception:
            center = getattr(shape.wrapped, "Center", lambda: None)()
            center_tuple = _vector_like_to_tuple(center)
            if center_tuple is not None:
                hint["center"] = center_tuple
    elif isinstance(shape, Face):
        hint["area"] = float(shape.get_area())
        center_tuple = _vector_like_to_tuple(shape.get_center())
        normal_tuple = _vector_like_to_tuple(shape.get_normal_at())
        if center_tuple is not None:
            hint["center"] = center_tuple
        if normal_tuple is not None:
            hint["normal"] = normal_tuple
    elif isinstance(shape, Wire):
        hint["edge_count"] = len(shape._iter_edges())
        hint["closed"] = bool(shape.is_closed())
    elif isinstance(shape, Vertex):
        hint["coordinates"] = tuple(float(v) for v in shape.get_coordinates())
    elif isinstance(shape, Shell):
        hint["face_count"] = len(shape._iter_faces())
        bb = bounding_box(shape.wrapped)
        hint["bbox"] = {
            "min": (float(bb.xmin), float(bb.ymin), float(bb.zmin)),
            "max": (float(bb.xmax), float(bb.ymax), float(bb.zmax)),
        }
    elif isinstance(shape, Solid):
        hint["volume"] = float(shape.get_volume())
        bb = bounding_box(shape.wrapped)
        hint["bbox"] = {
            "min": (float(bb.xmin), float(bb.ymin), float(bb.zmin)),
            "max": (float(bb.xmax), float(bb.ymax), float(bb.zmax)),
        }
    elif isinstance(shape, Compound):
        hint["volume"] = float(shape.get_volume())
        hint["solid_count"] = len(shape._iter_solids())
        bb = bounding_box(shape.wrapped)
        hint["bbox"] = {
            "min": (float(bb.xmin), float(bb.ymin), float(bb.zmin)),
            "max": (float(bb.xmax), float(bb.ymax), float(bb.zmax)),
        }

    return hint

def _jsonable_geo_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (int, float)):
        return value
    to_tuple = getattr(value, "to_tuple", None)
    if callable(to_tuple):
        try:
            return [float(v) for v in to_tuple()]
        except Exception:
            pass
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        try:
            return [float(value.x), float(value.y), float(value.z)]
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): _jsonable_geo_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_geo_value(v) for v in value]
    return str(value)

def _bbox_selector_payload(shape: AnyShape) -> Optional[Dict[str, List[float]]]:
    try:
        bb = bounding_box(shape.wrapped)
        return {
            "min": [float(bb.xmin), float(bb.ymin), float(bb.zmin)],
            "max": [float(bb.xmax), float(bb.ymax), float(bb.zmax)],
        }
    except Exception:
        return None

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

def _selection_op_for_shape(shape: AnyShape) -> Optional[str]:
    if isinstance(shape, Vertex):
        return _OP_MAKE_SELECT_RVERTEX
    if isinstance(shape, Edge):
        return _OP_MAKE_SELECT_REDGE
    if isinstance(shape, Wire):
        return _OP_MAKE_SELECT_RWIRE
    if isinstance(shape, Face):
        return _OP_MAKE_SELECT_RFACE
    if isinstance(shape, Shell):
        return _OP_MAKE_SELECT_RSHELL
    if isinstance(shape, Solid):
        return _OP_MAKE_SELECT_RSOLID
    return None

def _candidate_shapes_for_selection(source: AnyShape, kind: str) -> List[AnyShape]:
    if kind == "edge":
        if hasattr(source, "get_edges"):
            return list(source._iter_edges())
        return [source] if isinstance(source, Edge) else []
    if kind == "face":
        if isinstance(source, (Shell, Solid, Compound)):
            return list(source._iter_faces())
        return [source] if isinstance(source, Face) else []
    if kind == "wire":
        if isinstance(source, Face):
            return [source.get_outer_wire(), *source._iter_inner_wires()]
        if hasattr(source, "get_children"):
            return [
                cast(AnyShape, child)
                for child in source.get_children()
                if isinstance(child, Wire)
            ]
        return [source] if isinstance(source, Wire) else []
    if kind == "vertex":
        if isinstance(source, Edge):
            return source.get_children()
        if hasattr(source, "get_children"):
            return [
                cast(AnyShape, child)
                for child in source.get_children()
                if isinstance(child, Vertex)
            ]
        return [source] if isinstance(source, Vertex) else []
    if kind == "shell":
        if isinstance(source, Compound):
            return [
                cast(AnyShape, child)
                for child in source.get_children()
                if isinstance(child, Shell)
            ]
        return [source] if isinstance(source, Shell) else []
    if kind == "solid":
        if isinstance(source, Compound):
            return cast(List[AnyShape], source._iter_solids())
        return [source] if isinstance(source, Solid) else []
    if kind == "compound":
        return [source] if isinstance(source, Compound) else []
    return []

def _source_selection_index(
    source: AnyShape, selected: AnyShape, *, kind: str
) -> Optional[int]:
    for idx, candidate in enumerate(_candidate_shapes_for_selection(source, kind)):
        try:
            if candidate.same_topology(selected):
                return idx
        except Exception:
            pass
        if getattr(candidate, "topo_id", None) == getattr(selected, "topo_id", None):
            return idx
    return None

def _make_geo_selector(
    shape: AnyShape,
    *,
    source_shape: Optional[AnyShape] = None,
) -> Dict[str, object]:
    kind = _shape_kind_token(shape)
    selector: Dict[str, object] = {
        "mode": "geo_exact",
        "kind": kind,
        "metadata_geo": _jsonable_geo_value(shape.get_metadata("geo", {})),
    }
    provenance = shape.get_metadata("provenance")
    if isinstance(shape, Face) and isinstance(provenance, dict):
        artifact_sha256 = provenance.get("artifact_sha256")
        source_face_id = provenance.get("source_face_id")
        if isinstance(artifact_sha256, str) and isinstance(source_face_id, str):
            selector["brep_region_ref"] = {
                "artifact_sha256": artifact_sha256,
                "source_face_id": source_face_id,
            }
    # `source_shape` is intentionally not serialized as a source index. The
    # canonical selector is geometry-based; source lineage comes from graph inputs.

    bbox_payload = _bbox_selector_payload(shape)
    if bbox_payload is not None:
        selector["bbox"] = bbox_payload

    geom_type = _shape_geom_type(shape)
    if geom_type is not None:
        selector["geom_type"] = geom_type

    if isinstance(shape, Vertex):
        selector["coordinates"] = [float(v) for v in shape.get_coordinates()]
    elif isinstance(shape, Edge):
        selector["length"] = float(shape.get_length())
        center = shape.get_center()
        selector["center"] = [float(center.x), float(center.y), float(center.z)]
        try:
            selector["start"] = [
                float(v) for v in shape.get_start_vertex().get_coordinates()
            ]
            selector["end"] = [
                float(v) for v in shape.get_end_vertex().get_coordinates()
            ]
        except Exception:
            pass
    elif isinstance(shape, Wire):
        selector["edge_count"] = len(shape._iter_edges())
        selector["closed"] = bool(shape.is_closed())
    elif isinstance(shape, Face):
        selector["area"] = float(shape.get_area())
        center = shape.get_center()
        normal = shape.get_normal_at()
        selector["center"] = [float(center.x), float(center.y), float(center.z)]
        selector["normal"] = [float(normal.x), float(normal.y), float(normal.z)]
        selector["edge_count"] = len(shape._iter_edges())
        selector["inner_wire_count"] = len(shape._iter_inner_wires())
    elif isinstance(shape, Shell):
        selector["face_count"] = len(shape._iter_faces())
    elif isinstance(shape, Solid):
        selector["volume"] = float(shape.get_volume())
        get_center = getattr(shape, "get_center", None)
        center = get_center() if callable(get_center) else None
        if center is not None:
            selector["center"] = [float(center.x), float(center.y), float(center.z)]
    elif isinstance(shape, Compound):
        selector["volume"] = float(shape.get_volume())
        selector["solid_count"] = len(shape._iter_solids())
    return selector

def _record_geo_selection_nodes(
    source_shape: AnyShape,
    selected_shapes: Sequence[AnyShape],
) -> List[str]:
    session = get_active_session()
    if session is None:
        return []
    source_node = source_shape._get_runtime("graph.node")
    if source_node is None:
        return []

    node_ids: List[str] = []
    for selected in selected_shapes:
        op = _selection_op_for_shape(selected)
        if op is None:
            continue
        kind = _shape_kind_token(selected)
        selected_node = _active_graph_node_for_shape(selected)
        inputs = [source_node]
        if (
            selected_node is not None
            and getattr(selected_node, "op", None) == _OP_APPLY_TAG_RSELECTION
            and selected_node is not source_node
        ):
            inputs.append(selected_node)
        node = record_operation(
            op=op,
            params={
                "target_kind": kind,
                "geo_selector": _make_geo_selector(
                    selected,
                    source_shape=source_shape,
                ),
            },
            inputs=inputs,
            output_count=1,
            semantic_delta=_semantic_delta_for_output(op, entity_type="Selection"),
            context=_current_context_metadata(),
        )
        attach_graph_node(
            selected,
            node,
            output_slot=0,
            graph_id=session.graph.graph_id,
        )
        node_ids.append(node.node_id)
    return node_ids

_GEO_SELECT_OPS = {
    _OP_MAKE_SELECT_RVERTEX,
    _OP_MAKE_SELECT_REDGE,
    _OP_MAKE_SELECT_RWIRE,
    _OP_MAKE_SELECT_RFACE,
    _OP_MAKE_SELECT_RSHELL,
    _OP_MAKE_SELECT_RSOLID,
}

def _is_geo_select_node(node: object) -> bool:
    return getattr(node, "op", None) in _GEO_SELECT_OPS

def _ensure_source_shape_has_own_selection_node(
    source_shape: AnyShape,
) -> Optional[object]:
    source_node = _active_graph_node_for_shape(source_shape)
    if (
        source_node is None
        or _is_geo_select_node(source_node)
        or getattr(source_node, "op", None) == _OP_APPLY_TAG_RSELECTION
    ):
        return source_node

    parent_source = _selection_source_for_shape(source_shape)
    if parent_source is None:
        return source_node

    _ensure_geo_selection_node_ids(parent_source, [source_shape])
    return _active_graph_node_for_shape(source_shape)

def _ensure_geo_selection_node_ids(
    source_shape: AnyShape,
    selected_shapes: Sequence[AnyShape],
) -> List[str]:
    session = get_active_session()
    if session is None:
        return []
    source_node = _ensure_source_shape_has_own_selection_node(source_shape)
    if source_node is None:
        return []

    node_ids: List[str] = []
    for selected in selected_shapes:
        existing_node = _active_graph_node_for_shape(selected)
        existing_op = getattr(existing_node, "op", None)
        if existing_node is not None and existing_op in _GEO_SELECT_OPS:
            node_ids.append(str(existing_node.node_id))
            continue
        node_ids.extend(_record_geo_selection_nodes(source_shape, [selected]))
    return node_ids

def _active_graph_node_for_shape(shape: AnyShape) -> Optional[object]:
    session = get_active_session()
    if session is None:
        return None
    node = shape._get_runtime("graph.node")
    node_id = getattr(node, "node_id", None)
    if node_id is None:
        return None
    if session.graph.get_node(str(node_id)) is not None:
        return node
    # A shape from an earlier notebook cell was recorded by that cell's
    # session. A shared-lineage session adopts it, as it does for operator
    # inputs; any other session does not own it.
    if not isinstance(node, OperationNode) or node.graph_id != session.graph.graph_id:
        return None
    try:
        return session.owned_node(node)
    except StaleLineageError:
        raise
    except ValueError:
        return None

def _parent_shapes(shape: AnyShape) -> List[AnyShape]:
    parents: List[AnyShape] = []
    get_parent = getattr(shape, "get_parent", None)
    if callable(get_parent):
        parent = get_parent()
        if parent is not None:
            parents.append(cast(AnyShape, parent))
    get_parents = getattr(shape, "get_parents", None)
    if callable(get_parents):
        for parent in get_parents():
            if parent is not None:
                parents.append(cast(AnyShape, parent))
    return parents

def _selection_source_for_shape(shape: AnyShape) -> Optional[AnyShape]:
    kind = _shape_kind_token(shape)
    seen: Set[int] = set()
    stack = _parent_shapes(shape)

    while stack:
        source = stack.pop(0)
        marker = id(source)
        if marker in seen or source is shape:
            continue
        seen.add(marker)

        if _source_selection_index(source, shape, kind=kind) is not None:
            if _active_graph_node_for_shape(source) is not None:
                return source

        stack.extend(_parent_shapes(source))

    return None

def _ensure_geo_selection_input_nodes(
    input_shapes: Optional[Sequence[AnyShape]],
) -> Optional[Sequence[AnyShape]]:
    if not input_shapes:
        return input_shapes

    for shape in input_shapes:
        if _active_graph_node_for_shape(shape) is not None:
            continue
        source = _selection_source_for_shape(shape)
        if source is not None:
            _ensure_geo_selection_node_ids(source, [shape])
    return input_shapes

def _serialize_shape_ref(shape: AnyShape) -> Optional[Dict[str, object]]:
    topo_ref = shape._get_runtime("topo.ref")
    if isinstance(topo_ref, TopoRef):
        data = cast(Dict[str, object], topo_ref_to_dict(topo_ref))
        data["selector_hint"] = _make_selector_hint(shape)
        return data

    topo_ref_meta = shape.get_metadata("topo_ref")
    if isinstance(topo_ref_meta, dict):
        data = cast(Dict[str, object], dict(topo_ref_meta))
        data["selector_hint"] = _make_selector_hint(shape)
        return data

    return None

def _serialize_shape_refs(shapes: Sequence[AnyShape]) -> List[Dict[str, object]]:
    refs: List[Dict[str, object]] = []
    for shape in shapes:
        ref = _serialize_shape_ref(shape)
        if ref is not None:
            refs.append(ref)
    return refs

def _shape_ref_topo_id(shape: AnyShape) -> Optional[str]:
    ref = _serialize_shape_ref(shape)
    if ref is None:
        return None
    topo_id = ref.get("topo_id")
    return str(topo_id) if topo_id is not None else None

def _serialize_selection_indices(
    selected_shapes: Sequence[AnyShape],
    candidates: Sequence[AnyShape],
) -> List[int]:
    candidate_index_by_topo_id: Dict[str, int] = {}
    for idx, candidate in enumerate(candidates):
        topo_id = _shape_ref_topo_id(candidate)
        if topo_id is not None and topo_id not in candidate_index_by_topo_id:
            candidate_index_by_topo_id[topo_id] = idx

    result: List[int] = []
    for selected in selected_shapes:
        topo_id = _shape_ref_topo_id(selected)
        if topo_id is None:
            continue
        if topo_id in candidate_index_by_topo_id:
            result.append(candidate_index_by_topo_id[topo_id])
    return result

def _resolve_selector_or_shapes(
    scope: AnyShape,
    selection: Union[Sequence[AnyShape], ShapeSelector],
) -> List[AnyShape]:
    if isinstance(selection, ShapeSelector):
        return cast(List[AnyShape], selection.resolve(scope))
    return list(selection)

def _semantic_delta_for_output(
    op: str, output_count: int = 1, entity_type: Optional[str] = None
) -> SemanticDelta:
    resolved_entity_type = entity_type
    if resolved_entity_type is None:
        if op in {
            "make_point",
            _OP_MAKE_POINT_RVERTEX,
        }:
            resolved_entity_type = "Point"
        elif op in {
            _OP_MAKE_SKETCH_RSKETCH,
            _OP_ADD_POINT_RSKETCH,
            _OP_ADD_LINE_RSKETCH,
            _OP_ADD_CIRCLE_RSKETCH,
            _OP_ADD_ARC_RSKETCH,
            _OP_ADD_BSPLINE_RSKETCH,
            _OP_MAKE_WIRE_FROM_SKETCH_RWIRE,
            _OP_MAKE_FACE_FROM_SKETCH_RFACE,
            *_SKETCH_CONSTRAINT_OPS.values(),
        }:
            resolved_entity_type = "Sketch"
        elif op in {
            "make_line",
            "make_circle_edge",
            "make_circle_wire",
            "make_circle_face",
            "make_rectangle_wire",
            "make_rectangle_face",
            "make_segment_wire",
            "make_three_point_arc",
            "make_three_point_arc_wire",
            "make_angle_arc",
            "make_angle_arc_wire",
            "make_spline",
            "make_spline_wire",
            "make_polyline_wire",
            "make_helix",
            "make_helix_wire",
            "make_face_from_wire",
            "make_wire_from_edges",
            _OP_MAKE_LINE_REDGE,
            _OP_MAKE_CIRCLE_REDGE,
            _OP_MAKE_THREE_POINT_ARC_REDGE,
            _OP_MAKE_ANGLE_ARC_REDGE,
            _OP_MAKE_SPLINE_REDGE,
            _OP_MAKE_HELIX_REDGE,
            _OP_MAKE_FACE_FROM_WIRE_RFACE,
            _OP_MAKE_WIRE_FROM_EDGES_RWIRE,
        }:
            if op.endswith("_face") or op in {
                "make_face_from_wire",
                _OP_MAKE_FACE_FROM_WIRE_RFACE,
            }:
                resolved_entity_type = "Sketch"
            else:
                resolved_entity_type = "Profile"
        elif op in {
            "make_box",
            "make_cylinder",
            "make_cone",
            "make_sphere",
            "make_box_rsolid",
            "make_cylinder_rsolid",
            "make_cone_rsolid",
            "make_sphere_rsolid",
            "extrude",
            "revolve",
            "loft",
            "sweep",
            "helical_sweep",
            "fillet",
            "chamfer",
            "shell",
            "cut",
            "union",
            "intersect",
            "translate",
            "rotate",
            "mirror",
            _OP_MAKE_EXTRUDE_RSOLID,
            _OP_MAKE_REVOLVE_RSOLID,
            _OP_MAKE_LOFT_RSOLID,
            _OP_MAKE_SWEEP_RSOLID,
            _OP_MAKE_TWISTED_SWEEP_RSOLID,
            _OP_MAKE_FILLET_RSOLID,
            _OP_MAKE_CHAMFER_RSOLID,
            _OP_MAKE_SHELL_RSOLID,
            _OP_MAKE_CUT_RSOLID,
            _OP_MAKE_UNION_RSOLID,
            _OP_MAKE_INTERSECT_RSOLID,
            _OP_MAKE_TRANSLATE_RSHAPE,
            _OP_MAKE_ROTATE_RSHAPE,
            _OP_MAKE_MIRROR_RSHAPE,
            _OP_LOAD_BREP_REGION_RSOLID,
        }:
            if op in {
                "extrude",
                "revolve",
                "loft",
                "sweep",
                "fillet",
                "chamfer",
                "shell",
                "cut",
                "union",
                "intersect",
                _OP_MAKE_EXTRUDE_RSOLID,
                _OP_MAKE_REVOLVE_RSOLID,
                _OP_MAKE_LOFT_RSOLID,
                _OP_MAKE_SWEEP_RSOLID,
                _OP_MAKE_TWISTED_SWEEP_RSOLID,
                _OP_MAKE_FILLET_RSOLID,
                _OP_MAKE_CHAMFER_RSOLID,
                _OP_MAKE_SHELL_RSOLID,
                _OP_MAKE_CUT_RSOLID,
                _OP_MAKE_UNION_RSOLID,
                _OP_MAKE_INTERSECT_RSOLID,
            }:
                resolved_entity_type = "Feature"
            else:
                resolved_entity_type = "Body"
        else:
            resolved_entity_type = "ShapeOutput"

    refs = tuple(
        SemanticRef(
            graph_id="pending",
            node_id="pending",
            entity_type=resolved_entity_type,
            entity_id=f"{op}:{slot}",
        )
        for slot in range(output_count)
    )
    return SemanticDelta(created=refs, metadata={"op": op})

def _finalize_primitive_shape(
    shape: AnyShape,
    *,
    op: str,
    params: Dict[str, object],
    tags: Optional[Set[str]] = None,
) -> AnyShape:
    _attach_track_summary(shape, op=op)
    record_operation_if_active(
        op=op,
        params=params,
        outputs=shape,
        semantic_delta=_semantic_delta_for_output(op),
        context=_current_context_metadata(),
        tags=tags,
    )
    return shape

def _finalize_primitive_solid(
    solid: Solid,
    *,
    op: str,
    params: Dict[str, object],
    tags: Optional[Set[str]] = None,
) -> Solid:
    return cast(
        Solid,
        _finalize_primitive_shape(solid, op=op, params=params, tags=tags),
    )

def _topology_identity_payload(binding: TagBinding) -> Optional[Dict[str, Any]]:
    for key in ("topology_name", "source_topology_name"):
        value = binding.evidence.data.get(key)
        if isinstance(value, dict):
            return value
    return None

def _copy_exact_topology_identity_tags(
    target: AnyShape,
    sources: Sequence[AnyShape],
    *,
    operation: str,
) -> AnyShape:
    source_members = [
        member
        for source in sources
        for member in (source._iter_edges() if hasattr(source, "get_edges") else [source])
        if isinstance(member, Edge)
    ]
    target_members = target._iter_edges() if hasattr(target, "get_edges") else [target]
    result = target
    for target_member in target_members:
        if not isinstance(target_member, Edge):
            continue
        matches = [
            source
            for source in source_members
            if source.wrapped.IsSame(target_member.wrapped)
        ]
        if len(matches) != 1:
            continue
        source = matches[0]
        for binding in source._local_tag_bindings():
            topology_identity = _topology_identity_payload(binding)
            if topology_identity is None:
                continue
            local_name = topology_identity.get("local_name")
            if not isinstance(local_name, str) or not local_name:
                continue
            result = _apply_topology_identity_tag(
                result,
                [target_member],
                binding.tag,
                kind="edge",
                local_name=local_name,
                authoring_source=f"simplecadapi.{operation}.identity_tag",
            )
    return result

def _apply_topology_identity_tag(
    scope: AnyShape,
    targets: Union[ShapeSelector, Sequence[AnyShape]],
    tag: str,
    *,
    kind: str,
    local_name: str,
    authoring_source: str,
) -> AnyShape:
    normalized = normalize_tag(tag, strict=True)
    return _apply_tag_rselection(
        scope,
        targets,
        normalized,
        (TopologyPropagation.DOWNWARD if kind == "face" else TopologyPropagation.LOCAL),
        LineagePolicy.CONTINUATION_FRAGMENT,
        authoring_source=authoring_source,
        extra_evidence={
            "topology_name": {
                "kind": kind,
                "name": normalized,
                "local_name": normalize_tag(local_name, strict=True),
            }
        },
    )

def _apply_shape_tag_prefix(
    shape: AnyShape,
    tag_prefix: Optional[str],
    *,
    kind: str,
    authoring_source: str,
) -> AnyShape:
    if tag_prefix is None:
        return shape
    prefix = normalize_tag(tag_prefix, strict=True)
    tag = f"{prefix}.{kind}"
    return _apply_topology_identity_tag(
        shape,
        ShapeSelector(kind).exactly(1),
        tag,
        kind=kind,
        local_name=kind,
        authoring_source=authoring_source,
    )

def _apply_profile_tag_prefix(
    shape: Union[Wire, Face],
    tag_prefix: Optional[str],
    edge_tags: Optional[Sequence[str]],
    *,
    authoring_source: str,
) -> Union[Wire, Face]:
    if tag_prefix is None and edge_tags is None:
        return shape
    prefix = normalize_tag(tag_prefix, strict=True) if tag_prefix is not None else None
    result: AnyShape = (
        _apply_shape_tag_prefix(
            shape,
            prefix,
            kind=shape.__class__.__name__.lower(),
            authoring_source=authoring_source,
        )
        if prefix is not None
        else shape
    )
    edges = list(shape._iter_edges())
    local_names = (
        [str(value) for value in edge_tags]
        if edge_tags is not None
        else [f"line{index + 1}" for index in range(len(edges))]
    )
    if len(local_names) != len(edges):
        raise ValueError(
            f"edge_tags must contain exactly {len(edges)} tags, got {len(local_names)}"
        )
    for edge, raw_local_name in zip(edges, local_names):
        local_name = normalize_tag(raw_local_name, strict=True)
        edge_tag = f"{prefix}.edge.{local_name}" if prefix else local_name
        result = _apply_topology_identity_tag(
            result,
            [edge],
            edge_tag,
            kind="edge",
            local_name=local_name,
            authoring_source=authoring_source,
        )
    return cast(Union[Wire, Face], result)

def _finalize_derived_shape(
    shape: AnyShape,
    *,
    op: str,
    params: Dict[str, object],
    input_shapes: Sequence[AnyShape],
    tags: Optional[Set[str]] = None,
    topo_delta: Optional[TopoDelta] = None,
) -> AnyShape:
    _attach_track_summary(shape, op=op)
    prepared_inputs = list(_ensure_geo_selection_input_nodes(input_shapes) or ())
    recorded_params = dict(params)
    if get_active_session() is not None and op in {
        "make_ruled_surface_rface",
        "make_gordon_surface_rface",
        "make_surface_patch_rface",
        "trim_surface_rface",
        "make_loft_rshell",
        "sew_faces_rshell",
        "make_solid_from_shell_rsolid",
        "fill_holes_rshell",
    }:
        input_refs = _serialize_shape_refs(prepared_inputs)
        if len(input_refs) != len(prepared_inputs):
            raise ValueError(
                f"{op} requires every ordered input to have a graph reference"
            )
        recorded_params["input_refs"] = input_refs
    record_operation_if_active(
        op=op,
        params=recorded_params,
        outputs=shape,
        input_shapes=prepared_inputs,
        semantic_delta=_semantic_delta_for_output(op),
        topo_delta=topo_delta,
        context=_current_context_metadata(),
        tags=tags,
    )
    return shape

def _finalize_runtime_object(
    output: object,
    *,
    op: str,
    params: Dict[str, object],
    input_objects: Optional[Sequence[object]] = None,
    tags: Optional[Set[str]] = None,
    entity_type: str = "Sketch",
) -> object:
    record_operation_if_active(
        op=op,
        params=params,
        outputs=output,
        input_shapes=input_objects,
        semantic_delta=_semantic_delta_for_output(op, entity_type=entity_type),
        context=_current_context_metadata(),
        tags=tags,
    )
    return output

def _finalize_tracked_solid(
    solid: Solid,
    *,
    op: str,
    params: Dict[str, object],
    source_solid: Optional[Solid] = None,
    source_solids: Optional[Sequence[Solid]] = None,
    delta: Optional[object] = None,
    delta_entries: Optional[Dict[str, Dict[str, object]]] = None,
    input_shapes: Optional[Sequence[AnyShape]] = None,
) -> Solid:
    if current_tracking_policy() == TrackingPolicy.GRAPH:
        delta = None
        delta_entries = None
    if delta is not None:
        apply_tracking_tags_to_delta(
            solid,
            cast(TopoDelta, delta),
            cast(Optional[Dict[str, Dict[str, Any]]], delta_entries),
            op=op,
            source_solid=source_solid,
            source_solids=source_solids,
            source_shapes=input_shapes,
        )
    _attach_track_summary(
        solid,
        op=op,
        delta=delta,
        delta_entries=delta_entries,
    )
    record_operation_if_active(
        op=op,
        params=params,
        outputs=solid,
        input_shapes=_ensure_geo_selection_input_nodes(input_shapes),
        semantic_delta=_semantic_delta_for_output(op),
        topo_delta=cast(Optional[TopoDelta], delta),
        context=_current_context_metadata(),
    )
    return solid

def _normalize_operation_role_tags(
    op: str,
    named_tags: Sequence[Tuple[str, Optional[str]]],
) -> List[Tuple[str, str, str]]:
    role_specs = _OPERATION_OUTPUT_ROLE_CARDINALITY[op]
    cardinality_by_role = dict(role_specs)
    requested: Dict[str, str] = {}

    for role, raw_tag in named_tags:
        if raw_tag is None:
            continue
        if role in requested:
            raise ValueError(f"duplicate role tag assignment: {role}")
        requested[role] = normalize_tag(raw_tag, strict=True)

    unknown = sorted(set(requested) - set(cardinality_by_role))
    if unknown:
        raise ValueError(
            f"unsupported output role(s) for {op}: {', '.join(unknown)}; "
            f"expected one of {', '.join(cardinality_by_role)}"
        )
    return [
        (role, cardinality, requested[role])
        for role, cardinality in role_specs
        if role in requested
    ]

def _validate_operation_output_roles(
    delta: TopoDelta,
    assignments: Sequence[Tuple[str, str, str]],
) -> Dict[str, str]:
    target_kinds: Dict[str, str] = {}
    for role, cardinality, _tag in assignments:
        role_entries = {
            (entry.ref, entry.ref.kind.name.lower())
            for entry in delta.roles
            if entry.role == role
            and str(entry.metadata.get("coverage", "complete")).lower() == "complete"
            and str(entry.metadata.get("status", "proven")).lower() == "proven"
        }
        refs = {ref for ref, _kind in role_entries}
        kinds = {kind for _ref, kind in role_entries}
        if cardinality == "one" and len(refs) != 1:
            raise SemanticCapabilityError(
                f"operation output role '{role}' requires exactly one kernel-proven result, got {len(refs)}"
            )
        if cardinality == "many" and not refs:
            raise SemanticCapabilityError(
                f"operation output role '{role}' requires at least one kernel-proven result"
            )
        if len(kinds) != 1:
            raise SemanticCapabilityError(
                f"operation output role '{role}' does not resolve to one topology kind"
            )
        target_kinds[role] = next(iter(kinds))
    return target_kinds

def _apply_operation_role_tags(
    shape: AnyShape,
    *,
    op: str,
    assignments: Sequence[Tuple[str, str, str]],
    target_kinds: Mapping[str, str],
    result_tag: Optional[str] = None,
) -> AnyShape:
    if not assignments and result_tag is None:
        return shape

    role_source_node = _active_graph_node_for_shape(shape)
    role_source_slot = int(shape._get_runtime("graph.output_slot", 0))
    result: AnyShape = shape
    for role, cardinality, tag in assignments:
        selector = ShapeSelector(target_kinds[role]).where(output_role(role))
        selector = selector.exactly(1) if cardinality == "one" else selector.at_least(1)
        result = _apply_tag_rselection(
            result,
            selector,
            tag,
            TopologyPropagation.LOCAL,
            LineagePolicy.CONTINUATION_FRAGMENT,
            authoring_source=f"simplecadapi.{op}.role_tag",
            extra_evidence={
                "operation_output_role": {
                    "source_node_id": (
                        role_source_node.node_id
                        if role_source_node is not None
                        else None
                    ),
                    "source_output_slot": role_source_slot,
                    "operation": op,
                    "role": role,
                    "cardinality": cardinality,
                }
            },
        )
    if result_tag is not None:
        result = _apply_tag_rselection(
            result,
            ShapeSelector(_shape_kind_token(shape)).exactly(1),
            result_tag,
            TopologyPropagation.LOCAL,
            LineagePolicy.CONTINUATION_FRAGMENT,
            authoring_source=f"simplecadapi.{op}.result_tag",
            extra_evidence={
                "operation_result": {
                    "source_node_id": (
                        role_source_node.node_id
                        if role_source_node is not None
                        else None
                    ),
                    "source_output_slot": role_source_slot,
                    "operation": op,
                }
            },
        )
    return result

def _topology_identity_local_name(shape: AnyShape) -> Optional[str]:
    for binding in shape._local_tag_bindings():
        payload = _topology_identity_payload(binding)
        if (
            payload is not None
            and payload.get("kind") == shape.__class__.__name__.lower()
        ):
            local_name = payload.get("local_name")
            if isinstance(local_name, str) and local_name:
                return local_name
    return None

def _apply_feature_tag_prefix(
    solid: Solid,
    *,
    tag_prefix: Optional[str],
    op: str,
    delta: TopoDelta,
    start_role: Optional[str] = None,
    end_role: Optional[str] = None,
    side_role: Optional[str] = None,
    source_shapes: Sequence[AnyShape] = (),
    edge_roles: Sequence[Tuple[str, str]] = (),
    face_roles: Sequence[Tuple[str, str]] = (),
) -> Solid:
    if tag_prefix is None:
        return solid
    prefix = normalize_tag(tag_prefix, strict=True)
    result: AnyShape = _apply_topology_identity_tag(
        solid,
        ShapeSelector("solid").exactly(1),
        f"{prefix}.solid",
        kind="solid",
        local_name="solid",
        authoring_source=f"simplecadapi.{op}.tag_prefix",
    )

    for role, local_name in (
        (start_role, "start"),
        (end_role, "end"),
        (side_role, "side"),
    ):
        if role is None:
            continue
        cardinality = "one" if local_name in {"start", "end"} else "many"
        selector = ShapeSelector("face").where(output_role(role))
        selector = selector.exactly(1) if cardinality == "one" else selector.at_least(1)
        result = _apply_topology_identity_tag(
            cast(Solid, result),
            selector,
            f"{prefix}.face.{local_name}",
            kind="face",
            local_name=local_name,
            authoring_source=f"simplecadapi.{op}.tag_prefix",
        )

    source_edges = {
        _topo_id(edge.wrapped): edge
        for source in source_shapes
        for edge in (
            source._iter_edges()
            if hasattr(source, "get_edges")
            else ([source] if isinstance(source, Edge) else [])
        )
    }
    result_faces = {
        _topo_id(face.wrapped): face for face in cast(Solid, result)._iter_faces()
    }
    if side_role is not None:
        # A side Face may have multiple source profile Edges (for example, a
        # loft side joins the corresponding Edges from two sections). A
        # A topology-identity tag is safe only when kernel history proves a bijection.
        side_correspondence: List[Tuple[str, str]] = []
        for role_entry in delta.roles:
            if role_entry.role != side_role:
                continue
            parent_edges = [
                parent
                for parent in role_entry.parent_refs
                if parent.kind == TopoKind.EDGE
            ]
            if len(parent_edges) != 1:
                continue
            side_correspondence.append(
                (role_entry.ref.topo_id, parent_edges[0].topo_id)
            )

        target_sources: Dict[str, Set[str]] = {}
        source_targets: Dict[str, Set[str]] = {}
        for target_id, source_id in side_correspondence:
            target_sources.setdefault(target_id, set()).add(source_id)
            source_targets.setdefault(source_id, set()).add(target_id)

        for target_id, source_id in side_correspondence:
            if len(target_sources[target_id]) != 1:
                continue
            if len(source_targets[source_id]) != 1:
                continue
            source_edge = source_edges.get(source_id)
            target_face = result_faces.get(target_id)
            if source_edge is None or target_face is None:
                continue
            edge_local_name = _topology_identity_local_name(source_edge)
            if edge_local_name is None:
                continue
            result = _apply_topology_identity_tag(
                cast(Solid, result),
                [target_face],
                f"{prefix}.face.side.{edge_local_name}",
                kind="face",
                local_name=f"side.{edge_local_name}",
                authoring_source=f"simplecadapi.{op}.profile_edge_tag",
            )

    for role, local_name in edge_roles:
        result = _apply_topology_identity_tag(
            cast(Solid, result),
            ShapeSelector("edge").where(output_role(role)).exactly(1),
            f"{prefix}.edge.{local_name}",
            kind="edge",
            local_name=local_name,
            authoring_source=f"simplecadapi.{op}.tag_prefix",
        )
    for role, local_name in face_roles:
        result = _apply_topology_identity_tag(
            cast(Solid, result),
            ShapeSelector("face").where(output_role(role)).exactly(1),
            f"{prefix}.face.{local_name}",
            kind="face",
            local_name=local_name,
            authoring_source=f"simplecadapi.{op}.tag_prefix",
        )
    return cast(Solid, result)

def _semantic_view_target(view: AnyShape, target: AnyShape) -> AnyShape:
    candidates = [
        wrapper
        for entity in view._topology_cache.entities()
        if entity.kind == target._entity.kind
        for wrapper in entity.wrappers
        if isinstance(wrapper, type(target))
    ]
    matches = []
    for candidate in candidates:
        try:
            if _same_semantic_topology(
                target._entity.kind,
                candidate.wrapped,
                target.wrapped,
            ):
                matches.append(candidate)
        except Exception:
            continue
    unique = {candidate.topo_id: candidate for candidate in matches}
    if not unique:
        raise ValueError("tag target does not belong to the assignment scope")
    if len(unique) != 1:
        raise ValueError("tag target resolves ambiguously inside the assignment scope")
    return cast(AnyShape, next(iter(unique.values())))

def _apply_tag_rselection(
    scope: AnyShape,
    targets: Union[ShapeSelector, Sequence[AnyShape]],
    tag: str,
    topology_propagation: str | TopologyPropagation,
    lineage_policy: str | LineagePolicy,
    *,
    authoring_source: str = "simplecadapi.apply_tag_rselection",
    extra_evidence: Optional[Dict[str, Any]] = None,
    clone_scope: bool = True,
) -> AnyShape:
    normalized_tag = normalize_tag(tag, strict=True)
    topology = TopologyPropagation(topology_propagation)
    lineage = LineagePolicy(lineage_policy)
    session = get_active_session()
    source_node = _active_graph_node_for_shape(scope)
    source_output_slot = int(scope._get_runtime("graph.output_slot", 0))
    if session is not None and source_node is None:
        raise ValueError("assignment scope is not produced by the active GraphSession")

    view = clone_semantic_shape_view(scope) if clone_scope else scope
    if isinstance(targets, ShapeSelector):
        selector = targets
        if source_node is not None:
            if selector.source_node_id is None:
                selector = selector.from_source(source_node.node_id, source_output_slot)
            elif (
                selector.source_node_id != source_node.node_id
                or int(selector.source_output_slot or 0) != source_output_slot
            ):
                raise ValueError(
                    "tag selector source does not match the assignment scope"
                )
        selected = cast(List[AnyShape], selector.resolve(view))
        target = TagTarget("selection_query", selector=selector.to_dict())
    else:
        if isinstance(targets, (str, bytes)):
            raise TypeError("targets must be a ShapeSelector or shape sequence")
        target_shapes = list(targets)
        if not target_shapes:
            raise ValueError("tag assignment targets cannot be empty")
        if not all(
            isinstance(item, (Vertex, Edge, Wire, Face, Shell, Solid, Compound))
            for item in target_shapes
        ):
            raise TypeError("tag assignment targets must contain only shapes")
        selected = [
            _semantic_view_target(view, item) for item in target_shapes
        ]
        refs = tuple(
            ref for ref in _serialize_shape_refs(target_shapes) if isinstance(ref, dict)
        )
        if len(refs) != len(target_shapes):
            refs = tuple(
                {"kind": _shape_kind_token(item), "topo_id": item.topo_id}
                for item in target_shapes
            )
        target = TagTarget("explicit_refs", refs=refs)

    selected_by_topo_id = {item.topo_id: item for item in selected}
    if len(selected_by_topo_id) != len(selected):
        raise ValueError("tag assignment targets contain ambiguous duplicate entities")
    selected = list(selected_by_topo_id.values())
    if not selected:
        raise ValueError("tag assignment resolved no targets")

    selected_refs = _serialize_shape_refs(selected)
    if len(selected_refs) != len(selected):
        selected_refs = [
            {"kind": _shape_kind_token(item), "topo_id": item.topo_id}
            for item in selected
        ]

    assignment_node_id = (
        session.graph.allocate_node_id("n")
        if source_node is not None and session is not None
        else None
    )
    evidence_data = {
        "authoring_source": authoring_source,
        "selected_count": len(selected),
        "selected_refs": selected_refs,
        **dict(extra_evidence or {}),
    }
    binding = TagBinding(
        tag=normalized_tag,
        producer=TagProducer("user_operation", node_id=assignment_node_id),
        scope=TagBindingScope(
            node_id=(source_node.node_id if source_node is not None else None),
            output_slot=source_output_slot,
        ),
        target=target,
        propagation=TagPropagation(topology=topology, lineage=lineage),
        evidence=TagEvidence("query_execution", evidence_data),
        certainty=TagCertainty.ASSERTED,
        lifecycle=TagLifecycle.ASSERTION,
        binding_id=(
            f"tag_binding_{uuid.uuid5(uuid.NAMESPACE_URL, f'simplecad:user-tag:{session.graph.graph_id}:{assignment_node_id}:{normalized_tag}').hex}"
            if assignment_node_id is not None and session is not None
            else f"tag_binding_{uuid.uuid4().hex}"
        ),
    )

    for selected_shape in selected:
        selected_shape._add_tag_binding(binding)

    if source_node is not None and session is not None:
        node = record_operation(
            op=_OP_APPLY_TAG_RSELECTION,
            params={"tag_binding": binding.to_dict()},
            inputs=[source_node],
            node_id=assignment_node_id,
            output_count=1,
            context=_current_context_metadata(),
        )
        attach_semantic_graph_node(
            view,
            node,
            output_slot=0,
            graph_id=session.graph.graph_id,
        )
    return view

_EXPORTABLE_TYPES = (Compound, Solid, Shell, Face, Wire, Edge, Vertex)

__all__ = tuple(name for name in globals() if not name.startswith("__"))

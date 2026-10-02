"""Geometry operator implementations."""

from __future__ import annotations

from ._diagnostics import raise_loft_failure_if_diagnosed, raise_open_wire_failure
from ._support import *

@dataclass(frozen=True)
class SurfaceBoundary:
    """One edge constraint used by ``make_surface_patch_rface``."""

    edge: Edge
    continuity: str = "C0"
    support: Optional[Face] = None

    def __post_init__(self) -> None:
        if not isinstance(self.edge, Edge):
            raise TypeError("SurfaceBoundary.edge must be an Edge")
        if self.support is not None and not isinstance(self.support, Face):
            raise TypeError("SurfaceBoundary.support must be a Face or None")
        if str(self.continuity).upper() not in {"C0", "G1", "G2"}:
            raise ValueError("SurfaceBoundary.continuity must be C0, G1, or G2")

    def as_dict(self) -> Dict[str, object]:
        return {
            "continuity": str(self.continuity).upper(),
            "has_support": self.support is not None,
        }

@dataclass(frozen=True)
class SurfaceFillingSettings:
    """Explicit OCCT filling controls; units are model units and radians."""

    degree: int = 3
    points_per_curve: int = 15
    iterations: int = 2
    anisotropic: bool = False
    tolerance_2d: float = 1e-5
    tolerance_3d: float = 1e-4
    angular_tolerance: float = 0.01
    curvature_tolerance: float = 0.1
    max_degree: int = 8
    max_segments: int = 9

    def __post_init__(self) -> None:
        if self.degree < 1 or self.points_per_curve < 2 or self.iterations < 1:
            raise ValueError(
                "filling degree, points_per_curve, and iterations must be positive"
            )
        if self.max_degree < self.degree or self.max_segments < 1:
            raise ValueError(
                "max_degree must cover degree and max_segments must be positive"
            )
        for name in (
            "tolerance_2d",
            "tolerance_3d",
            "angular_tolerance",
            "curvature_tolerance",
        ):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite value")

    def as_dict(self) -> Dict[str, object]:
        return cast(Dict[str, object], asdict(self))

def _surface_tag_output(shape: AnyShape, tag_prefix: Optional[str]) -> AnyShape:
    if tag_prefix is None:
        return shape
    normalized = normalize_tag(tag_prefix, strict=True)
    shape._apply_tag(f"{normalized}.{_shape_kind_token(shape)}", propagate=False)
    return shape

def _surface_point_grid(
    points: Sequence[Sequence[Sequence[float]]],
) -> List[List[Tuple[float, float, float]]]:
    rows = [
        [tuple(float(component) for component in point) for point in row]
        for row in points
    ]
    if len(rows) < 2 or any(len(row) < 2 for row in rows):
        raise ValueError("surface point grids require at least 2 rows and 2 columns")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("surface point grids must be rectangular")
    if any(len(point) != 3 for row in rows for point in row):
        raise ValueError("surface points must contain exactly three coordinates")
    if not all(np.isfinite(value) for row in rows for point in row for value in point):
        raise ValueError("surface points must be finite")
    return rows

def _surface_global_point_grid(
    points: Sequence[Sequence[Sequence[float]]],
) -> List[List[Tuple[float, float, float]]]:
    cs = get_current_cs()
    grid = _surface_point_grid(points)
    return [
        [
            tuple(float(value) for value in cs.transform_point(np.asarray(point)))
            for point in row
        ]
        for row in grid
    ]

def _surface_global_points(
    points: Sequence[Sequence[float]],
) -> List[Tuple[float, float, float]]:
    cs = get_current_cs()
    result = []
    for point in points:
        values = tuple(float(value) for value in point)
        if len(values) != 3 or not all(np.isfinite(value) for value in values):
            raise ValueError("surface constraint points must be finite 3D points")
        result.append(
            tuple(float(value) for value in cs.transform_point(np.asarray(values)))
        )
    return result

def _surface_local_point_grid(
    points: Sequence[Sequence[Sequence[float]]],
) -> List[List[Tuple[float, float, float]]]:
    return _surface_point_grid(points)

def make_bezier_surface_rface(
    control_points: Sequence[Sequence[Sequence[float]]],
    weights: Optional[Sequence[Sequence[float]]] = None,
    *,
    tag_prefix: Optional[str] = None,
) -> Face:
    """Create a trimmed Face carrying a tensor-product Bezier surface."""
    try:
        local_points = _surface_local_point_grid(control_points)
        global_points = _surface_global_point_grid(local_points)
        global_weights = (
            None if weights is None else [list(map(float, row)) for row in weights]
        )
        if global_weights is not None:
            if len(global_weights) != len(local_points) or any(
                len(row) != len(local_points[0]) for row in global_weights
            ):
                raise ValueError("Bezier weights must match the control-point grid")
            if any(
                weight <= 0 or not np.isfinite(weight)
                for row in global_weights
                for weight in row
            ):
                raise ValueError("Bezier weights must be positive finite values")
        result = Face(make_bezier_surface(global_points, global_weights))
        result = cast(
            Face,
            _finalize_primitive_shape(
                result,
                op="make_bezier_surface_rface",
                params={
                    "control_points": local_points,
                    "weights": global_weights,
                    "tag_prefix": tag_prefix,
                },
                tags={"primitive", "surface", "face"},
            ),
        )
        return cast(Face, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="make_bezier_surface_rface",
            what_happened="Failed to create the Bezier surface face.",
            possible_causes=[
                "The control-point grid is invalid or degenerate.",
                "The kernel rejected the Bezier surface.",
            ],
            how_to_fix=[
                "Pass a rectangular finite grid with at least two rows and columns.",
                "Use positive finite weights with the same dimensions as the grid.",
            ],
            error=e,
        )

def make_cylindrical_surface_rface(
    radius: ScalarLike,
    u_range: Tuple[ScalarLike, ScalarLike],
    v_range: Tuple[ScalarLike, ScalarLike],
    origin: Tuple[float, float, float] = (0, 0, 0),
    axis: Tuple[float, float, float] = (0, 0, 1),
    x_direction: Optional[Tuple[float, float, float]] = None,
    *,
    tolerance: ScalarLike = 1e-7,
    tag_prefix: Optional[str] = None,
) -> Face:
    """Create a finite cylindrical carrier Face over explicit U/V ranges.

    ``radius``, V values, and ``tolerance`` use model length units. U values
    are unitless raw radians, must increase, and may span at most one
    revolution. Unit-aware angle expressions are not accepted for U because
    the existing expression evaluator returns canonical angles in degrees.
    """

    try:
        if expression_uses_units(radius) and infer_dimension(radius) != LENGTH:
            raise ValueError("radius must use model length units")
        if any(
            expression_uses_units(value) and infer_dimension(value) != DIMENSIONLESS
            for value in u_range
        ):
            raise ValueError(
                "u_range must use unitless raw radians; unit-aware angle values "
                "evaluate in degrees"
            )
        if any(
            expression_uses_units(value) and infer_dimension(value) != LENGTH
            for value in v_range
        ):
            raise ValueError("v_range must use model length units")
        if expression_uses_units(tolerance) and infer_dimension(tolerance) != LENGTH:
            raise ValueError("tolerance must use model length units")
        radius_value = evaluate_scalar(radius)
        u_values = tuple(evaluate_scalar(value) for value in u_range)
        v_values = tuple(evaluate_scalar(value) for value in v_range)
        tolerance_value = float(evaluate_scalar(tolerance))
        if not np.isfinite(radius_value) or radius_value <= 0.0:
            raise ValueError("radius must be a positive finite value")
        if len(u_values) != 2 or not all(np.isfinite(value) for value in u_values):
            raise ValueError("u_range must contain two finite values")
        if len(v_values) != 2 or not all(np.isfinite(value) for value in v_values):
            raise ValueError("v_range must contain two finite values")
        u_span = u_values[1] - u_values[0]
        v_span = v_values[1] - v_values[0]
        if (
            u_span <= Precision.PConfusion_s()
            or u_span > 2.0 * math.pi + Precision.Angular_s()
        ):
            raise ValueError(
                "u_range must be increasing and span at most one revolution"
            )
        if v_span <= Precision.Confusion_s():
            raise ValueError("v_range must be increasing beyond kernel confusion")
        if not np.isfinite(tolerance_value) or tolerance_value <= 0.0:
            raise ValueError("tolerance must be a positive finite value")

        origin_value = cast(Tuple[float, float, float], evaluate_value(origin))
        axis_value = cast(Tuple[float, float, float], evaluate_value(axis))
        x_value = (
            tuple(float(value) for value in _default_plane_x_direction(axis_value))
            if x_direction is None
            else cast(Tuple[float, float, float], evaluate_value(x_direction))
        )
        vectors = [
            tuple(float(value) for value in item)
            for item in (origin_value, axis_value, x_value)
        ]
        if any(
            len(item) != 3 or not all(np.isfinite(value) for value in item)
            for item in vectors
        ):
            raise ValueError("origin, axis, and x_direction must be finite 3D values")
        axis_norm = float(np.linalg.norm(vectors[1]))
        x_norm = float(np.linalg.norm(vectors[2]))
        if axis_norm <= 1e-12 or x_norm <= 1e-12:
            raise ValueError("axis and x_direction must be non-zero")
        parallel = abs(float(np.dot(vectors[1], vectors[2])) / (axis_norm * x_norm))
        if parallel >= 1.0 - 1e-12:
            raise ValueError("axis and x_direction must not be parallel")

        cs = get_current_cs()
        global_origin = cs.transform_point(np.asarray(vectors[0], dtype=float))
        global_axis = cs.transform_vector(np.asarray(vectors[1], dtype=float))
        global_x_direction = cs.transform_vector(np.asarray(vectors[2], dtype=float))
        result = cast(
            Face,
            _finalize_primitive_shape(
                Face(
                    make_cylindrical_surface(
                        radius_value,
                        u_values,
                        v_values,
                        origin=global_origin,
                        axis=global_axis,
                        x_direction=global_x_direction,
                        tolerance=tolerance_value,
                    )
                ),
                op="make_cylindrical_surface_rface",
                params={
                    "radius": radius,
                    "u_range": u_range,
                    "v_range": v_range,
                    "origin": origin,
                    "axis": axis,
                    "x_direction": x_direction,
                    "tolerance": tolerance,
                    "tag_prefix": tag_prefix,
                },
                tags={"primitive", "surface", "face"},
            ),
        )
        return cast(Face, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="make_cylindrical_surface_rface",
            what_happened="Failed to create the cylindrical surface face.",
            possible_causes=[
                "The radius, U/V ranges, or tolerance is invalid.",
                "The axis frame is degenerate or parallel.",
                "The kernel rejected the bounded cylindrical surface.",
            ],
            how_to_fix=[
                "Use model length units for radius, V, and tolerance.",
                "Pass increasing finite U bounds as unitless raw radians.",
                "Keep the U span at or below one revolution and provide non-parallel axis directions.",
            ],
            error=e,
        )

def fit_point_grid_rface(
    points: Sequence[Sequence[Sequence[float]]],
    *,
    tolerance: float = 1e-3,
    degree_min: int = 3,
    degree_max: int = 8,
    smoothing: Optional[Tuple[float, float, float]] = None,
    tag_prefix: Optional[str] = None,
) -> Face:
    """Fit a B-spline Face through a rectangular 3D point grid."""
    try:
        tolerance_value = float(tolerance)
        if not np.isfinite(tolerance_value) or tolerance_value <= 0:
            raise ValueError("tolerance must be a positive finite value")
        degree_min_value, degree_max_value = int(degree_min), int(degree_max)
        if degree_min_value < 1 or degree_max_value < degree_min_value:
            raise ValueError("degree_max must be greater than or equal to degree_min")
        smoothing_values = (
            None if smoothing is None else tuple(float(v) for v in smoothing)
        )
        if smoothing_values is not None and (
            len(smoothing_values) != 3
            or any(not np.isfinite(v) or v < 0 for v in smoothing_values)
        ):
            raise ValueError("smoothing must contain three finite non-negative weights")
        local_points = _surface_local_point_grid(points)
        global_points = _surface_global_point_grid(local_points)
        result = Face(
            fit_point_grid_surface(
                global_points,
                tolerance=tolerance_value,
                degree_min=degree_min_value,
                degree_max=degree_max_value,
                smoothing=smoothing_values,
            )
        )
        result = cast(
            Face,
            _finalize_primitive_shape(
                result,
                op="fit_point_grid_rface",
                params={
                    "points": local_points,
                    "tolerance": tolerance_value,
                    "degree_min": degree_min_value,
                    "degree_max": degree_max_value,
                    "smoothing": smoothing_values,
                    "tag_prefix": tag_prefix,
                },
                tags={"primitive", "surface", "face"},
            ),
        )
        return cast(Face, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="fit_point_grid_rface",
            what_happened="Failed to fit a B-spline surface face.",
            possible_causes=[
                "The point grid or fitting controls are invalid.",
                "The kernel fitting algorithm did not converge.",
            ],
            how_to_fix=[
                "Pass a rectangular finite point grid and positive tolerance.",
                "Keep degree_min <= degree_max and use non-negative smoothing weights.",
            ],
            error=e,
        )

def make_ruled_surface_rface(
    edge_a: Edge, edge_b: Edge, *, tag_prefix: Optional[str] = None
) -> Face:
    """Create a ruled Face spanning two compatible edges."""
    try:
        if not isinstance(edge_a, Edge) or not isinstance(edge_b, Edge):
            raise TypeError("make_ruled_surface_rface requires two Edge objects")
        result = cast(
            Face,
            _finalize_derived_shape(
                Face(make_ruled_face(edge_a.wrapped, edge_b.wrapped)),
                op="make_ruled_surface_rface",
                params={"tag_prefix": tag_prefix},
                input_shapes=[edge_a, edge_b],
                tags={"derived", "surface", "face"},
            ),
        )
        return cast(Face, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="make_ruled_surface_rface",
            what_happened="Failed to create the ruled surface face.",
            possible_causes=[
                "The inputs are not edges.",
                "The two edges cannot define a ruled surface.",
            ],
            how_to_fix=[
                "Pass two valid Edge objects with compatible parameterization."
            ],
            error=e,
        )

def make_gordon_surface_rface(
    profiles: Sequence[Edge],
    guides: Sequence[Edge],
    *,
    tolerance: float = 1e-3,
    tag_prefix: Optional[str] = None,
) -> Face:
    """Create a Gordon Face from intersecting profile and guide edge networks."""
    try:
        profile_list, guide_list = list(profiles), list(guides)
        if len(profile_list) < 2 or len(guide_list) < 2:
            raise ValueError(
                "Gordon surfaces require at least two profiles and two guides"
            )
        if not all(isinstance(edge, Edge) for edge in [*profile_list, *guide_list]):
            raise TypeError("Gordon profiles and guides must contain only Edge objects")
        if not np.isfinite(float(tolerance)) or float(tolerance) <= 0:
            raise ValueError("tolerance must be a positive finite value")
        result = cast(
            Face,
            _finalize_derived_shape(
                Face(
                    make_gordon_surface(
                        [edge.wrapped for edge in profile_list],
                        [edge.wrapped for edge in guide_list],
                        tolerance=float(tolerance),
                    )
                ),
                op="make_gordon_surface_rface",
                params={
                    "profile_count": len(profile_list),
                    "guide_count": len(guide_list),
                    "tolerance": float(tolerance),
                    "tag_prefix": tag_prefix,
                },
                input_shapes=[*profile_list, *guide_list],
                tags={"derived", "surface", "face"},
            ),
        )
        return cast(Face, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="make_gordon_surface_rface",
            what_happened="Failed to create the Gordon surface face.",
            possible_causes=[
                "The curve network is too small, non-intersecting, or inconsistent.",
                "The kernel Gordon interpolation failed.",
            ],
            how_to_fix=[
                "Pass at least two profiles and two guides whose endpoints form a compatible network.",
                "Increase tolerance only when the source curves are numerically noisy.",
            ],
            error=e,
        )

def make_surface_patch_rface(
    boundaries: Sequence[SurfaceBoundary],
    *,
    points: Sequence[Sequence[float]] = (),
    settings: Optional[SurfaceFillingSettings] = None,
    holes: Sequence[Wire] = (),
    tag_prefix: Optional[str] = None,
) -> Face:
    """Fill a constrained boundary network into one Face, optionally with holes.

    The filling kernel re-fits each boundary edge, so adjacent patches built
    with this operation do not keep identical shared boundary curves. When
    several patches must share exact boundary edges and sew into one closed
    shell, build each patch with ``make_gordon_surface_rface`` from a shared
    profile/guide edge network instead.
    """
    try:
        boundary_list = list(boundaries)
        if not boundary_list or not all(
            isinstance(item, SurfaceBoundary) for item in boundary_list
        ):
            raise ValueError("boundaries must be a non-empty SurfaceBoundary sequence")
        settings_value = settings or SurfaceFillingSettings()
        if not isinstance(settings_value, SurfaceFillingSettings):
            raise TypeError("settings must be SurfaceFillingSettings")
        hole_list = list(holes)
        if not all(isinstance(wire, Wire) for wire in hole_list):
            raise TypeError("holes must contain only Wire objects")
        support_shapes = [
            item.support for item in boundary_list if item.support is not None
        ]
        interleaved_inputs: List[AnyShape] = []
        for item in boundary_list:
            interleaved_inputs.append(item.edge)
            if item.support is not None:
                interleaved_inputs.append(item.support)
        input_shapes: List[AnyShape] = [*interleaved_inputs, *hole_list]
        local_points = [tuple(float(v) for v in point) for point in points]
        global_points = _surface_global_points(local_points)
        result = cast(
            Face,
            _finalize_derived_shape(
                Face(
                    make_filling_face(
                        [
                            (
                                item.edge.wrapped,
                                item.support.wrapped if item.support else None,
                                str(item.continuity).upper(),
                            )
                            for item in boundary_list
                        ],
                        global_points,
                        settings=settings_value.as_dict(),
                        holes=[wire.wrapped for wire in hole_list],
                    )
                ),
                op="make_surface_patch_rface",
                params={
                    "boundary_count": len(boundary_list),
                    "support_count": len(support_shapes),
                    "hole_count": len(hole_list),
                    "boundaries": [item.as_dict() for item in boundary_list],
                    "points": local_points,
                    "settings": settings_value.as_dict(),
                    "tag_prefix": tag_prefix,
                },
                input_shapes=input_shapes,
                tags={"derived", "surface", "face"},
            ),
        )
        return cast(Face, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="make_surface_patch_rface",
            what_happened="Failed to fill the constrained surface patch.",
            possible_causes=[
                "A boundary is invalid, open, or incompatible with its support face.",
                "The filling controls are invalid or the kernel did not converge.",
            ],
            how_to_fix=[
                "Pass non-empty SurfaceBoundary values with valid Edge objects.",
                "Use C0/G1/G2 continuity and explicit positive filling tolerances.",
                "For patches that must share exact boundary edges with neighbors "
                "and sew into a closed shell, build them with "
                "make_gordon_surface_rface on a shared edge network instead; "
                "filling re-fits boundaries and breaks edge identity.",
            ],
            error=e,
        )

def _validated_loft_sections(
    sections: Sequence[Union[Wire, Vertex]], *, operation: str
) -> List[Union[Wire, Vertex]]:
    section_list = list(sections)
    if len(section_list) < 2:
        raise ValueError(f"{operation} requires at least two sections")
    if not all(isinstance(section, (Wire, Vertex)) for section in section_list):
        raise TypeError(
            f"{operation} sections must contain only Wire or Vertex objects"
        )
    if not any(isinstance(section, Wire) for section in section_list):
        raise ValueError(f"{operation} requires at least one Wire section")
    if any(isinstance(section, Vertex) for section in section_list[1:-1]):
        raise ValueError(f"{operation} allows Vertex sections only at the start or end")
    return section_list

def _pending_loft_role(shape: AnyShape, role: str, method: str) -> TopoRoleEntry:
    return TopoRoleEntry(
        ref=TopoRef(
            "pending",
            "pending",
            0,
            {
                "wire": TopoKind.WIRE,
                "face": TopoKind.FACE,
            }[_shape_kind_token(shape)],
            _topo_id(shape.wrapped),
        ),
        role=role,
        metadata={
            "coverage": "complete",
            "status": "proven",
            "evidence_kind": "kernel_operation_role",
            "evidence_method": method,
        },
    )

def _matching_shell_boundary(shell: Shell, profile: Wire) -> Wire:
    profile_edges = list(profile._iter_edges())
    matches = [
        boundary
        for boundary in shell._iter_wires()
        if len(boundary._iter_edges()) == len(profile_edges)
        and all(
            any(
                edge.wrapped.IsSame(profile_edge.wrapped)
                for edge in boundary._iter_edges()
            )
            for profile_edge in profile_edges
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            f"loft endpoint profile must match exactly one result boundary, got {len(matches)}"
        )
    return matches[0]

def _apply_loft_role_metadata(
    shape: AnyShape, delta: TopoDelta, *, op: str
) -> AnyShape:
    candidates: Dict[Tuple[TopoKind, str], AnyShape] = {}
    for kind, members in (
        (TopoKind.FACE, shape._iter_faces() if hasattr(shape, "get_faces") else []),
        (TopoKind.WIRE, shape._iter_wires() if hasattr(shape, "get_wires") else []),
    ):
        for member in members:
            candidates[(kind, _topo_id(member.wrapped))] = member
    for entry in delta.roles:
        member = candidates.get((entry.ref.kind, entry.ref.topo_id))
        if member is None:
            continue
        track = dict(member.get_metadata("track", {}))
        roles = sorted({*track.get("result_roles", ()), entry.role})
        track.update(
            {
                "op": op,
                "topo_id": entry.ref.topo_id,
                "kind": entry.ref.kind.name,
                "coverage": "complete",
                "status": "proven",
                "result_roles": roles,
            }
        )
        member.set_metadata("track", track)
    return shape

def _apply_shell_loft_tag_prefix(
    shell: Shell, *, tag_prefix: Optional[str], has_start: bool, has_end: bool
) -> Shell:
    if tag_prefix is None:
        return shell
    prefix = normalize_tag(tag_prefix, strict=True)
    result: AnyShape = _apply_topology_identity_tag(
        shell,
        ShapeSelector("shell").exactly(1),
        f"{prefix}.shell",
        kind="shell",
        local_name="shell",
        authoring_source="simplecadapi.loft_rshell.tag_prefix",
    )
    for present, role, local_name in (
        (has_start, "loft.start_wire", "start"),
        (has_end, "loft.end_wire", "end"),
    ):
        if not present:
            continue
        result = _apply_topology_identity_tag(
            cast(Shell, result),
            ShapeSelector("wire").where(output_role(role)).exactly(1),
            f"{prefix}.wire.{local_name}",
            kind="wire",
            local_name=local_name,
            authoring_source="simplecadapi.loft_rshell.tag_prefix",
        )
    result = _apply_topology_identity_tag(
        cast(Shell, result),
        ShapeSelector("face").where(output_role("loft.side")).at_least(1),
        f"{prefix}.face.side",
        kind="face",
        local_name="side",
        authoring_source="simplecadapi.loft_rshell.tag_prefix",
    )
    return cast(Shell, result)

def trim_surface_rface(
    carrier: Face,
    outer: Wire,
    holes: Sequence[Wire] = (),
    *,
    tolerance: float = 1e-7,
    tag_prefix: Optional[str] = None,
) -> Face:
    """Trim a carrier Face to exactly one connected Face.

    Existing carrier bounds and holes are preserved by intersecting them with
    the requested closed, simple outer loop and optional closed, simple holes.
    Empty or disconnected intersections are rejected. Every trim curve must
    lie on the carrier within ``tolerance``. Periodic carriers do not support
    holes; their outer loop must fit within one seam period without crossing
    the seam.
    """

    try:
        if not isinstance(carrier, Face):
            raise TypeError("carrier must be a Face")
        if not isinstance(outer, Wire):
            raise TypeError("outer must be a Wire")
        hole_list = list(holes)
        if not all(isinstance(wire, Wire) for wire in hole_list):
            raise TypeError("holes must contain only Wire objects")
        tolerance_value = float(tolerance)
        if not np.isfinite(tolerance_value) or tolerance_value <= 0.0:
            raise ValueError("tolerance must be a positive finite value")
        result = Face(
            trim_surface_face(
                carrier.wrapped,
                outer.wrapped,
                [wire.wrapped for wire in hole_list],
                tolerance=tolerance_value,
            )
        )
        for source in (carrier, outer, *hole_list):
            _attach_lineage_from_source(
                source,
                result,
                derivation="fragment",
                op="trim_surface_rface",
                coverage="partial",
            )
        result = cast(
            Face,
            _finalize_derived_shape(
                result,
                op="trim_surface_rface",
                params={
                    "hole_count": len(hole_list),
                    "tolerance": tolerance_value,
                    "tag_prefix": tag_prefix,
                },
                input_shapes=[carrier, outer, *hole_list],
                tags={"derived", "surface", "face", "trimmed"},
            ),
        )
        return cast(Face, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="trim_surface_rface",
            what_happened="Failed to trim the carrier surface face.",
            possible_causes=[
                "A trim wire is open, invalid, or does not lie on the carrier.",
                "A periodic trim crosses the carrier seam.",
                "A hole intersects the outer boundary or another hole.",
                "The bounded intersection is empty or has multiple connected regions.",
            ],
            how_to_fix=[
                "Pass one closed, simple outer Wire and optional closed, simple hole Wires.",
                "Keep every trim curve on the carrier within tolerance and inside one periodic seam.",
                "Choose boundaries whose carrier intersection is exactly one connected Face.",
            ],
            error=e,
        )

def loft_rshell(
    sections: Sequence[Union[Wire, Vertex]],
    *,
    ruled: bool = False,
    tag_prefix: Optional[str] = None,
    result_tag: Optional[str] = None,
    start_wire_tag: Optional[str] = None,
    end_wire_tag: Optional[str] = None,
    side_faces_tag: Optional[str] = None,
) -> Shell:
    """Create an open loft Shell with endpoint-Wire and side-Face naming."""
    try:
        section_list = _validated_loft_sections(sections, operation="loft_rshell")
        start_is_wire = isinstance(section_list[0], Wire)
        end_is_wire = isinstance(section_list[-1], Wire)
        if start_wire_tag is not None and not start_is_wire:
            raise ValueError("start_wire_tag requires a Wire start section")
        if end_wire_tag is not None and not end_is_wire:
            raise ValueError("end_wire_tag requires a Wire end section")
        assignments = _normalize_operation_role_tags(
            "make_loft_rshell",
            (
                ("loft.start_wire", start_wire_tag),
                ("loft.end_wire", end_wire_tag),
                ("loft.side", side_faces_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        result = Shell(
            make_loft_shell(
                [section.wrapped for section in section_list], ruled=bool(ruled)
            )
        )
        roles = [
            _pending_loft_role(face, "loft.side", "ResultSideFace")
            for face in result._iter_faces()
        ]
        if start_is_wire:
            roles.append(
                _pending_loft_role(
                    _matching_shell_boundary(result, section_list[0]),
                    "loft.start_wire",
                    "EndpointBoundary",
                )
            )
        if end_is_wire:
            roles.append(
                _pending_loft_role(
                    _matching_shell_boundary(result, section_list[-1]),
                    "loft.end_wire",
                    "EndpointBoundary",
                )
            )
        delta = TopoDelta(roles=tuple(roles))
        _apply_loft_role_metadata(result, delta, op="make_loft_rshell")
        finalized = cast(
            Shell,
            _finalize_derived_shape(
                result,
                op="make_loft_rshell",
                params={
                    "section_count": len(section_list),
                    "ruled": bool(ruled),
                    "tag_prefix": tag_prefix,
                },
                input_shapes=section_list,
                tags={"derived", "surface", "shell"},
                topo_delta=delta,
            ),
        )
        target_kinds = _validate_operation_output_roles(delta, assignments)
        tagged = cast(
            Shell,
            _apply_operation_role_tags(
                finalized,
                op="make_loft_rshell",
                assignments=assignments,
                target_kinds=target_kinds,
                result_tag=normalized_result_tag,
            ),
        )
        return _apply_shell_loft_tag_prefix(
            tagged,
            tag_prefix=tag_prefix,
            has_start=start_is_wire,
            has_end=end_is_wire,
        )
    except Exception as e:
        # Same section-compatibility diagnosis as the solid loft; falls
        # through to the generic wrap when no verdict lands.
        if not isinstance(e, SimpleCADError):
            try:
                raise_loft_failure_if_diagnosed(sections, "loft_rshell")
            except SimpleCADError:
                raise
            except Exception:
                pass
        _wrap_public_api_error(
            operation="loft_rshell",
            what_happened="Failed to create the surface loft shell.",
            possible_causes=[
                "Sections are incompatible or a Vertex was used away from an endpoint.",
                "The kernel loft algorithm failed.",
            ],
            how_to_fix=[
                "Pass at least two Wire or endpoint Vertex sections in loft order."
            ],
            error=e,
        )

def sew_faces_rshell(
    faces: Sequence[Face], *, tolerance: float = 1e-6, tag_prefix: Optional[str] = None
) -> Shell:
    """Sew faces into exactly one connected Shell."""
    try:
        face_list = list(faces)
        if not face_list or not all(isinstance(face, Face) for face in face_list):
            raise ValueError("sew_faces_rshell requires a non-empty Face sequence")
        if not np.isfinite(float(tolerance)) or float(tolerance) <= 0:
            raise ValueError("tolerance must be a positive finite value")
        sewn, result_face_indices = sew_faces_with_history_ocp(
            [face.wrapped for face in face_list], tolerance=float(tolerance)
        )
        result = cast(
            Shell,
            _finalize_derived_shape(
                Shell(sewn),
                op="sew_faces_rshell",
                params={
                    "face_count": len(face_list),
                    "tolerance": float(tolerance),
                    "tag_prefix": tag_prefix,
                },
                input_shapes=face_list,
                tags={"derived", "surface", "shell"},
            ),
        )
        _carry_face_provenance(
            result, face_list, result_face_indices=result_face_indices
        )
        return cast(Shell, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="sew_faces_rshell",
            what_happened="Failed to sew faces into one shell.",
            possible_causes=[
                "Faces are disconnected or their gaps exceed tolerance.",
                "The sewing result contains multiple shell components.",
                "Faces built with make_surface_patch_rface re-fit their "
                "boundary edges, so patches no longer share exact boundaries.",
            ],
            how_to_fix=[
                "Pass connected Face objects and a positive sewing tolerance.",
                "When freeform patches must share exact boundary edges, build "
                "them with make_gordon_surface_rface on a shared edge network "
                "before sewing.",
            ],
            error=e,
        )

def make_solid_from_shell_rsolid(
    shell: Shell, *, tag_prefix: Optional[str] = None
) -> Solid:
    """Create an oriented Solid from one valid closed Shell."""

    try:
        if not isinstance(shell, Shell):
            raise TypeError("make_solid_from_shell_rsolid requires a Shell")
        solid = Solid(solid_from_shell(shell.wrapped))
        source_entities = shell._topology_cache.entities()
        for target_entity in solid._topology_cache.entities():
            matches = [
                source_entity
                for source_entity in source_entities
                if source_entity.kind == target_entity.kind
                and _same_semantic_topology(
                    source_entity.kind,
                    source_entity.representative,
                    target_entity.representative,
                )
            ]
            if len(matches) == 1 and matches[0].wrappers and target_entity.wrappers:
                target_entity.wrappers[0]._copy_semantic_state_from(
                    matches[0].wrappers[0]
                )
        _attach_lineage_from_source(
            shell,
            solid,
            derivation="continuation",
            op="make_solid_from_shell_rsolid",
            coverage="partial",
        )
        result = cast(
            Solid,
            _finalize_derived_shape(
                solid,
                op="make_solid_from_shell_rsolid",
                params={"tag_prefix": tag_prefix},
                input_shapes=[shell],
                tags={"derived", "surface", "solid"},
            ),
        )
        _carry_face_provenance(
            result,
            shell._iter_faces(),
            allow_orientation_change=True,
            replace_local_bindings=False,
        )
        return cast(Solid, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="make_solid_from_shell_rsolid",
            what_happened="Failed to create a solid from the shell.",
            possible_causes=[
                "The input is not a Shell.",
                "The shell is open, invalid, or cannot be oriented as one material boundary.",
            ],
            how_to_fix=[
                "Sew a valid closed shell before converting it to a solid.",
                "Inspect free boundaries and face orientation when conversion fails.",
            ],
            error=e,
        )

def free_boundaries_rwirelist(shell: Shell, *, tolerance: float = 1e-6) -> List[Wire]:
    """Return unique closed and open free boundary wires of a Shell."""
    try:
        if not isinstance(shell, Shell):
            raise TypeError("free_boundaries_rwirelist requires a Shell")
        if not np.isfinite(float(tolerance)) or float(tolerance) <= 0:
            raise ValueError("tolerance must be a positive finite value")
        result = [
            Wire(wire)
            for wire in free_boundaries_ocp(shell.wrapped, tolerance=float(tolerance))
        ]
        record_operation_if_active(
            op="free_boundaries_rwirelist",
            params={"tolerance": float(tolerance)},
            outputs=result,
            input_shapes=[shell],
            semantic_delta=_semantic_delta_for_output(
                "free_boundaries_rwirelist",
                output_count=len(result),
                entity_type="Profile",
            ),
            context=_current_context_metadata(),
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="free_boundaries_rwirelist",
            what_happened="Failed to extract free boundary wires.",
            possible_causes=[
                "The input is not a valid Shell.",
                "The boundary analysis tolerance is invalid.",
            ],
            how_to_fix=["Pass a Shell and a positive finite tolerance."],
            error=e,
        )

def fill_holes_rshell(
    shell: Shell,
    hole_indices: Optional[Sequence[int]] = None,
    *,
    tolerance: float = 1e-6,
    settings: Optional[SurfaceFillingSettings] = None,
    tag_prefix: Optional[str] = None,
) -> Shell:
    """Fill selected closed free boundaries and return a sewn Shell."""
    try:
        if not isinstance(shell, Shell):
            raise TypeError("fill_holes_rshell requires a Shell")
        if not np.isfinite(float(tolerance)) or float(tolerance) <= 0:
            raise ValueError("tolerance must be a positive finite value")
        settings_value = settings or SurfaceFillingSettings()
        if not isinstance(settings_value, SurfaceFillingSettings):
            raise TypeError("settings must be SurfaceFillingSettings")
        indices = (
            None if hole_indices is None else [int(index) for index in hole_indices]
        )
        result = cast(
            Shell,
            _finalize_derived_shape(
                Shell(
                    fill_shell_holes_ocp(
                        shell.wrapped,
                        hole_indices=indices,
                        tolerance=float(tolerance),
                        settings=settings_value.as_dict(),
                    )
                ),
                op="fill_holes_rshell",
                params={
                    "hole_indices": indices,
                    "tolerance": float(tolerance),
                    "settings": settings_value.as_dict(),
                    "tag_prefix": tag_prefix,
                },
                input_shapes=[shell],
                tags={"derived", "surface", "shell"},
            ),
        )
        return cast(Shell, _surface_tag_output(result, tag_prefix))
    except Exception as e:
        _wrap_public_api_error(
            operation="fill_holes_rshell",
            what_happened="Failed to fill selected shell holes.",
            possible_causes=[
                "A selected boundary is not a closed hole or the index is out of range.",
                "The filling or sewing operation failed.",
            ],
            how_to_fix=[
                "Use free_boundaries_rwirelist() to inspect valid boundary indices before filling."
            ],
            error=e,
        )

def _default_plane_x_direction(normal: Sequence[float]) -> np.ndarray:
    """Return OCP's canonical in-plane X axis for a local normal."""
    normal_vec = np.asarray(normal, dtype=float)
    axis = gp_Ax2(
        gp_Pnt(0.0, 0.0, 0.0),
        gp_Dir(float(normal_vec[0]), float(normal_vec[1]), float(normal_vec[2])),
    )
    direction = axis.XDirection()
    return np.asarray(direction.Coord(), dtype=float)

def _pick_perpendicular_unit(axis: Tuple[float, float, float]) -> np.ndarray:
    axis_vec = np.array(axis, dtype=float)
    axis_norm = float(np.linalg.norm(axis_vec))
    if axis_norm <= 1e-12:
        raise ValueError("轴向量不能是零向量")
    axis_unit = axis_vec / axis_norm
    ref_vec = (
        np.array([1.0, 0.0, 0.0])
        if abs(axis_unit[2]) > 0.9
        else np.array([0.0, 0.0, 1.0])
    )
    radial = np.cross(axis_unit, ref_vec)
    radial_norm = float(np.linalg.norm(radial))
    if radial_norm <= 1e-12:
        raise ValueError("无法根据给定轴向量构建旋转剖面")
    return radial / radial_norm

def _offset_point_expr(
    center: Tuple[ScalarLike, ScalarLike, ScalarLike],
    x_axis: Sequence[float],
    y_axis: Sequence[float],
    dx: ScalarLike,
    dy: ScalarLike,
) -> Tuple[ScalarLike, ScalarLike, ScalarLike]:
    return (
        center[0] + dx * float(x_axis[0]) + dy * float(y_axis[0]),
        center[1] + dx * float(x_axis[1]) + dy * float(y_axis[1]),
        center[2] + dx * float(x_axis[2]) + dy * float(y_axis[2]),
    )

def _make_closed_profile_rwire(
    points: Sequence[Tuple[ScalarLike, ScalarLike, ScalarLike]],
) -> Wire:
    edges = [
        make_line_redge(points[index], points[(index + 1) % len(points)])
        for index in range(len(points))
    ]
    return make_wire_from_edges_rwire(edges)

def _make_closed_profile_rface(
    points: Sequence[Tuple[ScalarLike, ScalarLike, ScalarLike]],
    *,
    normal: Tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> Face:
    return make_face_from_wire_rface(_make_closed_profile_rwire(points), normal=normal)

def make_point_rvertex(x: ScalarLike, y: ScalarLike, z: ScalarLike) -> Vertex:
    """Create a point in 3D space and return it as a vertex."""
    try:
        cs = get_current_cs()
        point_value = cast(Tuple[float, float, float], evaluate_value((x, y, z)))
        global_point = cs.transform_point(np.array(point_value))
        vertex_shape = BRepBuilderAPI_MakeVertex(
            gp_Pnt(
                float(global_point[0]), float(global_point[1]), float(global_point[2])
            )
        ).Vertex()
        return cast(
            Vertex,
            _finalize_primitive_shape(
                Vertex(vertex_shape),
                op=_OP_MAKE_POINT_RVERTEX,
                params={"x": x, "y": y, "z": z},
                tags={"primitive", "vertex"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_point_rvertex",
            what_happened="Failed to create a point vertex.",
            possible_causes=[
                "One or more coordinate values are not valid finite scalars.",
                "The current coordinate system rejected the transformed point.",
            ],
            how_to_fix=[
                "Pass numeric x, y, and z values or valid scalar expressions.",
                "Inspect the coordinate values and the active workplane before retrying.",
            ],
            error=e,
        )

def make_line_redge(
    start: Tuple[ScalarLike, ScalarLike, ScalarLike],
    end: Tuple[ScalarLike, ScalarLike, ScalarLike],
    *,
    tag_prefix: Optional[str] = None,
) -> Edge:
    """Create a straight edge between two points."""
    try:
        cs = get_current_cs()
        start_value = cast(Tuple[float, float, float], evaluate_value(start))
        end_value = cast(Tuple[float, float, float], evaluate_value(end))
        start_global = cs.transform_point(np.array(start_value))
        end_global = cs.transform_point(np.array(end_value))

        edge_shape = make_line_edge(start_global, end_global)
        edge = cast(
            Edge,
            _finalize_primitive_shape(
                Edge(edge_shape),
                op=_OP_MAKE_LINE_REDGE,
                params={"start": start, "end": end},
                tags={"primitive", "edge"},
            ),
        )
        return cast(
            Edge,
            _apply_shape_tag_prefix(
                edge,
                tag_prefix,
                kind="edge",
                authoring_source="simplecadapi.make_line_redge.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_line_redge",
            what_happened="Failed to create a line edge.",
            possible_causes=[
                "The start or end point is not a valid finite 3D point.",
                "The transformed points are degenerate or rejected by the kernel.",
            ],
            how_to_fix=[
                "Pass start and end as 3-element numeric tuples or valid expressions.",
                "Ensure the two points are distinct and finite.",
            ],
            error=e,
        )

def make_segment_redge(
    start: Tuple[float, float, float], end: Tuple[float, float, float]
) -> Edge:
    """Alias of `make_line_redge` that returns a straight edge."""
    return make_line_redge(start, end)

def make_segment_rwire(
    start: Tuple[float, float, float], end: Tuple[float, float, float]
) -> Wire:
    """Create a wire containing a single straight segment."""
    try:
        if get_active_session() is not None:
            edge = make_line_redge(start, end)
            return make_wire_from_edges_rwire([edge])

        with suspend_graph_recording():
            edge = make_line_redge(start, end)
        wire_shape = make_wire_from_edges_ocp([edge.wrapped])
        return cast(
            Wire,
            _finalize_primitive_shape(
                Wire(wire_shape),
                op="make_segment_wire",
                params={"start": start, "end": end},
                tags={"primitive", "wire"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_segment_rwire",
            what_happened="Failed to create a single-segment wire.",
            possible_causes=[
                "The segment endpoints are invalid.",
                "The kernel could not assemble the segment into a wire.",
            ],
            how_to_fix=[
                "Pass two valid 3D endpoints.",
                "If the segment is computed dynamically, log the two endpoints before retrying.",
            ],
            error=e,
        )

def make_circle_redge(
    center: Tuple[float, float, float],
    radius: ScalarLike,
    normal: Tuple[float, float, float] = (0, 0, 1),
    *,
    tag_prefix: Optional[str] = None,
) -> Edge:
    """Create a circular edge."""
    try:
        radius_value = evaluate_scalar(radius)
        if radius_value <= 0:
            raise ValueError("半径必须大于0")

        cs = get_current_cs()
        center_value = cast(Tuple[float, float, float], evaluate_value(center))
        normal_value = cast(Tuple[float, float, float], evaluate_value(normal))
        center_global = cs.transform_point(np.array(center_value))
        normal_global = cs.transform_vector(np.array(normal_value))
        x_direction_global = cs.transform_vector(
            _default_plane_x_direction(normal_value)
        )

        edge_shape = make_circle_edge(
            center_global,
            radius_value,
            normal_global,
            x_direction=x_direction_global,
        )
        edge = cast(
            Edge,
            _finalize_primitive_shape(
                Edge(edge_shape),
                op=_OP_MAKE_CIRCLE_REDGE,
                params={"center": center, "radius": radius, "normal": normal},
                tags={"primitive", "edge"},
            ),
        )
        return cast(
            Edge,
            _apply_shape_tag_prefix(
                edge,
                tag_prefix,
                kind="edge",
                authoring_source="simplecadapi.make_circle_redge.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_circle_redge",
            what_happened="Failed to create a circular edge.",
            possible_causes=[
                "The radius is not a positive finite scalar.",
                "The center or normal is not a valid finite 3D vector.",
                "The kernel rejected the circle definition.",
            ],
            how_to_fix=[
                "Use a radius greater than zero.",
                "Pass finite center and normal vectors.",
                "If the normal is computed dynamically, verify it is not zero-length.",
            ],
            error=e,
        )

def make_circle_rwire(
    center: Tuple[float, float, float],
    radius: ScalarLike,
    normal: Tuple[float, float, float] = (0, 0, 1),
    *,
    tag_prefix: Optional[str] = None,
    edge_tag: Optional[str] = None,
) -> Wire:
    """Create a circular wire."""
    try:
        if get_active_session() is not None:
            edge = make_circle_redge(center, radius, normal)
            wire = make_wire_from_edges_rwire([edge])
            local_edge_tag = edge_tag or "circle"
            return cast(
                Wire,
                _apply_profile_tag_prefix(
                    wire,
                    tag_prefix,
                    (
                        [local_edge_tag]
                        if tag_prefix is not None or edge_tag is not None
                        else None
                    ),
                    authoring_source="simplecadapi.make_circle_rwire.tag_prefix",
                ),
            )

        with suspend_graph_recording():
            edge = make_circle_redge(center, radius, normal)
        wire_shape = make_wire_from_edges_ocp([edge.wrapped])
        wire = cast(
            Wire,
            _finalize_primitive_shape(
                Wire(wire_shape),
                op="make_circle_wire",
                params={"center": center, "radius": radius, "normal": normal},
                tags={"primitive", "wire"},
            ),
        )
        local_edge_tag = edge_tag or "circle"
        return cast(
            Wire,
            _apply_profile_tag_prefix(
                wire,
                tag_prefix,
                (
                    [local_edge_tag]
                    if tag_prefix is not None or edge_tag is not None
                    else None
                ),
                authoring_source="simplecadapi.make_circle_rwire.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_circle_rwire",
            what_happened="Failed to create a circular wire.",
            possible_causes=[
                "The circle edge could not be created.",
                "The wire assembly step rejected the generated edge.",
            ],
            how_to_fix=[
                "Check the center, radius, and normal inputs.",
                "Retry with a positive radius and a valid normal vector.",
            ],
            error=e,
        )

def make_circle_rface(
    center: Tuple[float, float, float],
    radius: ScalarLike,
    normal: Tuple[float, float, float] = (0, 0, 1),
    *,
    tag_prefix: Optional[str] = None,
    edge_tag: Optional[str] = None,
) -> Face:
    """Create a circular face."""
    try:
        if get_active_session() is not None:
            wire = make_circle_rwire(
                center,
                radius,
                normal,
                tag_prefix=tag_prefix,
                edge_tag=edge_tag,
            )
            return make_face_from_wire_rface(wire, normal=normal, tag_prefix=tag_prefix)

        with suspend_graph_recording():
            wire = make_circle_rwire(
                center,
                radius,
                normal,
                tag_prefix=tag_prefix,
                edge_tag=edge_tag,
            )
        face_shape = make_face_from_wire_ocp(wire.wrapped)
        face = Face(face_shape)
        face._metadata = wire._metadata.copy()
        result = cast(
            Face,
            _finalize_primitive_shape(
                face,
                op="make_circle_face",
                params={"center": center, "radius": radius, "normal": normal},
                tags={"primitive", "face"},
            ),
        )
        result = cast(
            Face,
            _copy_exact_topology_identity_tags(
                result, [wire], operation="make_circle_rface"
            ),
        )
        return cast(
            Face,
            _apply_shape_tag_prefix(
                result,
                tag_prefix,
                kind="face",
                authoring_source="simplecadapi.make_circle_rface.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_circle_rface",
            what_happened="Failed to create a circular face.",
            possible_causes=[
                "The underlying circular wire could not be created.",
                "The kernel could not create a face from the wire.",
            ],
            how_to_fix=[
                "Verify the center, radius, and normal values.",
                "Use a positive radius and a valid non-zero normal vector.",
            ],
            error=e,
        )

def make_ellipse_redge(
    center: Tuple[float, float, float],
    major_radius: ScalarLike,
    minor_radius: ScalarLike,
    normal: Tuple[float, float, float] = (0, 0, 1),
    *,
    major_direction: Optional[Tuple[float, float, float]] = None,
    tag_prefix: Optional[str] = None,
) -> Edge:
    """Create a full ellipse edge.

    ``major_direction`` orients the major axis in the ellipse plane; when
    omitted the plane basis derived from ``normal`` picks it.
    """
    try:
        major_value = evaluate_scalar(major_radius)
        minor_value = evaluate_scalar(minor_radius)
        if major_value <= 0 or minor_value <= 0:
            raise ValueError("椭圆半径必须大于0")
        if minor_value > major_value:
            raise ValueError("椭圆短半轴不能大于长半轴")

        cs = get_current_cs()
        center_value = cast(Tuple[float, float, float], evaluate_value(center))
        normal_value = cast(Tuple[float, float, float], evaluate_value(normal))
        center_global = cs.transform_point(np.array(center_value))
        normal_global = cs.transform_vector(np.array(normal_value))
        direction_value = (
            major_direction
            if major_direction is not None
            else _default_plane_x_direction(normal_value)
        )
        direction_global = cs.transform_vector(np.array(direction_value))

        edge_shape = make_ellipse_edge(
            center_global,
            major_value,
            minor_value,
            normal_global,
            major_direction=direction_global,
        )
        edge = cast(
            Edge,
            _finalize_primitive_shape(
                Edge(edge_shape),
                op="make_ellipse_redge",
                params={
                    "center": center,
                    "major_radius": major_radius,
                    "minor_radius": minor_radius,
                    "normal": normal,
                    "major_direction": major_direction,
                },
                tags={"primitive", "edge"},
            ),
        )
        return cast(
            Edge,
            _apply_shape_tag_prefix(
                edge,
                tag_prefix,
                kind="edge",
                authoring_source="simplecadapi.make_ellipse_redge.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_ellipse_redge",
            what_happened="Failed to create an ellipse edge.",
            possible_causes=[
                "The major or minor radius is not positive.",
                "The minor radius exceeds the major radius.",
                "The normal or major direction vector is invalid.",
            ],
            how_to_fix=[
                "Use positive radii with minor not exceeding major.",
                "Pass a valid non-zero normal and an in-plane major direction.",
            ],
            error=e,
        )

def make_ellipse_rwire(
    center: Tuple[float, float, float],
    major_radius: ScalarLike,
    minor_radius: ScalarLike,
    normal: Tuple[float, float, float] = (0, 0, 1),
    *,
    major_direction: Optional[Tuple[float, float, float]] = None,
    tag_prefix: Optional[str] = None,
    edge_tag: Optional[str] = None,
) -> Wire:
    """Create an elliptical wire."""
    try:
        if get_active_session() is not None:
            edge = make_ellipse_redge(
                center, major_radius, minor_radius, normal,
                major_direction=major_direction,
            )
            wire = make_wire_from_edges_rwire([edge])
            local_edge_tag = edge_tag or "ellipse"
            return cast(
                Wire,
                _apply_profile_tag_prefix(
                    wire,
                    tag_prefix,
                    (
                        [local_edge_tag]
                        if tag_prefix is not None or edge_tag is not None
                        else None
                    ),
                    authoring_source="simplecadapi.make_ellipse_rwire.tag_prefix",
                ),
            )

        with suspend_graph_recording():
            edge = make_ellipse_redge(
                center, major_radius, minor_radius, normal,
                major_direction=major_direction,
            )
        wire_shape = make_wire_from_edges_ocp([edge.wrapped])
        wire = cast(
            Wire,
            _finalize_primitive_shape(
                Wire(wire_shape),
                op="make_ellipse_wire",
                params={
                    "center": center,
                    "major_radius": major_radius,
                    "minor_radius": minor_radius,
                    "normal": normal,
                    "major_direction": major_direction,
                },
                tags={"primitive", "wire"},
            ),
        )
        local_edge_tag = edge_tag or "ellipse"
        return cast(
            Wire,
            _apply_profile_tag_prefix(
                wire,
                tag_prefix,
                (
                    [local_edge_tag]
                    if tag_prefix is not None or edge_tag is not None
                    else None
                ),
                authoring_source="simplecadapi.make_ellipse_rwire.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_ellipse_rwire",
            what_happened="Failed to create an elliptical wire.",
            possible_causes=[
                "The underlying ellipse edge could not be created.",
                "The radii or direction vectors are invalid.",
            ],
            how_to_fix=[
                "Verify the center, radii, normal, and major direction values.",
                "Use positive radii with minor not exceeding major.",
            ],
            error=e,
        )

def make_ellipse_rface(
    center: Tuple[float, float, float],
    major_radius: ScalarLike,
    minor_radius: ScalarLike,
    normal: Tuple[float, float, float] = (0, 0, 1),
    *,
    major_direction: Optional[Tuple[float, float, float]] = None,
    tag_prefix: Optional[str] = None,
    edge_tag: Optional[str] = None,
) -> Face:
    """Create an elliptical face."""
    try:
        if get_active_session() is not None:
            wire = make_ellipse_rwire(
                center,
                major_radius,
                minor_radius,
                normal,
                major_direction=major_direction,
                tag_prefix=tag_prefix,
                edge_tag=edge_tag,
            )
            return make_face_from_wire_rface(wire, normal=normal, tag_prefix=tag_prefix)

        with suspend_graph_recording():
            wire = make_ellipse_rwire(
                center,
                major_radius,
                minor_radius,
                normal,
                major_direction=major_direction,
                tag_prefix=tag_prefix,
                edge_tag=edge_tag,
            )
        face_shape = make_face_from_wire_ocp(wire.wrapped)
        face = Face(face_shape)
        face._metadata = wire._metadata.copy()
        result = cast(
            Face,
            _finalize_primitive_shape(
                face,
                op="make_ellipse_face",
                params={
                    "center": center,
                    "major_radius": major_radius,
                    "minor_radius": minor_radius,
                    "normal": normal,
                    "major_direction": major_direction,
                },
                tags={"primitive", "face"},
            ),
        )
        result = cast(
            Face,
            _copy_exact_topology_identity_tags(
                result, [wire], operation="make_ellipse_rface"
            ),
        )
        return cast(
            Face,
            _apply_shape_tag_prefix(
                result,
                tag_prefix,
                kind="face",
                authoring_source="simplecadapi.make_ellipse_rface.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_ellipse_rface",
            what_happened="Failed to create an elliptical face.",
            possible_causes=[
                "The underlying elliptical wire could not be created.",
                "The kernel could not create a face from the wire.",
            ],
            how_to_fix=[
                "Verify the center, radii, normal, and major direction values.",
                "Use positive radii with minor not exceeding major.",
            ],
            error=e,
        )

def make_rectangle_rwire(
    width: ScalarLike,
    height: ScalarLike,
    center: Tuple[ScalarLike, ScalarLike, ScalarLike] = (0, 0, 0),
    normal: Tuple[ScalarLike, ScalarLike, ScalarLike] = (0, 0, 1),
    *,
    tag_prefix: Optional[str] = None,
    edge_tags: Optional[Sequence[str]] = None,
) -> Wire:
    """Create a rectangular wire."""
    try:
        width_value = evaluate_scalar(width)
        height_value = evaluate_scalar(height)
        if width_value <= 0 or height_value <= 0:
            raise ValueError("宽度和高度必须大于0")

        if get_active_session() is not None:
            normal_value = cast(Tuple[float, float, float], evaluate_value(normal))
            _, x_axis, y_axis = _orthonormal_plane_axes(normal_value)
            half_w = width / 2
            half_h = height / 2
            corners = [
                _offset_point_expr(center, x_axis, y_axis, -half_w, -half_h),
                _offset_point_expr(center, x_axis, y_axis, half_w, -half_h),
                _offset_point_expr(center, x_axis, y_axis, half_w, half_h),
                _offset_point_expr(center, x_axis, y_axis, -half_w, half_h),
            ]
            wire = _make_closed_profile_rwire(corners)
            return cast(
                Wire,
                _apply_profile_tag_prefix(
                    wire,
                    tag_prefix,
                    edge_tags,
                    authoring_source="simplecadapi.make_rectangle_rwire.tag_prefix",
                ),
            )

        cs = get_current_cs()
        center_value = cast(Tuple[float, float, float], evaluate_value(center))
        normal_value = cast(Tuple[float, float, float], evaluate_value(normal))
        center_global = cs.transform_point(np.array(center_value))
        normal_global = cs.transform_vector(np.array(normal_value))

        normal_norm = float(np.linalg.norm(normal_global))
        if normal_norm <= 1e-15 or not np.isfinite(normal_norm):
            raise ValueError("法向量不能是零向量")

        _, local_x, local_y = _orthonormal_plane_axes(normal_value)
        plane_x = cs.transform_vector(local_x)
        plane_y = cs.transform_vector(local_y)

        # 创建矩形的四个顶点（在本地坐标系中）
        half_w, half_h = width_value / 2, height_value / 2
        local_points = [
            (-half_w, -half_h),
            (half_w, -half_h),
            (half_w, half_h),
            (-half_w, half_h),
        ]

        # 转换到全局坐标系
        global_points = []
        for local_point in local_points:
            # 在本地坐标系中的点
            point_3d = (
                center_global + local_point[0] * plane_x + local_point[1] * plane_y
            )
            global_points.append(tuple(float(v) for v in point_3d))

        # 创建边
        wire_points = [
            (float(point[0]), float(point[1]), float(point[2]))
            for point in global_points
        ]
        wire_shape = make_polyline_wire(wire_points, closed=True)
        wire = cast(
            Wire,
            _finalize_primitive_shape(
                Wire(wire_shape),
                op="make_rectangle_wire",
                params={
                    "width": width,
                    "height": height,
                    "center": center,
                    "normal": normal,
                },
                tags={"primitive", "wire"},
            ),
        )
        return cast(
            Wire,
            _apply_profile_tag_prefix(
                wire,
                tag_prefix,
                edge_tags,
                authoring_source="simplecadapi.make_rectangle_rwire.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_rectangle_rwire",
            what_happened="Failed to create a rectangular wire.",
            possible_causes=[
                "Width or height is not a positive finite scalar.",
                "The center or normal is not a valid finite 3D vector.",
                "The local rectangle basis became degenerate.",
            ],
            how_to_fix=[
                "Use width and height values greater than zero.",
                "Pass a valid center and a non-zero normal vector.",
                "If the normal is near zero, normalize or replace it before retrying.",
            ],
            error=e,
        )

def make_rectangle_rface(
    width: ScalarLike,
    height: ScalarLike,
    center: Tuple[ScalarLike, ScalarLike, ScalarLike] = (0, 0, 0),
    normal: Tuple[ScalarLike, ScalarLike, ScalarLike] = (0, 0, 1),
    *,
    tag_prefix: Optional[str] = None,
    edge_tags: Optional[Sequence[str]] = None,
) -> Face:
    """Create a rectangular face."""
    try:
        if get_active_session() is not None:
            wire = make_rectangle_rwire(
                width,
                height,
                center,
                normal,
                tag_prefix=tag_prefix,
                edge_tags=edge_tags,
            )
            return make_face_from_wire_rface(
                wire, normal=cast(Any, normal), tag_prefix=tag_prefix
            )

        with suspend_graph_recording():
            wire = make_rectangle_rwire(
                width,
                height,
                center,
                normal,
                tag_prefix=tag_prefix,
                edge_tags=edge_tags,
            )
        face_shape = make_face_from_wire_ocp(wire.wrapped)
        face = Face(face_shape)
        face._metadata = wire._metadata.copy()
        result = cast(
            Face,
            _finalize_primitive_shape(
                face,
                op="make_rectangle_face",
                params={
                    "width": width,
                    "height": height,
                    "center": center,
                    "normal": normal,
                },
                tags={"primitive", "face"},
            ),
        )
        result = cast(
            Face,
            _copy_exact_topology_identity_tags(
                result, [wire], operation="make_rectangle_rface"
            ),
        )
        return cast(
            Face,
            _apply_shape_tag_prefix(
                result,
                tag_prefix,
                kind="face",
                authoring_source="simplecadapi.make_rectangle_rface.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_rectangle_rface",
            what_happened="Failed to create a rectangular face.",
            possible_causes=[
                "The rectangular wire could not be created.",
                "The face construction step rejected the generated wire.",
            ],
            how_to_fix=[
                "Verify width, height, center, and normal.",
                "Retry with positive dimensions and a valid non-zero normal vector.",
            ],
            error=e,
        )

def make_face_from_wire_rface(
    wire: Wire,
    normal: Tuple[float, float, float] = (0, 0, 1),
    *,
    tag_prefix: Optional[str] = None,
) -> Face:
    """Create a face from a closed wire."""
    try:
        if not isinstance(wire, Wire):
            raise ValueError("输入必须是Wire类型")

        # 检查Wire是否封闭；缺口诊断（端点对+距离+证据图）随结构化错误给出
        if not wire.is_closed():
            raise_open_wire_failure(
                "make_face_from_wire_rface", wire, purpose="create a face"
            )

        # The wire is already global geometry; only the requested local normal
        # is resolved through the active workplane chain.
        cs = get_current_cs()
        global_normal = cs.transform_vector(np.array(normal))

        # 标准化法向量
        normal_vec = global_normal / np.linalg.norm(global_normal)

        # 创建面
        face_shape = make_face_from_wire_ocp(wire.wrapped)
        face = Face(face_shape)

        # 检查面的法向量是否与期望方向一致
        face_normal = face.get_normal_at()
        face_normal_vec = np.array([face_normal.x, face_normal.y, face_normal.z])

        # 计算法向量的点积，如果小于0则需要反向
        dot_product = np.dot(normal_vec, face_normal_vec)

        if dot_product < 0:
            # 反向面（通过反向Wire的方向）
            # OCP Wire 没有直接的 reverse 包装方法，这里重新构建
            # 简单的方法是使用makeFromWires的orientation参数
            # 或者我们接受当前面的方向，添加一个警告
            print(f"警告: 创建的面的法向量与期望方向相反 (点积: {dot_product:.3f})")

        face._metadata = wire._metadata.copy()

        result = cast(
            Face,
            _finalize_derived_shape(
                face,
                op=_OP_MAKE_FACE_FROM_WIRE_RFACE,
                params={"normal": normal},
                input_shapes=[wire],
                tags={"derived", "face"},
            ),
        )
        result = cast(
            Face,
            _copy_exact_topology_identity_tags(
                result, [wire], operation="make_face_from_wire_rface"
            ),
        )
        return cast(
            Face,
            _apply_shape_tag_prefix(
                result,
                tag_prefix,
                kind="face",
                authoring_source="simplecadapi.make_face_from_wire_rface.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_face_from_wire_rface",
            what_happened="Failed to create a face from the input wire.",
            possible_causes=[
                "The input is not a Wire instance.",
                "The wire is open or geometrically invalid.",
                "The kernel rejected the closed wire when building a face.",
            ],
            how_to_fix=[
                "Pass a Wire object, not an Edge or a list of points.",
                "Ensure the wire is closed before calling this API.",
                "If the wire was assembled from edges, verify the edges connect end-to-end.",
            ],
            error=e,
        )

def make_face_from_wires_rface(
    outer_wire: Wire,
    inner_wires: Sequence[Wire],
    normal: Tuple[float, float, float] = (0, 0, 1),
) -> Face:
    """Create a face from one outer closed wire and optional inner closed wires."""
    try:
        if not isinstance(outer_wire, Wire):
            raise ValueError("outer_wire must be a Wire")
        if not outer_wire.is_closed():
            raise ValueError("outer_wire must be closed")

        inner_list = list(inner_wires or [])
        for inner_wire in inner_list:
            if not isinstance(inner_wire, Wire):
                raise ValueError("inner_wires must contain only Wire objects")
            if not inner_wire.is_closed():
                raise ValueError("inner wires must be closed")

        cs = get_current_cs()
        global_normal = cs.transform_vector(np.array(normal))
        normal_norm = float(np.linalg.norm(global_normal))
        if normal_norm <= 1e-15 or not np.isfinite(normal_norm):
            raise ValueError("normal must be a non-zero finite vector")
        normal_vec = global_normal / normal_norm

        face_shape = make_face_from_wires_ocp(
            outer_wire.wrapped,
            [inner_wire.wrapped for inner_wire in inner_list],
        )
        face = Face(face_shape)

        face_normal = face.get_normal_at()
        face_normal_vec = np.array([face_normal.x, face_normal.y, face_normal.z])
        dot_product = float(np.dot(normal_vec, face_normal_vec))
        if dot_product < 0:
            print(f"警告: 创建的面的法向量与期望方向相反 (点积: {dot_product:.3f})")

        face._metadata = outer_wire._metadata.copy()

        return cast(
            Face,
            _finalize_derived_shape(
                face,
                op=_OP_MAKE_FACE_FROM_WIRES_RFACE,
                params={"normal": normal, "inner_wire_count": len(inner_list)},
                input_shapes=[outer_wire, *inner_list],
                tags={"derived", "face"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_face_from_wires_rface",
            what_happened="Failed to create a face from the input outer and inner wires.",
            possible_causes=[
                "The outer wire is not a Wire instance or is not closed.",
                "One or more inner wires are not Wire instances or are not closed.",
                "The inner wires are not contained by the outer wire or are geometrically invalid.",
                "The kernel rejected the multi-loop face definition.",
            ],
            how_to_fix=[
                "Pass one closed outer Wire and zero or more closed inner Wire objects.",
                "Ensure every inner wire lies inside the outer wire and does not intersect other loops.",
                "Use a valid non-zero normal vector.",
            ],
            error=e,
        )

def make_wire_from_edges_rwire(
    edges: List[Edge], *, tag_prefix: Optional[str] = None
) -> Wire:
    """Create a wire from a list of connected edges."""
    try:
        if not edges:
            raise ValueError("边列表不能为空")

        wire_shape = make_wire_from_edges_ocp([edge.wrapped for edge in edges])
        result = cast(
            Wire,
            _finalize_derived_shape(
                Wire(wire_shape),
                op=_OP_MAKE_WIRE_FROM_EDGES_RWIRE,
                params={"edge_count": len(edges)},
                input_shapes=edges,
                tags={"derived", "wire"},
            ),
        )
        result = cast(
            Wire,
            _copy_exact_topology_identity_tags(
                result, edges, operation="make_wire_from_edges_rwire"
            ),
        )
        return cast(
            Wire,
            _apply_shape_tag_prefix(
                result,
                tag_prefix,
                kind="wire",
                authoring_source="simplecadapi.make_wire_from_edges_rwire.tag_prefix",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_wire_from_edges_rwire",
            what_happened="Failed to assemble a wire from the input edges.",
            possible_causes=[
                "The edge list is empty.",
                "One or more items are invalid edges.",
                "The edges do not connect into a valid wire chain.",
            ],
            how_to_fix=[
                "Pass a non-empty list of Edge objects.",
                "Ensure consecutive edges share matching endpoints.",
                "Inspect the edge order if the wire should form a closed loop.",
            ],
            error=e,
        )

def load_brep_region_rsolid(
    path: str | Path,
    sha256: str,
    *,
    tag_prefix: Optional[str] = None,
) -> Solid:
    """Load a hash-pinned, target-derived BREP region snapshot as one Solid.

    The complete artifact SHA-256 is verified before native BREP decoding. In a
    GraphSession, ``path`` must be relative and is replayed relative to the replay
    process working directory. Model JSON records the locator and digest, not the
    sidecar bytes.
    """

    try:
        return cast(
            Solid,
            _load_brep_region_rshape(
                path,
                sha256,
                root_kind="solid",
                tag_prefix=tag_prefix,
                replay_root=(Path.cwd() if get_active_session() is not None else None),
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="load_brep_region_rsolid",
            what_happened="Failed to load the BREP region snapshot.",
            possible_causes=[
                "The snapshot path does not exist or is not readable.",
                "The supplied SHA-256 does not match the snapshot bytes.",
                "The snapshot is corrupt, unsupported, invalid, or not one solid.",
            ],
            how_to_fix=[
                "Create the snapshot with copy_step_region_rpath(...).",
                "Pass the SHA-256 of the complete .scadbrep file.",
                "Keep the sidecar at the same path when replaying model JSON.",
            ],
            error=e,
        )

def _carry_face_provenance(
    shape: Shell | Solid,
    source_faces: Sequence[Face],
    *,
    result_face_indices: Optional[Sequence[int]] = None,
    allow_orientation_change: bool = False,
    replace_local_bindings: bool = True,
) -> None:
    result_faces = list(shape._iter_faces())
    if result_face_indices is None:
        mapped_indices = []
        for source in source_faces:
            matches = [
                index
                for index, result in enumerate(result_faces)
                if result.wrapped.IsSame(source.wrapped)
            ]
            if len(matches) != 1:
                raise ValueError("face continuation mapping is incomplete or ambiguous")
            mapped_indices.append(matches[0])
    else:
        mapped_indices = [int(index) for index in result_face_indices]
    if len(mapped_indices) != len(source_faces) or len(set(mapped_indices)) != len(
        result_faces
    ):
        raise ValueError("face continuation mapping is not one-to-one")
    for source, result_index in zip(source_faces, mapped_indices):
        if result_index < 0 or result_index >= len(result_faces):
            raise ValueError(
                "face continuation mapping contains an invalid result index"
            )
        face = result_faces[result_index]
        provenance = source.get_metadata("provenance")
        if (
            isinstance(provenance, dict)
            and provenance.get("construction") == "exact_transcription"
            and not allow_orientation_change
            and not face.wrapped.IsEqual(source.wrapped)
        ):
            raise ValueError("sewing modified an exact-transcription input face")
        projected_bindings = [
            binding
            for binding in source._local_tag_bindings()
            if lineage_policy_allows(binding.propagation, "continuation")
        ]
        if replace_local_bindings:
            face._replace_local_tag_bindings(projected_bindings)
        _attach_lineage_from_source(
            source,
            face,
            derivation="continuation",
            op="face_continuation",
            coverage="complete",
        )
        if isinstance(provenance, dict):
            face.set_metadata("provenance", dict(provenance))
        face._set_runtime("semantic.lineage.coverage", "complete")

def load_brep_region_rshell(
    path: str | Path,
    sha256: str,
    *,
    tag_prefix: Optional[str] = None,
) -> Shell:
    """Load a hash-pinned, target-derived BREP face region as one Shell.

    The Shell keeps target-derived topology and is tagged with imported-sidecar
    provenance. Use ordinary replayable surface operations to join it to fitted
    or analytic feature faces. GraphSession requires a relative sidecar path.
    """

    try:
        return cast(
            Shell,
            _load_brep_region_rshape(
                path,
                sha256,
                root_kind="shell",
                tag_prefix=tag_prefix,
                replay_root=(Path.cwd() if get_active_session() is not None else None),
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="load_brep_region_rshell",
            what_happened="Failed to load the BREP face-region snapshot.",
            possible_causes=[
                "The snapshot path or SHA-256 is incorrect.",
                "The snapshot is corrupt, unsupported, invalid, or not one Shell.",
            ],
            how_to_fix=[
                "Create a face-region snapshot with copy_step_region_rpath(..., face_ids=[...]).",
                "Pass the SHA-256 of the complete .scadbrep file.",
            ],
            error=e,
        )

def _load_brep_region_rshape(
    path: str | Path,
    sha256: str,
    *,
    root_kind: str,
    tag_prefix: Optional[str],
    replay_root: Path | None,
) -> Shell | Solid:
    source_path = _brep_region_path(path, for_graph=replay_root is not None)
    wrapped, manifest, canonical_hash = read_artifact(
        source_path,
        sha256,
        expected_root_kind=cast(Any, root_kind),
        replay_root=replay_root,
    )
    shape: Shell | Solid = Solid(wrapped) if root_kind == "solid" else Shell(wrapped)
    shape._add_tag("imported")
    shape._add_tag("sidecar")
    shape._add_tag(root_kind)
    normalized_prefix = (
        normalize_tag(tag_prefix, strict=True) if tag_prefix is not None else None
    )
    if normalized_prefix is not None:
        shape._apply_tag(f"{normalized_prefix}.{root_kind}", propagate=False)
    shape.set_metadata(
        "brep_region",
        {
            "artifact_sha256": canonical_hash,
            "profile": manifest["profile"],
            "provenance": manifest["provenance"],
            "source_face_ids": manifest["region"].get("source_face_ids"),
        },
    )
    _attach_brep_region_provenance(shape, manifest, canonical_hash)
    op = (
        _OP_LOAD_BREP_REGION_RSOLID
        if root_kind == "solid"
        else _OP_LOAD_BREP_REGION_RSHELL
    )
    return cast(
        Shell | Solid,
        _finalize_primitive_shape(
            shape,
            op=op,
            params={
                "path": source_path,
                "sha256": canonical_hash,
                "tag_prefix": normalized_prefix,
            },
            tags={"imported", "sidecar", root_kind},
        ),
    )

def _attach_brep_region_provenance(
    shape: Shell | Solid,
    manifest: Mapping[str, Any],
    artifact_sha256: str,
) -> None:
    source = manifest["source"]
    region = manifest["region"]
    evidence = {
        "artifact_sha256": artifact_sha256,
        "profile": manifest["profile"],
        "source_sha256": source["content_hash"],
        "source_name": source["name"],
        "source_face_ids": region.get("source_face_ids"),
        "construction": "exact_transcription",
        "topology_origin": "retained",
        "runtime_dependency": "embedded_target_derived",
    }
    root_binding = TagBinding(
        tag="provenance.exact_transcription",
        producer=TagProducer(TagProducerKind.IMPORTED_SIDECAR),
        target=TagTarget(TagTargetKind.SCOPE_ROOT),
        propagation=TagPropagation(
            topology=TopologyPropagation.DOWNWARD,
            lineage=LineagePolicy.CONTINUATION_FRAGMENT,
        ),
        evidence=TagEvidence(TagEvidenceKind.IMPORTED_SIDECAR, evidence),
        certainty=TagCertainty.ASSERTED,
        lifecycle=TagLifecycle.SNAPSHOT,
        binding_id=f"tag_binding_{uuid.uuid5(uuid.NAMESPACE_URL, '|'.join(('simplecad.brep_region.root', artifact_sha256, str(region['kind'])))).hex}",
    )
    shape._add_tag_binding(root_binding)
    source_face_ids = tuple(region.get("source_face_ids") or ())
    for index, face in enumerate(shape._iter_faces()):
        face_evidence = {
            **evidence,
            "source_face_id": (
                source_face_ids[index] if index < len(source_face_ids) else None
            ),
        }
        face.set_metadata("provenance", face_evidence)
        face._add_tag_binding(
            TagBinding(
                tag="provenance.exact_transcription",
                producer=TagProducer(TagProducerKind.IMPORTED_SIDECAR),
                target=TagTarget(TagTargetKind.SCOPE_ROOT),
                propagation=TagPropagation(
                    topology=TopologyPropagation.LOCAL,
                    lineage=LineagePolicy.CONTINUATION_FRAGMENT,
                ),
                evidence=TagEvidence(TagEvidenceKind.IMPORTED_SIDECAR, face_evidence),
                certainty=TagCertainty.ASSERTED,
                lifecycle=TagLifecycle.SNAPSHOT,
                binding_id=f"tag_binding_{uuid.uuid5(uuid.NAMESPACE_URL, '|'.join(('simplecad.brep_region.face', artifact_sha256, str(face_evidence['source_face_id'])))).hex}",
            )
        )
        face._set_runtime("semantic.lineage.coverage", "complete")

def _brep_region_path(path: str | Path, *, for_graph: bool) -> str:
    source = Path(path)
    if ":" in source.name:
        raise ValueError(".scadbrep filenames must not contain ':'")
    if for_graph and source.is_absolute():
        raise ValueError(
            "GraphSession requires a relative .scadbrep path so model JSON does "
            "not record machine-specific absolute paths"
        )
    if for_graph and source.drive:
        raise ValueError("GraphSession .scadbrep paths must not contain a drive")
    if for_graph and ".." in source.parts:
        raise ValueError(".scadbrep paths must not traverse parent directories")
    if for_graph and "\\" in str(path):
        raise ValueError("GraphSession .scadbrep paths must use '/' separators")
    if source.suffix.lower() != ".scadbrep":
        raise ValueError("path must end in .scadbrep")
    return source.as_posix() if for_graph else str(source)

def make_box_rsolid(
    width: ScalarLike,
    height: ScalarLike,
    depth: ScalarLike,
    bottom_face_center: Tuple[float, float, float] = (0, 0, 0),
    *,
    tag_prefix: Optional[str] = None,
    result_tag: Optional[str] = None,
    bottom_face_tag: Optional[str] = None,
    top_face_tag: Optional[str] = None,
    front_face_tag: Optional[str] = None,
    back_face_tag: Optional[str] = None,
    left_face_tag: Optional[str] = None,
    right_face_tag: Optional[str] = None,
) -> Solid:
    """Create a box with native kernel-backed Face topology tags.

    The box extends ``depth`` along the current coordinate-system z_axis
    starting at the bottom face; ``width`` spans the x_axis and ``height``
    spans the y_axis.

    Args:
        width: Box size along the current coordinate-system x_axis.
        height: Box size along the current coordinate-system y_axis.
        depth: Box size along the current coordinate-system z_axis.
        bottom_face_center: Geometric center of the box's bottom face in the
            current coordinate system. The box is centered on this point
            along x and y (it spans width/2 and height/2 to each side) and
            extends the full ``depth`` upward along the z_axis from this
            point's height. It is not a corner; to build a box
            occupying x in [0, w], pass ``bottom_face_center=(w/2, h/2, z0)``.
    """
    try:
        assignments = _normalize_operation_role_tags(
            "make_box_rsolid",
            (
                ("box.bottom", bottom_face_tag),
                ("box.top", top_face_tag),
                ("box.front", front_face_tag),
                ("box.back", back_face_tag),
                ("box.left", left_face_tag),
                ("box.right", right_face_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        width_value = evaluate_scalar(width)
        height_value = evaluate_scalar(height)
        depth_value = evaluate_scalar(depth)

        if width_value <= 0 or height_value <= 0 or depth_value <= 0:
            raise ValueError("宽度、高度和深度必须大于0")

        cs = get_current_cs()
        center_value = cast(
            Tuple[float, float, float], evaluate_value(bottom_face_center)
        )
        center_global = cs.transform_point(np.array(center_value))
        corner_global = (
            center_global
            - np.asarray(cs.x_axis, dtype=float) * (width_value / 2.0)
            - np.asarray(cs.y_axis, dtype=float) * (height_value / 2.0)
        )
        tracked = tracked_box(
                tuple(float(value) for value in corner_global),
                width_value,
                height_value,
                depth_value,
                x_axis=tuple(float(value) for value in cs.x_axis),
                y_axis=tuple(float(value) for value in cs.y_axis),
                z_axis=tuple(float(value) for value in cs.z_axis),
            )
        solid = cast(Solid, tracked.shape)

        # 自动标记面
        solid.auto_tag_faces("box")
        solid._apply_tag("geom.primitive.box", propagate=False)
        solid._add_tag("box")
        solid.set_metadata(
            "geo",
            {
                "type": "box",
                "size": {"x": width_value, "y": height_value, "z": depth_value},
                "bottom_face_center": bottom_face_center,
            },
        )

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            solid,
            op="make_box_rsolid",
            params={
                "width": width,
                "height": height,
                "depth": depth,
                "bottom_face_center": bottom_face_center,
            },
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
        )
        tagged = _apply_operation_role_tags(
            finalized,
            op="make_box_rsolid",
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
        return _apply_feature_tag_prefix(
            tagged,
            tag_prefix=tag_prefix,
            op="make_box_rsolid",
            delta=tracked.delta,
            face_roles=(
                ("box.bottom", "bottom"),
                ("box.top", "top"),
                ("box.front", "front"),
                ("box.back", "back"),
                ("box.left", "left"),
                ("box.right", "right"),
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_box_rsolid",
            what_happened="Failed to create a box solid.",
            possible_causes=[
                "Width, height, or depth is not a positive finite scalar.",
                "The bottom face center is not a valid finite 3D point.",
                "The kernel rejected the box dimensions or placement.",
            ],
            how_to_fix=[
                "Use width, height, and depth values greater than zero.",
                "Pass bottom_face_center as a finite 3D tuple.",
                "If dimensions come from expressions, inspect the evaluated numeric values.",
            ],
            error=e,
        )
def make_cylinder_rsolid(
    radius: ScalarLike,
    height: ScalarLike,
    bottom_face_center: Tuple[float, float, float] = (0, 0, 0),
    axis: Tuple[float, float, float] = (0, 0, 1),
    *,
    tag_prefix: Optional[str] = None,
    result_tag: Optional[str] = None,
    start_face_tag: Optional[str] = None,
    end_face_tag: Optional[str] = None,
    side_face_tag: Optional[str] = None,
    start_edge_tag: Optional[str] = None,
    end_edge_tag: Optional[str] = None,
    seam_edge_tag: Optional[str] = None,
) -> Solid:
    """Create a cylinder with native kernel-backed Face and Edge topology tags.

    The cylinder extends ``height`` along ``axis`` from the bottom face.

    Args:
        radius: Cylinder radius.
        height: Cylinder length along ``axis``.
        bottom_face_center: Geometric center of the cylinder's bottom
            (start) face in the current coordinate system; the solid extends
            the full ``height`` along ``axis`` from this point.
        axis: Direction of the cylinder axis in the current coordinate
            system.
    """
    try:
        assignments = _normalize_operation_role_tags(
            "make_cylinder_rsolid",
            (
                ("cylinder.start", start_face_tag),
                ("cylinder.end", end_face_tag),
                ("cylinder.side", side_face_tag),
                ("cylinder.start_boundary", start_edge_tag),
                ("cylinder.end_boundary", end_edge_tag),
                ("cylinder.seam", seam_edge_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        radius_value = evaluate_scalar(radius)
        height_value = evaluate_scalar(height)
        if radius_value <= 0 or height_value <= 0:
            raise ValueError("半径和高度必须大于0")

        cs = get_current_cs()
        center_value = cast(
            Tuple[float, float, float], evaluate_value(bottom_face_center)
        )
        axis_value = cast(Tuple[float, float, float], evaluate_value(axis))
        center_global = cs.transform_point(np.array(center_value))
        axis_global = cs.transform_vector(np.array(axis_value))

        resolved_center = tuple(float(value) for value in center_global)
        resolved_axis = tuple(float(value) for value in axis_global)
        tracked = tracked_cylinder(
                resolved_center,
                resolved_axis,
                radius_value,
                height_value,
            )
        solid = cast(Solid, tracked.shape)

        # 自动标记面
        solid.auto_tag_faces("cylinder")
        solid._apply_tag("geom.primitive.cylinder", propagate=False)
        solid._add_tag("cylinder")
        solid.set_metadata(
            "geo",
            {
                "type": "cylinder",
                "radius": radius_value,
                "height": height_value,
                "bottom_face_center": center_value,
                "axis": axis_value,
            },
        )

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            solid,
            op="make_cylinder_rsolid",
            params={
                "radius": radius,
                "height": height,
                "bottom_face_center": bottom_face_center,
                "axis": axis,
            },
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
        )
        tagged = _apply_operation_role_tags(
            finalized,
            op="make_cylinder_rsolid",
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
        return _apply_feature_tag_prefix(
            tagged,
            tag_prefix=tag_prefix,
            op="make_cylinder_rsolid",
            delta=tracked.delta,
            start_role="cylinder.start",
            end_role="cylinder.end",
            side_role="cylinder.side",
            edge_roles=(
                ("cylinder.start_boundary", "start"),
                ("cylinder.end_boundary", "end"),
                ("cylinder.seam", "seam"),
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_cylinder_rsolid",
            what_happened="Failed to create a cylinder solid.",
            possible_causes=[
                "Radius or height is not a positive finite scalar.",
                "The bottom face center or axis is not a valid finite 3D vector.",
                "The axis is degenerate or rejected by the kernel.",
            ],
            how_to_fix=[
                "Use radius and height values greater than zero.",
                "Pass a valid bottom_face_center and a non-zero axis vector.",
                "If the axis is computed dynamically, inspect its evaluated numeric value.",
            ],
            error=e,
        )

def make_cone_rsolid(
    bottom_radius: ScalarLike,
    height: ScalarLike,
    top_radius: ScalarLike = 0.0,
    bottom_face_center: Tuple[float, float, float] = (0, 0, 0),
    axis: Tuple[float, float, float] = (0, 0, 1),
    *,
    tag_prefix: Optional[str] = None,
    result_tag: Optional[str] = None,
    start_face_tag: Optional[str] = None,
    end_face_tag: Optional[str] = None,
    side_face_tag: Optional[str] = None,
    start_edge_tag: Optional[str] = None,
    end_edge_tag: Optional[str] = None,
    seam_edge_tag: Optional[str] = None,
) -> Solid:
    """Create a cone or frustum with native kernel-backed topology tags.

    The solid extends ``height`` along ``axis`` from the bottom face,
    tapering from ``bottom_radius`` to ``top_radius`` (a cone when
    ``top_radius`` is 0).

    Args:
        bottom_radius: Radius of the bottom (start) face.
        height: Frustum length along ``axis``.
        top_radius: Radius of the top face; 0 produces a cone.
        bottom_face_center: Geometric center of the bottom (start) face in
            the current coordinate system; the solid extends the full
            ``height`` along ``axis`` from this point.
        axis: Direction of the frustum axis in the current coordinate
            system.
    """
    try:
        assignments = _normalize_operation_role_tags(
            "make_cone_rsolid",
            (
                ("cone.start", start_face_tag),
                ("cone.end", end_face_tag),
                ("cone.side", side_face_tag),
                ("cone.start_boundary", start_edge_tag),
                ("cone.end_boundary", end_edge_tag),
                ("cone.seam", seam_edge_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        bottom_radius_value = evaluate_scalar(bottom_radius)
        height_value = evaluate_scalar(height)
        top_radius_value = evaluate_scalar(top_radius)
        if bottom_radius_value <= 0 or height_value <= 0:
            raise ValueError("底面半径和高度必须大于0")

        cs = get_current_cs()
        center_value = cast(
            Tuple[float, float, float], evaluate_value(bottom_face_center)
        )
        axis_value = cast(Tuple[float, float, float], evaluate_value(axis))
        center_global = cs.transform_point(np.array(center_value))
        axis_global = cs.transform_vector(np.array(axis_value))

        resolved_center = tuple(float(value) for value in center_global)
        resolved_axis = tuple(float(value) for value in axis_global)
        tracked = tracked_cone(
                resolved_center,
                resolved_axis,
                bottom_radius_value,
                top_radius_value,
                height_value,
            )
        solid = cast(Solid, tracked.shape)

        # 自动标记面
        solid._apply_tag("geom.primitive.cone", propagate=False)
        solid._add_tag("cone")
        solid.set_metadata(
            "geo",
            {
                "type": "cone",
                "bottom_radius": bottom_radius_value,
                "top_radius": top_radius_value,
                "height": height_value,
                "bottom_face_center": center_value,
                "axis": axis_value,
            },
        )

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            solid,
            op="make_cone_rsolid",
            params={
                "bottom_radius": bottom_radius,
                "top_radius": top_radius,
                "height": height,
                "bottom_face_center": bottom_face_center,
                "axis": axis,
            },
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
        )
        tagged = _apply_operation_role_tags(
            finalized,
            op="make_cone_rsolid",
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
        return _apply_feature_tag_prefix(
            tagged,
            tag_prefix=tag_prefix,
            op="make_cone_rsolid",
            delta=tracked.delta,
            start_role="cone.start",
            end_role="cone.end" if top_radius_value > 0.0 else None,
            side_role="cone.side",
            edge_roles=(
                ("cone.start_boundary", "start"),
                ("cone.end_boundary", "end"),
                ("cone.seam", "seam"),
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_cone_rsolid",
            what_happened="Failed to create a cone or truncated cone solid.",
            possible_causes=[
                "Bottom radius or height is not a positive finite scalar.",
                "The bottom face center or axis is not a valid finite 3D vector.",
                "The kernel rejected the cone dimensions or orientation.",
            ],
            how_to_fix=[
                "Use a positive bottom radius and a positive height.",
                "Pass a valid center point and non-zero axis vector.",
                "If top_radius is used, make sure it is a finite scalar.",
            ],
            error=e,
        )

def make_sphere_rsolid(
    radius: ScalarLike, center: Tuple[float, float, float] = (0, 0, 0)
) -> Solid:
    """Create a sphere solid."""
    try:
        radius_value = evaluate_scalar(radius)
        if radius_value <= 0:
            raise ValueError("半径必须大于0")

        cs = get_current_cs()
        center_value = cast(Tuple[float, float, float], evaluate_value(center))
        center_global = cs.transform_point(np.array(center_value))

        resolved_center = tuple(float(value) for value in center_global)
        solid = Solid(make_sphere_solid(resolved_center, radius_value))

        # 自动标记面
        solid.auto_tag_faces("sphere")
        solid._apply_tag("geom.primitive.sphere", propagate=False)
        solid._add_tag("sphere")
        solid.set_metadata(
            "geo",
            {
                "type": "sphere",
                "radius": radius_value,
                "center": center_value,
            },
        )

        return _finalize_primitive_solid(
            solid,
            op="make_sphere_rsolid",
            params={
                "radius": radius,
                "center": center,
            },
            tags={"primitive", "solid"},
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_sphere_rsolid",
            what_happened="Failed to create a sphere solid.",
            possible_causes=[
                "The radius is not a positive finite scalar.",
                "The center is not a valid finite 3D point.",
                "The kernel rejected the sphere definition.",
            ],
            how_to_fix=[
                "Use a radius greater than zero.",
                "Pass center as a finite 3D tuple.",
                "If the center is expression-driven, inspect the evaluated coordinates.",
            ],
            error=e,
        )

def make_three_point_arc_redge(
    start: Tuple[float, float, float],
    middle: Tuple[float, float, float],
    end: Tuple[float, float, float],
) -> Edge:
    """Create an arc edge from three points."""
    try:
        cs = get_current_cs()
        start_value = cast(Tuple[float, float, float], evaluate_value(start))
        middle_value = cast(Tuple[float, float, float], evaluate_value(middle))
        end_value = cast(Tuple[float, float, float], evaluate_value(end))
        start_global = cs.transform_point(np.array(start_value))
        middle_global = cs.transform_point(np.array(middle_value))
        end_global = cs.transform_point(np.array(end_value))

        edge_shape = make_arc_three_point_edge(start_global, middle_global, end_global)
        return cast(
            Edge,
            _finalize_primitive_shape(
                Edge(edge_shape),
                op=_OP_MAKE_THREE_POINT_ARC_REDGE,
                params={"start": start, "middle": middle, "end": end},
                tags={"primitive", "edge"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_three_point_arc_redge",
            what_happened="Failed to create a three-point arc edge.",
            possible_causes=[
                "One or more points are invalid.",
                "The three points are collinear or nearly collinear.",
                "The kernel rejected the derived arc geometry.",
            ],
            how_to_fix=[
                "Pass three finite 3D points.",
                "Make sure the three points do not lie on the same straight line.",
                "If points are computed dynamically, log them before retrying.",
            ],
            error=e,
        )

def make_three_point_arc_rwire(
    start: Tuple[float, float, float],
    middle: Tuple[float, float, float],
    end: Tuple[float, float, float],
) -> Wire:
    """Create a wire containing an arc defined by three points."""
    try:
        if get_active_session() is not None:
            edge = make_three_point_arc_redge(start, middle, end)
            return make_wire_from_edges_rwire([edge])

        with suspend_graph_recording():
            edge = make_three_point_arc_redge(start, middle, end)
        wire_shape = make_wire_from_edges_ocp([edge.wrapped])
        return cast(
            Wire,
            _finalize_primitive_shape(
                Wire(wire_shape),
                op="make_three_point_arc_wire",
                params={"start": start, "middle": middle, "end": end},
                tags={"primitive", "wire"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_three_point_arc_rwire",
            what_happened="Failed to create a wire from the three-point arc.",
            possible_causes=[
                "The arc edge could not be created.",
                "The wire assembly step rejected the generated edge.",
            ],
            how_to_fix=[
                "Verify the three arc points first.",
                "If the edge is valid but the wire still fails, inspect the generated arc geometry.",
            ],
            error=e,
        )

def make_angle_arc_redge(
    center: Tuple[float, float, float],
    radius: ScalarLike,
    start_angle: ScalarLike,
    end_angle: ScalarLike,
    normal: Tuple[float, float, float] = (0, 0, 1),
) -> Edge:
    """Create an arc edge from a center, radius, and angle range."""
    try:
        radius_value = evaluate_scalar(radius)
        start_angle_value = evaluate_scalar(start_angle)
        end_angle_value = evaluate_scalar(end_angle)
        if radius_value <= 0:
            raise ValueError("半径必须大于0")
        if start_angle_value == end_angle_value:
            raise ValueError("起始角度和结束角度不能相同")

        cs = get_current_cs()
        center_value = cast(Tuple[float, float, float], evaluate_value(center))
        normal_value = cast(Tuple[float, float, float], evaluate_value(normal))
        center_global = cs.transform_point(np.array(center_value))
        normal_global = cs.transform_vector(np.array(normal_value))
        x_direction_global = cs.transform_vector(
            _default_plane_x_direction(normal_value)
        )

        edge_shape = make_arc_angle_edge(
            center_global,
            radius_value,
            start_angle_value,
            end_angle_value,
            normal_global,
            x_direction=x_direction_global,
        )
        return cast(
            Edge,
            _finalize_primitive_shape(
                Edge(edge_shape),
                op=_OP_MAKE_ANGLE_ARC_REDGE,
                params={
                    "center": center,
                    "radius": radius,
                    "start_angle": start_angle,
                    "end_angle": end_angle,
                    "normal": normal,
                },
                tags={"primitive", "edge"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_angle_arc_redge",
            what_happened="Failed to create an angle-defined arc edge.",
            possible_causes=[
                "The radius is not positive.",
                "The start and end angles collapse to the same value.",
                "The center or normal is invalid, or the kernel rejected the arc.",
            ],
            how_to_fix=[
                "Use a positive radius.",
                "Make sure start_angle and end_angle are different.",
                "Pass a valid finite center and a non-zero normal vector.",
            ],
            error=e,
        )

def make_angle_arc_rwire(
    center: Tuple[float, float, float],
    radius: float,
    start_angle: float,
    end_angle: float,
    normal: Tuple[float, float, float] = (0, 0, 1),
) -> Wire:
    """Create a wire containing an arc defined by a center, radius, and angle range."""

    try:
        if get_active_session() is not None:
            edge = make_angle_arc_redge(center, radius, start_angle, end_angle, normal)
            return make_wire_from_edges_rwire([edge])

        with suspend_graph_recording():
            edge = make_angle_arc_redge(center, radius, start_angle, end_angle, normal)
        wire_shape = make_wire_from_edges_ocp([edge.wrapped])
        return cast(
            Wire,
            _finalize_primitive_shape(
                Wire(wire_shape),
                op="make_angle_arc_wire",
                params={
                    "center": center,
                    "radius": radius,
                    "start_angle": start_angle,
                    "end_angle": end_angle,
                    "normal": normal,
                },
                tags={"primitive", "wire"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_angle_arc_rwire",
            what_happened="Failed to create a wire from the angle-defined arc.",
            possible_causes=[
                "The underlying arc edge could not be created.",
                "The wire assembly step rejected the generated edge.",
            ],
            how_to_fix=[
                "Check the center, radius, angle range, and normal.",
                "Retry after validating the arc edge input values.",
            ],
            error=e,
        )

def _normalize_bspline_control_points(
    control_points: Sequence[Sequence[ScalarLike]],
) -> Tuple[Tuple[float, float, float], ...]:
    points = list(control_points)
    if not points:
        raise ValueError("control_points must contain at least one point")
    normalized: List[Tuple[float, float, float]] = []
    for index, point in enumerate(points):
        value = cast(Sequence[float], evaluate_value(point))
        if len(value) == 2:
            coords = (float(value[0]), float(value[1]), 0.0)
        elif len(value) == 3:
            coords = (float(value[0]), float(value[1]), float(value[2]))
        else:
            raise ValueError(f"control point {index} must be 2D or 3D")
        if not all(math.isfinite(component) for component in coords):
            raise ValueError(f"control point {index} contains a non-finite coordinate")
        normalized.append(coords)
    return tuple(normalized)

def _collapse_knot_vector(
    knots: Sequence[ScalarLike],
) -> Tuple[Tuple[float, ...], Tuple[int, ...]]:
    values = [float(evaluate_scalar(knot)) for knot in knots]
    if not values:
        raise ValueError("knots must not be empty")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("knots must contain only finite values")
    for previous, current in zip(values, values[1:]):
        if current < previous:
            raise ValueError(
                "knots must be non-decreasing when passed as a full knot vector"
            )
    unique: List[float] = []
    multiplicities: List[int] = []
    for value in values:
        if unique and abs(value - unique[-1]) <= 1e-12:
            multiplicities[-1] += 1
        else:
            unique.append(value)
            multiplicities.append(1)
    return tuple(unique), tuple(multiplicities)

def _default_bspline_knots(
    control_count: int, degree: int, periodic: bool
) -> Tuple[Tuple[float, ...], Tuple[int, ...]]:
    if periodic:
        knot_count = control_count + 1
        return (
            tuple(index / (knot_count - 1) for index in range(knot_count)),
            tuple(1 for _ in range(knot_count)),
        )
    knot_count = control_count - degree + 1
    if knot_count < 2:
        raise ValueError("control point count must be at least degree + 1")
    knots = tuple(index / (knot_count - 1) for index in range(knot_count))
    multiplicities = [degree + 1]
    multiplicities.extend(1 for _ in range(max(0, knot_count - 2)))
    multiplicities.append(degree + 1)
    return knots, tuple(multiplicities)

def _normalize_bspline_knots(
    *,
    control_count: int,
    degree: int,
    periodic: bool,
    knots: Optional[Sequence[ScalarLike]],
    multiplicities: Optional[Sequence[int]],
) -> Tuple[Tuple[float, ...], Tuple[int, ...]]:
    if knots is None:
        if multiplicities is not None:
            raise ValueError("multiplicities require explicit knots")
        unique_knots, mults = _default_bspline_knots(control_count, degree, periodic)
    elif multiplicities is None:
        unique_knots, mults = _collapse_knot_vector(knots)
    else:
        unique_knots = tuple(float(evaluate_scalar(knot)) for knot in knots)
        mults = tuple(int(value) for value in multiplicities)

    if len(unique_knots) != len(mults):
        raise ValueError("knots and multiplicities must have the same length")
    if len(unique_knots) < 2:
        raise ValueError("at least two unique knots are required")
    if any(not math.isfinite(knot) for knot in unique_knots):
        raise ValueError("knots must contain only finite values")
    for previous, current in zip(unique_knots, unique_knots[1:]):
        if current <= previous:
            raise ValueError("unique knots must be strictly increasing")
    if any(multiplicity <= 0 for multiplicity in mults):
        raise ValueError("multiplicities must be positive integers")
    if any(multiplicity > degree + 1 for multiplicity in mults):
        raise ValueError("multiplicities must not exceed degree + 1")

    expected_sum = control_count + (1 if periodic else degree + 1)
    actual_sum = sum(mults)
    if actual_sum != expected_sum:
        raise ValueError(
            "sum(multiplicities) must equal "
            f"{expected_sum} for this {'periodic' if periodic else 'non-periodic'} B-spline"
        )
    return tuple(unique_knots), tuple(mults)

def _normalize_bspline_weights(
    weights: Optional[Sequence[ScalarLike]], control_count: int
) -> Optional[Tuple[float, ...]]:
    if weights is None:
        return None
    values = tuple(float(evaluate_scalar(weight)) for weight in weights)
    if len(values) != control_count:
        raise ValueError("weights must contain exactly one value per control point")
    if any(not math.isfinite(value) or value <= 0.0 for value in values):
        raise ValueError("weights must be finite positive values")
    return values

def make_spline_redge(
    *,
    control_points: Sequence[Sequence[ScalarLike]],
    degree: int = 3,
    knots: Optional[Sequence[ScalarLike]] = None,
    multiplicities: Optional[Sequence[int]] = None,
    weights: Optional[Sequence[ScalarLike]] = None,
    periodic: bool = False,
) -> Edge:
    """Create an exact B-spline edge from named control-point parameters.

    Pass sampled curve points through `fit_cubic_bspline_control_points(...)` first,
    then pass the result fields explicitly as `control_points=...`, `knots=...`,
    and `multiplicities=...`. `control_points` are poles, not interpolation
    points; the curve generally does not pass through interior poles.
    """
    try:
        if isinstance(degree, bool) or int(degree) != degree:
            raise ValueError("degree must be an integer")
        degree_value = int(degree)
        if degree_value < 1:
            raise ValueError("degree must be at least 1")
        if degree_value > 25:
            raise ValueError("degree must be 25 or lower")
        periodic_value = bool(periodic)

        local_control_points = _normalize_bspline_control_points(control_points)
        if len(local_control_points) < degree_value + 1:
            raise ValueError("control point count must be at least degree + 1")
        resolved_knots, resolved_multiplicities = _normalize_bspline_knots(
            control_count=len(local_control_points),
            degree=degree_value,
            periodic=periodic_value,
            knots=knots,
            multiplicities=multiplicities,
        )
        resolved_weights = _normalize_bspline_weights(
            weights, len(local_control_points)
        )

        cs = get_current_cs()
        global_control_points = tuple(
            tuple(float(component) for component in cs.transform_point(np.array(point)))
            for point in local_control_points
        )
        edge_shape = make_bspline_edge(
            control_points=global_control_points,
            degree=degree_value,
            knots=resolved_knots,
            multiplicities=resolved_multiplicities,
            weights=resolved_weights,
            periodic=periodic_value,
        )
        edge = Edge(edge_shape)
        edge.set_metadata(
            "geo",
            {
                "type": "bspline",
                "degree": degree_value,
                "control_points": [list(point) for point in global_control_points],
                "knots": list(resolved_knots),
                "multiplicities": list(resolved_multiplicities),
                "weights": (
                    list(resolved_weights) if resolved_weights is not None else None
                ),
                "periodic": periodic_value,
            },
        )

        return cast(
            Edge,
            _finalize_primitive_shape(
                edge,
                op=_OP_MAKE_SPLINE_REDGE,
                params={
                    "control_points": control_points,
                    "degree": degree_value,
                    "knots": resolved_knots,
                    "multiplicities": resolved_multiplicities,
                    "weights": weights,
                    "periodic": periodic_value,
                },
                tags={"primitive", "edge"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_spline_redge",
            what_happened="Failed to create a spline edge.",
            possible_causes=[
                "The exact B-spline definition is inconsistent.",
                "Control points, knots, multiplicities, or weights are invalid.",
                "A sampled-point list was passed directly instead of fitted control points.",
            ],
            how_to_fix=[
                "Pass keyword arguments such as control_points=..., degree=3, knots=..., multiplicities=....",
                "Use fit_cubic_bspline_control_points(sample_points) for sampled curves, then pass its result fields explicitly.",
                "Ensure sum(multiplicities) matches the exact B-spline degree/control-count rule.",
            ],
            error=e,
        )

def _normalize_interpolation_points(
    points: Sequence[Sequence[ScalarLike]],
    *,
    periodic: bool,
    tolerance: float,
) -> Tuple[Tuple[float, float, float], ...]:
    normalized = list(_normalize_bspline_control_points(points))
    if periodic and len(normalized) >= 2:
        if (
            np.linalg.norm(np.asarray(normalized[0]) - np.asarray(normalized[-1]))
            <= tolerance
        ):
            normalized.pop()
    minimum = 3 if periodic else 2
    if len(normalized) < minimum:
        qualifier = "distinct" if periodic else ""
        raise ValueError(
            f"interpolation requires at least {minimum} {qualifier} points".replace(
                "  ", " "
            )
        )
    adjacent_pairs = list(zip(normalized, normalized[1:]))
    if periodic:
        adjacent_pairs.append((normalized[-1], normalized[0]))
    for index, (first, second) in enumerate(adjacent_pairs):
        if np.linalg.norm(np.asarray(first) - np.asarray(second)) <= tolerance:
            second_index = (index + 1) % len(normalized)
            raise ValueError(
                f"interpolation points {index} and {second_index} are within "
                f"the interpolation tolerance"
            )
    return tuple(normalized)

def make_interpolated_spline_redge(
    *,
    points: Sequence[Sequence[ScalarLike]],
    periodic: bool = False,
    tolerance: ScalarLike = 1.0e-6,
) -> Edge:
    """Interpolate an exact B-spline edge through the supplied points."""
    try:
        periodic_value = bool(periodic)
        tolerance_value = float(evaluate_scalar(tolerance))
        if not math.isfinite(tolerance_value) or tolerance_value <= 0.0:
            raise ValueError("tolerance must be a finite positive value")
        local_points = _normalize_interpolation_points(
            points,
            periodic=periodic_value,
            tolerance=tolerance_value,
        )
        cs = get_current_cs()
        global_points = tuple(
            tuple(float(component) for component in cs.transform_point(np.array(point)))
            for point in local_points
        )
        edge = Edge(
            make_interpolated_bspline_edge(
                global_points,
                periodic=periodic_value,
                tolerance=tolerance_value,
            )
        )
        edge.set_metadata(
            "geo",
            {
                "type": "bspline",
                "construction": "interpolated",
                "interpolation_points": [list(point) for point in global_points],
                "periodic": periodic_value,
                "tolerance": tolerance_value,
            },
        )
        return cast(
            Edge,
            _finalize_primitive_shape(
                edge,
                op=_OP_MAKE_INTERPOLATED_SPLINE_REDGE,
                params={
                    "points": points,
                    "periodic": periodic_value,
                    "tolerance": tolerance,
                },
                tags={"primitive", "edge"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_interpolated_spline_redge",
            what_happened="Failed to interpolate a B-spline edge through the input points.",
            possible_causes=[
                "Too few distinct interpolation points were provided.",
                "Consecutive points are duplicated or contain invalid coordinates.",
                "The requested periodic interpolation is geometrically inconsistent.",
            ],
            how_to_fix=[
                "Provide at least two open-curve points or three periodic-curve points.",
                "Remove consecutive duplicate points; a repeated periodic endpoint is optional.",
                "Use a smaller positive tolerance when nearby points must remain distinct.",
            ],
            error=e,
        )

def make_interpolated_spline_rwire(
    *,
    points: Sequence[Sequence[ScalarLike]],
    periodic: bool = False,
    tolerance: ScalarLike = 1.0e-6,
) -> Wire:
    """Create a one-edge wire that interpolates the supplied points."""
    try:
        edge_kwargs = {
            "points": points,
            "periodic": periodic,
            "tolerance": tolerance,
        }
        if get_active_session() is not None:
            edge = make_interpolated_spline_redge(**edge_kwargs)
            return make_wire_from_edges_rwire([edge])

        with suspend_graph_recording():
            edge = make_interpolated_spline_redge(**edge_kwargs)
        wire_shape = make_wire_from_edges_ocp([edge.wrapped])
        return cast(
            Wire,
            _finalize_primitive_shape(
                Wire(wire_shape),
                op="make_interpolated_spline_wire",
                params=edge_kwargs,
                tags={"primitive", "wire"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_interpolated_spline_rwire",
            what_happened="Failed to create an interpolated spline wire.",
            possible_causes=[
                "The interpolated spline edge could not be created.",
                "The kernel rejected the resulting one-edge wire.",
            ],
            how_to_fix=[
                "Validate the interpolation points and tolerance.",
                "Use periodic=True for a closed profile and omit a duplicated final point.",
            ],
            error=e,
        )

def make_periodic_spline_rwire(
    *,
    points: Sequence[Sequence[ScalarLike]],
    tolerance: ScalarLike = 1.0e-6,
) -> Wire:
    """Create a closed periodic spline wire interpolating the supplied points."""
    return make_interpolated_spline_rwire(
        points=points,
        periodic=True,
        tolerance=tolerance,
    )

def make_spline_rwire(
    *,
    control_points: Sequence[Sequence[ScalarLike]],
    degree: int = 3,
    knots: Optional[Sequence[ScalarLike]] = None,
    multiplicities: Optional[Sequence[int]] = None,
    weights: Optional[Sequence[ScalarLike]] = None,
    periodic: bool = False,
) -> Wire:
    """Create a wire containing one exact B-spline edge."""
    try:
        edge_kwargs = {
            "control_points": control_points,
            "degree": degree,
            "knots": knots,
            "multiplicities": multiplicities,
            "weights": weights,
            "periodic": periodic,
        }
        if get_active_session() is not None:
            edge = make_spline_redge(**edge_kwargs)
            return make_wire_from_edges_rwire([edge])

        with suspend_graph_recording():
            edge = make_spline_redge(**edge_kwargs)
        wire_shape = make_wire_from_edges_ocp([edge.wrapped])
        rv = Wire(wire_shape)
        return cast(
            Wire,
            _finalize_primitive_shape(
                rv,
                op="make_spline_wire",
                params=edge_kwargs,
                tags={"primitive", "wire"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_spline_rwire",
            what_happened="Failed to create a spline wire.",
            possible_causes=[
                "The spline edge could not be created.",
                "The exact B-spline definition is inconsistent.",
                "The kernel rejected the resulting wire geometry.",
            ],
            how_to_fix=[
                "Validate the B-spline control points, degree, knots, multiplicities, and weights first.",
                "For sampled curves, call fit_cubic_bspline_control_points(...) and pass the result fields explicitly.",
                "Retry after inspecting the evaluated spline inputs.",
            ],
            error=e,
        )

def make_polyline_rwire(
    points: List[Tuple[ScalarLike, ScalarLike, ScalarLike]], closed: bool = False
) -> Wire:
    """Create a polyline wire from a point list."""
    try:
        if len(points) < 2:
            raise ValueError("至少需要2个点")

        if get_active_session() is not None:
            edges = [
                make_line_redge(points[idx], points[idx + 1])
                for idx in range(len(points) - 1)
            ]
            if closed and len(points) > 2:
                edges.append(make_line_redge(points[-1], points[0]))
            return make_wire_from_edges_rwire(edges)

        cs = get_current_cs()

        # 转换所有点到全局坐标系
        global_points = []
        for point in points:
            point_value = cast(Tuple[float, float, float], evaluate_value(point))
            global_point = cs.transform_point(np.array(point_value))
            global_points.append(tuple(float(v) for v in global_point))

        wire_shape = make_polyline_wire(
            [
                (float(point[0]), float(point[1]), float(point[2]))
                for point in global_points
            ],
            closed=closed,
        )
        return cast(
            Wire,
            _finalize_primitive_shape(
                Wire(wire_shape),
                op="make_polyline_wire",
                params={"points": points, "closed": closed},
                tags={"primitive", "wire"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_polyline_rwire",
            what_happened="Failed to create a polyline wire.",
            possible_causes=[
                "Fewer than two points were provided.",
                "One or more points are invalid or non-finite.",
                "The kernel rejected the resulting polyline geometry.",
            ],
            how_to_fix=[
                "Pass at least two finite 3D points.",
                "If closed=True, ensure the sequence describes a valid loop.",
                "Inspect the evaluated points before retrying.",
            ],
            error=e,
        )

def make_helix_redge(
    pitch: ScalarLike,
    height: ScalarLike,
    radius: ScalarLike,
    center: Tuple[float, float, float] = (0, 0, 0),
    dir: Tuple[float, float, float] = (0, 0, 1),
    *,
    handedness: str = "Right",
) -> Edge:
    """Create a helix edge, right- or left-handed."""
    try:
        if handedness not in {"Right", "Left"}:
            raise ValueError("handedness 必须是 'Right' 或 'Left'")
        pitch_value = evaluate_scalar(pitch)
        height_value = evaluate_scalar(height)
        radius_value = evaluate_scalar(radius)
        if pitch_value <= 0:
            raise ValueError("螺距必须大于0")
        if height_value <= 0:
            raise ValueError("高度必须大于0")
        if radius_value <= 0:
            raise ValueError("半径必须大于0")

        cs = get_current_cs()
        center_value = cast(Tuple[float, float, float], evaluate_value(center))
        dir_value = cast(Tuple[float, float, float], evaluate_value(dir))
        global_center = cs.transform_point(np.array(center_value))
        global_dir = cs.transform_vector(np.array(dir_value))
        global_x_direction = cs.transform_vector(_default_plane_x_direction(dir_value))

        wire_shape = make_helix_wire(
            pitch_value,
            height_value,
            radius_value,
            global_center,
            global_dir,
            x_direction=global_x_direction,
            handedness=handedness,
        )
        wire = Wire(wire_shape)
        edges = wire._iter_edges()
        if not edges:
            raise ValueError("无法从螺旋线中提取边")
        helix_edge = edges[0]
        return cast(
            Edge,
            _finalize_primitive_shape(
                helix_edge,
                op=_OP_MAKE_HELIX_REDGE,
                params={
                    "pitch": pitch,
                    "height": height,
                    "radius": radius,
                    "center": center,
                    "dir": dir,
                    "handedness": handedness,
                },
                tags={"primitive", "edge"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_helix_redge",
            what_happened="Failed to create a helix edge.",
            possible_causes=[
                "Pitch, height, or radius is not positive.",
                "The center or direction vector is invalid.",
                "The kernel rejected the helix definition.",
            ],
            how_to_fix=[
                "Use positive pitch, height, and radius values.",
                "Pass a valid center and a non-zero direction vector.",
                "Inspect the evaluated helix parameters before retrying.",
            ],
            error=e,
        )

def make_helix_rwire(
    pitch: float,
    height: float,
    radius: float,
    center: Tuple[float, float, float] = (0, 0, 0),
    dir: Tuple[float, float, float] = (0, 0, 1),
    *,
    handedness: str = "Right",
) -> Wire:
    """Create a helix wire, right- or left-handed."""
    try:
        if get_active_session() is not None:
            edge = make_helix_redge(
                pitch, height, radius, center=center, dir=dir,
                handedness=handedness,
            )
            return make_wire_from_edges_rwire([edge])

        cs = get_current_cs()
        global_center = cs.transform_point(np.array(center))
        global_dir = cs.transform_vector(np.array(dir))
        global_x_direction = cs.transform_vector(_default_plane_x_direction(dir))

        wire_shape = make_helix_wire(
            pitch,
            height,
            radius,
            global_center,
            global_dir,
            x_direction=global_x_direction,
        )
        return cast(
            Wire,
            _finalize_primitive_shape(
                Wire(wire_shape),
                op="make_helix_wire",
                params={
                    "pitch": pitch,
                    "height": height,
                    "radius": radius,
                    "center": center,
                    "dir": dir,
                },
                tags={"primitive", "wire"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_helix_rwire",
            what_happened="Failed to create a helix wire.",
            possible_causes=[
                "The helix parameters are invalid.",
                "The direction vector is zero or malformed.",
                "The kernel rejected the wire geometry.",
            ],
            how_to_fix=[
                "Use positive pitch, height, and radius values.",
                "Pass a valid center and a non-zero direction vector.",
                "Retry after logging the evaluated helix parameters.",
            ],
            error=e,
        )

__all__ = tuple(name for name in globals() if not name.startswith("__"))

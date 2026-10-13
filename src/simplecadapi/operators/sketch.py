"""Sketch operator implementations."""

from __future__ import annotations

from ._support import *

def make_sketch_rsketch(
    name: Optional[str] = None,
    *,
    plane: Any = "XY",
    sketch_id: Optional[str] = None,
) -> Sketch:
    """Create an empty declarative sketch document.

    Use this API, not concrete edge/wire constructors, when the intent is to
    build a sketch profile with constraints.
    """
    try:
        session = get_active_session()
        resolved_sketch_id = (
            sketch_id
            if sketch_id is not None or session is None
            else session.allocate_object_id("sketch")
        )
        sketch = Sketch(
            name=name,
            plane=_sketch_plane_in_current_coordinates(plane),
            sketch_id=resolved_sketch_id,
        )
        return cast(
            Sketch,
            _finalize_runtime_object(
                sketch,
                op=_OP_MAKE_SKETCH_RSKETCH,
                params={"name": name, "plane": plane, "sketch_id": sketch.sketch_id},
                tags={"sketch"},
                entity_type="Sketch",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_sketch_rsketch",
            what_happened="Failed to create a sketch document.",
            possible_causes=["The sketch name or plane payload is invalid."],
            how_to_fix=["Use plane='XY', 'XZ', 'YZ', or a valid plane mapping."],
            error=e,
        )

def _safe_semantic_tag(prefix: str, value: object) -> str:
    raw = str(value or "unnamed").strip().lower()
    raw = re.sub(r"[^a-z0-9_-]+", ".", raw).strip(".")
    raw = re.sub(r"\.+", ".", raw)
    segments: List[str] = []
    for segment in raw.split("."):
        if not segment:
            continue
        if not segment[0].isalpha():
            segment = f"id_{segment}"
        segments.append(segment)
    if not segments:
        segments = ["unnamed"]
    return normalize_tag(f"{prefix}.{'.'.join(segments)}", strict=True)

def _sketch_target_to_path(target: SketchRef) -> str:
    if target.kind == "point" and target.subentity != "geometry":
        return f"{target.entity_id}.{target.subentity}"
    return target.entity_id

def _resolve_sketch_target(
    sketch: Sketch,
    target: Union[SketchRef, str],
    *,
    expected: Optional[Union[str, Sequence[str]]] = None,
) -> SketchRef:
    return sketch.resolve_target(target, expected=expected)

def _resolve_sketch_targets(
    sketch: Sketch,
    targets: Sequence[Union[SketchRef, str]],
    *,
    expected: Optional[Sequence[Optional[Union[str, Sequence[str]]]]] = None,
) -> List[SketchRef]:
    refs: List[SketchRef] = []
    for index, target in enumerate(targets):
        target_expected = expected[index] if expected is not None else None
        refs.append(_resolve_sketch_target(sketch, target, expected=target_expected))
    return refs

def _begin_linear_sketch_edits(sketch: Sketch) -> Sketch:
    """Enable in-place edits for one private, linear sketch construction chain."""
    sketch._set_runtime("sketch.linear_edit", True)
    return sketch

def _end_linear_sketch_edits(sketch: Sketch) -> Sketch:
    sketch._set_runtime("sketch.linear_edit", False)
    return sketch

def _sketch_update_target(sketch: Sketch) -> Sketch:
    if sketch._get_runtime("sketch.linear_edit", False):
        sketch._last_solve_result = None
        return sketch
    return sketch.clone(include_solve=False)

def add_point_rsketch(
    sketch: Sketch,
    point_id: str,
    x: ScalarLike,
    y: ScalarLike,
) -> Sketch:
    """Add a named point entity and return an updated sketch document."""
    try:
        updated = _sketch_update_target(sketch)
        updated.add_point(point_id, x, y)
        return cast(
            Sketch,
            _finalize_runtime_object(
                updated,
                op=_OP_ADD_POINT_RSKETCH,
                params={
                    "sketch_id": updated.sketch_id,
                    "point_id": point_id,
                    "x": x,
                    "y": y,
                },
                input_objects=[sketch],
                tags={"sketch", "point"},
                entity_type="Sketch",
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="add_point_rsketch",
            what_happened="Failed to add a point to the sketch.",
            possible_causes=[
                "The sketch is invalid.",
                "The point id is duplicated.",
                "The x or y value is not a valid scalar or expression.",
            ],
            how_to_fix=[
                "Use a unique point id within the sketch.",
                "Pass numeric x/y values or valid scalar expressions.",
            ],
            error=e,
        )

def get_sketch_entity_rsketchref(
    sketch: Sketch,
    entity_id: str,
) -> SketchRef:
    """Return a stable ref for a named sketch entity."""
    return sketch.ref(entity_id)

def get_sketch_point_rsketchref(
    sketch: Sketch,
    point_path: str,
) -> SketchRef:
    """Return a stable ref for a sketch point or endpoint path."""
    return sketch.point_ref(point_path)

def add_line_rsketch(
    sketch: Sketch,
    entity_id: str,
    start: Union[SketchRef, str],
    end: Union[SketchRef, str],
    *,
    construction: bool = False,
) -> Sketch:
    """Add a named line entity and return an updated sketch document."""
    try:
        start_ref = _resolve_sketch_target(sketch, start, expected="point")
        end_ref = _resolve_sketch_target(sketch, end, expected="point")
        updated = _sketch_update_target(sketch)
        updated.add_line(entity_id, start_ref, end_ref, construction=construction)
        return cast(
            Sketch,
            _finalize_runtime_object(
                updated,
                op=_OP_ADD_LINE_RSKETCH,
                params={
                    "sketch_id": updated.sketch_id,
                    "entity_id": entity_id,
                    "start": _sketch_target_to_path(start_ref),
                    "end": _sketch_target_to_path(end_ref),
                    "construction": construction,
                },
                input_objects=[sketch],
                tags={"sketch", "line"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="add_line_rsketch",
            what_happened="Failed to add a line to the sketch.",
            possible_causes=[
                "The line id is duplicated.",
                "One of the endpoint refs does not belong to this sketch.",
                "Both endpoints resolve to the same point.",
            ],
            how_to_fix=[
                "Use a unique line id.",
                "Create endpoints with add_point_rsketch(...) and refer to them by id.",
            ],
            error=e,
        )

def add_circle_rsketch(
    sketch: Sketch,
    entity_id: str,
    center: Union[SketchRef, str],
    radius: ScalarLike,
    *,
    construction: bool = False,
) -> Sketch:
    """Add a named circle entity and return an updated sketch document."""
    try:
        center_ref = _resolve_sketch_target(sketch, center, expected="point")
        updated = _sketch_update_target(sketch)
        updated.add_circle(entity_id, center_ref, radius, construction=construction)
        return cast(
            Sketch,
            _finalize_runtime_object(
                updated,
                op=_OP_ADD_CIRCLE_RSKETCH,
                params={
                    "sketch_id": updated.sketch_id,
                    "entity_id": entity_id,
                    "center": _sketch_target_to_path(center_ref),
                    "radius": radius,
                    "construction": construction,
                },
                input_objects=[sketch],
                tags={"sketch", "circle"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="add_circle_rsketch",
            what_happened="Failed to add a circle to the sketch.",
            possible_causes=[
                "The circle id is duplicated.",
                "The center ref does not belong to this sketch.",
                "The radius is not positive.",
            ],
            how_to_fix=[
                "Use a unique circle id and a positive radius.",
                "Create the center with add_point_rsketch(...) and refer to it by id.",
            ],
            error=e,
        )

def add_ellipse_rsketch(
    sketch: Sketch,
    entity_id: str,
    center: Union[SketchRef, str],
    major_point: Union[SketchRef, str],
    minor_point: Union[SketchRef, str],
    *,
    construction: bool = False,
) -> Sketch:
    """Add an ellipse entity derived from three solving points.

    The ellipse shape is a pure function of the center, major-axis, and
    minor-axis points; radius constraints therefore solve natively.
    """
    try:
        center_ref = _resolve_sketch_target(sketch, center, expected="point")
        major_ref = _resolve_sketch_target(sketch, major_point, expected="point")
        minor_ref = _resolve_sketch_target(sketch, minor_point, expected="point")
        updated = _sketch_update_target(sketch)
        updated.add_ellipse(
            entity_id,
            center_ref,
            major_ref,
            minor_ref,
            construction=construction,
        )
        return cast(
            Sketch,
            _finalize_runtime_object(
                updated,
                op=_OP_ADD_ELLIPSE_RSKETCH,
                params={
                    "sketch_id": updated.sketch_id,
                    "entity_id": entity_id,
                    "center": _sketch_target_to_path(center_ref),
                    "major_point": _sketch_target_to_path(major_ref),
                    "minor_point": _sketch_target_to_path(minor_ref),
                    "construction": construction,
                },
                input_objects=[sketch],
                tags={"sketch", "ellipse"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="add_ellipse_rsketch",
            what_happened="Failed to add an ellipse to the sketch.",
            possible_causes=[
                "The entity id is duplicated.",
                "One of the axis point refs does not belong to this sketch.",
                "The three axis points are not distinct or are degenerate.",
                "The minor axis exceeds the major axis at the initial positions.",
            ],
            how_to_fix=[
                "Use a unique entity id.",
                "Create the center, major, and minor points first.",
                "Place the major point farther from the center than the minor point.",
            ],
            error=e,
        )

def add_bspline_rsketch(
    sketch: Sketch,
    entity_id: str,
    start: Union[SketchRef, str],
    end: Union[SketchRef, str],
    control_points: Sequence[Any],
    degree: int = 3,
    knots: Optional[Sequence[float]] = None,
    multiplicities: Optional[Sequence[int]] = None,
    weights: Optional[Sequence[float]] = None,
    periodic: bool = False,
    *,
    construction: bool = False,
) -> Sketch:
    """Add a B-spline curve entity to a sketch.

    The start/end point refs link the B-spline into a closed profile
    loop. A closed curve may reuse one seam ref for both endpoints.
    Control points may be literal 2-D coordinates or point refs. A periodic
    seam links topology without replacing the periodic curve's poles.
    """
    try:
        start_ref = _resolve_sketch_target(sketch, start, expected="point")
        end_ref = _resolve_sketch_target(sketch, end, expected="point")
        updated = _sketch_update_target(sketch)
        updated.add_bspline(
            entity_id,
            start_ref,
            end_ref,
            control_points=control_points,
            degree=degree,
            knots=knots,
            multiplicities=multiplicities,
            weights=weights,
            periodic=periodic,
            construction=construction,
        )
        bspline_data = updated.entities[str(entity_id)].data
        return cast(
            Sketch,
            _finalize_runtime_object(
                updated,
                op=_OP_ADD_BSPLINE_RSKETCH,
                params={
                    "sketch_id": updated.sketch_id,
                    "entity_id": entity_id,
                    "start": _sketch_target_to_path(start_ref),
                    "end": _sketch_target_to_path(end_ref),
                    "control_points": bspline_data["control_points"],
                    "degree": bspline_data["degree"],
                    "knots": bspline_data["knots"],
                    "multiplicities": bspline_data["multiplicities"],
                    "weights": bspline_data["weights"],
                    "periodic": bspline_data["periodic"],
                    "construction": construction,
                },
                input_objects=[sketch],
                tags={"sketch", "bspline"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="add_bspline_rsketch",
            what_happened="Failed to add a B-spline to the sketch.",
            possible_causes=[
                "The entity id is duplicated.",
                "The start or end ref does not belong to this sketch.",
                "Too few control points for the requested degree.",
            ],
            how_to_fix=[
                "Use a unique entity id.",
                "Create start and end points with add_point_rsketch(...) first.",
                "Pass at least degree+1 control points.",
            ],
            error=e,
        )

def add_arc_rsketch(
    sketch: Sketch,
    entity_id: str,
    start: Union[SketchRef, str],
    end: Union[SketchRef, str],
    center: Union[SketchRef, str],
    *,
    construction: bool = False,
) -> Sketch:
    """Add an arc entity to a sketch."""
    try:
        start_ref = _resolve_sketch_target(sketch, start, expected="point")
        end_ref = _resolve_sketch_target(sketch, end, expected="point")
        center_ref = _resolve_sketch_target(sketch, center, expected="point")
        updated = _sketch_update_target(sketch)
        updated.add_arc(
            entity_id,
            start_ref,
            end_ref,
            center_ref,
            construction=construction,
        )
        return cast(
            Sketch,
            _finalize_runtime_object(
                updated,
                op=_OP_ADD_ARC_RSKETCH,
                params={
                    "sketch_id": updated.sketch_id,
                    "entity_id": entity_id,
                    "start": _sketch_target_to_path(start_ref),
                    "end": _sketch_target_to_path(end_ref),
                    "center": _sketch_target_to_path(center_ref),
                    "construction": construction,
                },
                input_objects=[sketch],
                tags={"sketch", "arc"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="add_arc_rsketch",
            what_happened="Failed to add an arc to the sketch.",
            possible_causes=[
                "The entity id is duplicated.",
                "The start, end, or center ref does not belong to this sketch.",
                "The start and end points are the same.",
            ],
            how_to_fix=[
                "Use a unique entity id.",
                "Create start, end, and center points with add_point_rsketch(...) first.",
            ],
            error=e,
        )

def _constrain_rsketch(
    sketch: Sketch,
    kind: str,
    targets: Sequence[Union[SketchRef, str]],
    *,
    value: Any = None,
    constraint_id: Optional[str] = None,
    driving: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
    expected: Optional[Sequence[Optional[Union[str, Sequence[str]]]]] = None,
) -> Sketch:
    target_refs = _resolve_sketch_targets(sketch, targets, expected=expected)
    updated = _sketch_update_target(sketch)
    updated.add_constraint(
        kind,
        target_refs,
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        metadata=metadata,
    )
    op = _SKETCH_CONSTRAINT_OPS[kind]
    return cast(
        Sketch,
        _finalize_runtime_object(
            updated,
            op=op,
            params={
                "sketch_id": updated.sketch_id,
                "kind": kind,
                "targets": [_sketch_target_to_path(target) for target in target_refs],
                "value": value,
                "constraint_id": constraint_id,
                "driving": driving,
                "metadata": metadata or {},
            },
            input_objects=[sketch],
            tags={"sketch", "constraint"},
        ),
    )

def constrain_coincident_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two sketch points to be coincident."""
    return _constrain_rsketch(
        sketch,
        "coincident",
        [a, b],
        constraint_id=constraint_id,
        expected=["point", "point"],
    )

def constrain_connect_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Alias for `constrain_coincident_rsketch` using connection wording."""
    return _constrain_rsketch(
        sketch,
        "coincident",
        [a, b],
        constraint_id=constraint_id,
        expected=["point", "point"],
    )

def constrain_point_on_rsketch(
    sketch: Sketch,
    point: Union[SketchRef, str],
    entity: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain a sketch point to lie on a line, circle, or circular arc."""
    return _constrain_rsketch(
        sketch,
        "point_on",
        [point, entity],
        constraint_id=constraint_id,
        expected=["point", ("line", "circle", "arc")],
    )

def constrain_horizontal_rsketch(
    sketch: Sketch, line: Union[SketchRef, str], *, constraint_id: Optional[str] = None
) -> Sketch:
    """Constrain a sketch line to be horizontal."""
    return _constrain_rsketch(
        sketch, "horizontal", [line], constraint_id=constraint_id, expected=["line"]
    )

def constrain_vertical_rsketch(
    sketch: Sketch, line: Union[SketchRef, str], *, constraint_id: Optional[str] = None
) -> Sketch:
    """Constrain a sketch line to be vertical."""
    return _constrain_rsketch(
        sketch, "vertical", [line], constraint_id=constraint_id, expected=["line"]
    )

def constrain_points_horizontal_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two sketch points to be horizontally aligned."""
    return _constrain_rsketch(
        sketch,
        "points_horizontal",
        [a, b],
        constraint_id=constraint_id,
        expected=["point", "point"],
    )

def constrain_points_vertical_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two sketch points to be vertically aligned."""
    return _constrain_rsketch(
        sketch,
        "points_vertical",
        [a, b],
        constraint_id=constraint_id,
        expected=["point", "point"],
    )

def constrain_line_distance_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving minimum-distance constraint between two sketch lines.

    The constraint drives the distance from line ``a``'s start point to line
    ``b``; for parallel lines this is exactly the minimum distance between
    them. The solved point keeps its initial side of line ``b``.
    """
    return _constrain_rsketch(
        sketch,
        "line_distance",
        [a, b],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=["line", "line"],
    )

def constrain_normal_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain a line to be normal to a circle or arc.

    A normal line passes through the curve's center; argument order is free.
    """
    return _constrain_rsketch(
        sketch,
        "normal",
        [a, b],
        constraint_id=constraint_id,
        expected=[("line", "circle", "arc"), ("line", "circle", "arc")],
    )

def constrain_mirror_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    axis: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two same-kind entities to be mirror images about a line.

    Lines match endpoints by nearest initial position; circles match centers;
    arcs match endpoints and centers.
    """
    return _constrain_rsketch(
        sketch,
        "mirror",
        [a, axis, b],
        constraint_id=constraint_id,
        expected=[
            ("line", "circle", "arc"),
            "line",
            ("line", "circle", "arc"),
        ],
    )

def constrain_midpoint_points_rsketch(
    sketch: Sketch,
    mid: Union[SketchRef, str],
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain point ``mid`` to be the midpoint of points ``a`` and ``b``."""
    return _constrain_rsketch(
        sketch,
        "midpoint_points",
        [mid, a, b],
        constraint_id=constraint_id,
        expected=["point", "point", "point"],
    )

def constrain_parallel_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two sketch lines to be parallel."""
    return _constrain_rsketch(
        sketch,
        "parallel",
        [a, b],
        constraint_id=constraint_id,
        expected=["line", "line"],
    )

def constrain_perpendicular_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two sketch lines to be perpendicular."""
    return _constrain_rsketch(
        sketch,
        "perpendicular",
        [a, b],
        constraint_id=constraint_id,
        expected=["line", "line"],
    )

def constrain_collinear_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two sketch lines to lie on the same infinite line."""
    return _constrain_rsketch(
        sketch,
        "collinear",
        [a, b],
        constraint_id=constraint_id,
        expected=["line", "line"],
    )

def constrain_tangent_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    at_a: Optional[str] = None,
    at_b: Optional[str] = None,
    mode: str = "external",
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain supported curves to be tangent on an explicit branch.

    ``at_a``/``at_b`` select ``"start"`` or ``"end"`` for arc and
    B-spline endpoint tangency. Circle-circle tangency accepts
    ``mode="external"`` or ``mode="internal"``.
    """
    if at_a not in {None, "start", "end"} or at_b not in {None, "start", "end"}:
        raise ValueError("Tangent endpoint selectors must be 'start' or 'end'")
    if mode not in {"external", "internal"}:
        raise ValueError("Tangent mode must be 'external' or 'internal'")
    return _constrain_rsketch(
        sketch,
        "tangent",
        [a, b],
        constraint_id=constraint_id,
        metadata={"at_a": at_a, "at_b": at_b, "mode": mode},
        expected=[
            ("line", "circle", "arc", "bspline", "ellipse"),
            ("line", "circle", "arc", "bspline", "ellipse"),
        ],
    )

def constrain_concentric_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two sketch circles/arcs/ellipses to share a center."""
    return _constrain_rsketch(
        sketch,
        "concentric",
        [a, b],
        constraint_id=constraint_id,
        expected=[("circle", "arc", "ellipse"), ("circle", "arc", "ellipse")],
    )

def constrain_midpoint_rsketch(
    sketch: Sketch,
    point: Union[SketchRef, str],
    line: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain a sketch point to the midpoint of a line."""
    return _constrain_rsketch(
        sketch,
        "midpoint",
        [point, line],
        constraint_id=constraint_id,
        expected=["point", "line"],
    )

def constrain_symmetric_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    axis: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two sketch points to be symmetric about a line axis."""
    return _constrain_rsketch(
        sketch,
        "symmetric",
        [a, b, axis],
        constraint_id=constraint_id,
        expected=["point", "point", "line"],
    )

def constrain_equal_length_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two sketch lines to have equal length."""
    return _constrain_rsketch(
        sketch,
        "equal_length",
        [a, b],
        constraint_id=constraint_id,
        expected=["line", "line"],
    )

def constrain_equal_radius_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Constrain two circles/arcs to have equal radius."""
    return _constrain_rsketch(
        sketch,
        "equal_radius",
        [a, b],
        constraint_id=constraint_id,
        expected=[("circle", "arc"), ("circle", "arc")],
    )

def constrain_distance_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving point-to-point distance constraint."""
    return _constrain_rsketch(
        sketch,
        "distance",
        [a, b],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=["point", "point"],
    )

def constrain_distance_x_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving horizontal distance constraint."""
    return _constrain_rsketch(
        sketch,
        "distance_x",
        [a, b],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=["point", "point"],
    )

def constrain_distance_y_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving vertical distance constraint."""
    return _constrain_rsketch(
        sketch,
        "distance_y",
        [a, b],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=["point", "point"],
    )

def constrain_length_rsketch(
    sketch: Sketch,
    line: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving length constraint to a line, arc, or B-spline."""
    return _constrain_rsketch(
        sketch,
        "length",
        [line],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=[("line", "arc", "bspline")],
    )

def constrain_angle_rsketch(
    sketch: Sketch,
    a: Union[SketchRef, str],
    b: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving angle constraint between two sketch lines."""
    return _constrain_rsketch(
        sketch,
        "angle",
        [a, b],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=["line", "line"],
    )

def constrain_radius_rsketch(
    sketch: Sketch,
    circle: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving circle or arc radius constraint."""
    return _constrain_rsketch(
        sketch,
        "radius",
        [circle],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=[("circle", "arc")],
    )

def constrain_diameter_rsketch(
    sketch: Sketch,
    circle: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving circle or arc diameter constraint."""
    return _constrain_rsketch(
        sketch,
        "diameter",
        [circle],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=[("circle", "arc")],
    )

def constrain_major_radius_rsketch(
    sketch: Sketch,
    ellipse: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving major-radius constraint to a sketch ellipse."""
    return _constrain_rsketch(
        sketch,
        "major_radius",
        [ellipse],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=["ellipse"],
    )

def constrain_minor_radius_rsketch(
    sketch: Sketch,
    ellipse: Union[SketchRef, str],
    value: ScalarLike,
    *,
    constraint_id: Optional[str] = None,
    driving: bool = True,
) -> Sketch:
    """Add a driving minor-radius constraint to a sketch ellipse."""
    return _constrain_rsketch(
        sketch,
        "minor_radius",
        [ellipse],
        value=value,
        constraint_id=constraint_id,
        driving=driving,
        expected=["ellipse"],
    )

def constrain_fix_rsketch(
    sketch: Sketch,
    target: Union[SketchRef, str],
    *,
    constraint_id: Optional[str] = None,
) -> Sketch:
    """Fix a sketch point or entity to its initial coordinates."""
    return _constrain_rsketch(sketch, "fix", [target], constraint_id=constraint_id)

def inspect_sketch_rsketchresult(
    sketch: Sketch,
    *,
    require_fully_constrained: bool = False,
    strict: bool = True,
    tolerance: float = 1e-7,
    max_iterations: int = 80,
) -> SketchSolveResult:
    """Inspect sketch constraints by running the solver without recording graph nodes."""
    try:
        result = sketch.clone(include_solve=False).solve(
            require_fully_constrained=require_fully_constrained,
            strict=strict,
            tolerance=tolerance,
            max_iterations=max_iterations,
        )
        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="inspect_sketch_rsketchresult",
            what_happened="Failed to inspect the sketch constraints.",
            possible_causes=[
                "The sketch has invalid, conflicting, or underconstrained constraints.",
                "A constraint references a missing or wrong-kind entity.",
            ],
            how_to_fix=[
                "Inspect diagnostics with strict=False if needed.",
                "Add fix/dimension constraints until the intended profile is fully constrained.",
            ],
            error=e,
        )

def _sketch_solve_snapshot(result: SketchSolveResult) -> Dict[str, Any]:
    return result.to_dict()

def _sketch_source_metadata(
    sketch: Sketch,
    profile: int | str,
    profile_payload: Dict[str, Any],
    inner_profile_payloads: Sequence[Tuple[int | str, Dict[str, Any]]] = (),
) -> Dict[str, Any]:
    return {
        "sketch_id": sketch.sketch_id,
        "name": sketch.name,
        "plane": sketch.plane,
        "profile": profile,
        "profile_id": profile_payload.get("id"),
        "profile_kind": profile_payload.get("kind"),
        "inner_profiles": [
            {
                "profile": inner_profile,
                "profile_id": inner_payload.get("id"),
                "profile_kind": inner_payload.get("kind"),
            }
            for inner_profile, inner_payload in inner_profile_payloads
        ],
    }

def _sketch_edge_metadata(
    sketch: Sketch,
    entity_id: str,
    profile: int | str,
    profile_payload: Dict[str, Any],
    *,
    loop_role: str = "outer",
) -> Dict[str, Any]:
    entity = sketch.entities[str(entity_id)]
    return {
        "sketch_id": sketch.sketch_id,
        "sketch_name": sketch.name,
        "entity_id": str(entity_id),
        "kind": entity.kind,
        "profile": profile,
        "profile_id": profile_payload.get("id"),
        "loop_role": loop_role,
    }

def _sketch_promotion_tags(
    sketch: Sketch,
    profile_payload: Dict[str, Any],
) -> Tuple[str, str]:
    sketch_tag = _safe_semantic_tag("sketch", sketch.name or sketch.sketch_id)
    profile_tag = _safe_semantic_tag(
        "sketch_profile", profile_payload.get("id", "profile")
    )
    return sketch_tag, profile_tag

def _sketch_promotion_map(
    sketch: Sketch,
    profile: int | str,
    profile_payload: Dict[str, Any],
    *,
    inner_profile_payloads: Sequence[Tuple[int | str, Dict[str, Any]]] = (),
    target_kind: Optional[str] = None,
) -> Dict[str, Any]:
    sketch_tag, profile_tag = _sketch_promotion_tags(sketch, profile_payload)
    profile_local_name = _sketch_topology_tag_local_name(
        profile_payload.get("id", "profile")
    )
    profile_identity_tag = f"{sketch_tag}.profile.{profile_local_name}"
    edges: List[Dict[str, Any]] = []
    loops: List[Dict[str, Any]] = []
    loop_specs = [
        (profile, profile_payload, "outer"),
        *[
            (inner_profile, inner_payload, "inner")
            for inner_profile, inner_payload in inner_profile_payloads
        ],
    ]
    for loop_profile, loop_payload, loop_role in loop_specs:
        loop_sketch_tag, loop_profile_tag = _sketch_promotion_tags(sketch, loop_payload)
        loop_edges: List[Dict[str, Any]] = []
        for entity_id in loop_payload.get("entity_ids", []):
            entity_tag = _safe_semantic_tag("sketch_entity", entity_id)
            entity_local_name = _sketch_topology_tag_local_name(entity_id)
            edge_payload = {
                "entity_id": str(entity_id),
                "profile": loop_profile,
                "profile_id": loop_payload.get("id"),
                "loop_role": loop_role,
                "target_kind": "edge",
                "tags": [loop_sketch_tag, loop_profile_tag, entity_tag],
                "topology_name": {
                    "kind": "edge",
                    "name": f"{loop_sketch_tag}.entity.{entity_local_name}",
                    "local_name": entity_local_name,
                },
                "metadata": {
                    "sketch_ref": _sketch_edge_metadata(
                        sketch,
                        str(entity_id),
                        loop_profile,
                        loop_payload,
                        loop_role=loop_role,
                    )
                },
            }
            loop_edges.append(edge_payload)
            edges.append(edge_payload)
        loop_local_name = _sketch_topology_tag_local_name(
            loop_payload.get("id", "profile")
        )
        loops.append(
            {
                "role": loop_role,
                "profile": loop_profile,
                "profile_id": loop_payload.get("id"),
                "profile_kind": loop_payload.get("kind"),
                "topology_name": {
                    "kind": "wire",
                    "name": f"{loop_sketch_tag}.profile.{loop_local_name}",
                    "local_name": loop_local_name,
                },
                "edges": loop_edges,
            }
        )
    return {
        "schema_version": "2.0",
        "profile": profile,
        "profile_id": profile_payload.get("id"),
        "profile_kind": profile_payload.get("kind"),
        "tags": [sketch_tag, profile_tag],
        "topology_name": {
            "kind": target_kind or "profile",
            "name": profile_identity_tag,
            "local_name": profile_local_name,
        },
        "loops": loops,
        "edges": edges,
    }

def _apply_sketch_promotion_metadata(
    shape: Union[Wire, Face],
    *,
    sketch: Sketch,
    profile: int | str,
    profile_payload: Dict[str, Any],
    inner_profile_payloads: Sequence[Tuple[int | str, Dict[str, Any]]],
    source_wires: Sequence[Tuple[int | str, Dict[str, Any], str, Wire]],
    solve_snapshot: Dict[str, Any],
) -> None:
    source_sketch = _sketch_source_metadata(
        sketch,
        profile,
        profile_payload,
        inner_profile_payloads,
    )
    promotion_map = _sketch_promotion_map(
        sketch,
        profile,
        profile_payload,
        inner_profile_payloads=inner_profile_payloads,
        target_kind="wire" if isinstance(shape, Wire) else "face",
    )
    sketch_tag, profile_tag = _sketch_promotion_tags(sketch, profile_payload)

    shape.set_metadata("source_sketch", source_sketch)
    shape.set_metadata("sketch_solve", solve_snapshot)
    shape.set_metadata("sketch_promotion", promotion_map)
    shape._apply_tag(sketch_tag, propagate=False)
    shape._apply_tag(profile_tag, propagate=False)

    wires: List[Wire] = []
    if isinstance(shape, Wire):
        wires = [shape]
    elif isinstance(shape, Face):
        wires = shape._iter_wires()

    for wire in wires:
        matches = [
            source for source in source_wires if source[3].wrapped.IsSame(wire.wrapped)
        ]
        if len(matches) != 1:
            raise ValueError(
                "Sketch promotion cannot establish exact profile-to-wire correspondence"
            )
        loop_profile, loop_payload, _loop_role, _source_wire = matches[0]
        loop_sketch_tag, loop_profile_tag = _sketch_promotion_tags(sketch, loop_payload)
        wire.set_metadata("source_sketch", source_sketch)
        wire.set_metadata("sketch_solve", solve_snapshot)
        wire.set_metadata("sketch_promotion", promotion_map)
        wire.set_metadata(
            "sketch_profile",
            _sketch_source_metadata(sketch, loop_profile, loop_payload),
        )
        wire._apply_tag(loop_sketch_tag, propagate=False)
        wire._apply_tag(loop_profile_tag, propagate=False)

    source_edges = [
        (loop_profile, loop_payload, loop_role, str(entity_id), source_edge)
        for loop_profile, loop_payload, loop_role, source_wire in source_wires
        for entity_id, source_edge in source_wire._get_runtime(
            "sketch.entity_edges", []
        )
    ]
    for edge in shape._iter_edges():
        matches = [source for source in source_edges if source[4].IsSame(edge.wrapped)]
        if len(matches) != 1:
            raise ValueError(
                "Sketch promotion cannot establish exact entity-to-edge correspondence"
            )
        loop_profile, loop_payload, loop_role, entity_id, _source_edge = matches[0]
        loop_sketch_tag, loop_profile_tag = _sketch_promotion_tags(sketch, loop_payload)
        entity_tag = _safe_semantic_tag("sketch_entity", entity_id)
        edge.set_metadata(
            "sketch_ref",
            _sketch_edge_metadata(
                sketch,
                entity_id,
                loop_profile,
                loop_payload,
                loop_role=loop_role,
            ),
        )
        edge.set_metadata("source_sketch", source_sketch)
        edge._apply_tag(loop_sketch_tag, propagate=False)
        edge._apply_tag(loop_profile_tag, propagate=False)
        edge._apply_tag(entity_tag, propagate=False)

def _sketch_topology_tag_local_name(value: object) -> str:
    """Return the normalized local segment for a sketch topology tag."""

    return _safe_semantic_tag("name", value).split(".", 1)[1]

def _sketch_topology_identity_binding(
    tag: str,
    *,
    kind: str,
    local_name: str,
    operation: str,
    sketch: Sketch,
    profile_id: str,
    target_topo_id: str,
    entity_id: Optional[str] = None,
) -> TagBinding:
    rule_id = "simplecad.sketch_promotion_topology_name"
    binding_key = "|".join(
        (
            rule_id,
            operation,
            sketch.sketch_id,
            profile_id,
            entity_id or "",
            target_topo_id,
            tag,
        )
    )
    return TagBinding(
        tag=tag,
        producer=TagProducer(
            "auto_rule",
            rule_id=rule_id,
            rule_version="1.0",
        ),
        target=TagTarget("scope_root"),
        propagation=TagPropagation(
            topology=(
                TopologyPropagation.DOWNWARD
                if kind == "face"
                else TopologyPropagation.LOCAL
            ),
            lineage=LineagePolicy.CONTINUATION_FRAGMENT,
        ),
        evidence=TagEvidence(
            "topology_change",
            {
                "operation": operation,
                "target_topo_id": target_topo_id,
                "evidence_method": "SketchPromotionMap",
                "sketch_promotion": {
                    "sketch_id": sketch.sketch_id,
                    "profile_id": profile_id,
                    **({"entity_id": entity_id} if entity_id is not None else {}),
                },
                "topology_name": {
                    "kind": kind,
                    "name": tag,
                    "local_name": local_name,
                },
            },
        ),
        certainty=TagCertainty.PROVEN,
        lifecycle=TagLifecycle.RECOMPUTE,
        binding_id=f"tag_binding_{uuid.uuid5(uuid.NAMESPACE_URL, binding_key).hex}",
    )

def _apply_sketch_promotion_identity_tags(
    shape: Union[Wire, Face],
    *,
    sketch: Sketch,
    profile_payload: Dict[str, Any],
    source_wires: Sequence[Tuple[int | str, Dict[str, Any], str, Wire]],
    operation: str,
) -> Union[Wire, Face]:
    """Attach topology-identity tags from an exact sketch promotion map."""

    sketch_prefix = _safe_semantic_tag("sketch", sketch.name or sketch.sketch_id)
    profile_local_name = _sketch_topology_tag_local_name(
        profile_payload.get("id", "profile")
    )
    profile_kind = "wire" if isinstance(shape, Wire) else "face"
    profile_tag = f"{sketch_prefix}.profile.{profile_local_name}"
    shape._add_tag_binding(
        _sketch_topology_identity_binding(
            profile_tag,
            kind=profile_kind,
            local_name=profile_local_name,
            operation=operation,
            sketch=sketch,
            profile_id=str(profile_payload.get("id", "profile")),
            target_topo_id=shape.topo_id,
        )
    )

    if isinstance(shape, Face):
        for wire in shape._iter_wires():
            matches = [
                source
                for source in source_wires
                if source[3].wrapped.IsSame(wire.wrapped)
            ]
            if len(matches) != 1:
                raise ValueError(
                    "Sketch promotion cannot establish exact profile-to-wire correspondence"
                )
            _loop_profile, loop_payload, _loop_role, _source_wire = matches[0]
            loop_local_name = _sketch_topology_tag_local_name(
                loop_payload.get("id", "profile")
            )
            wire._add_tag_binding(
                _sketch_topology_identity_binding(
                    f"{sketch_prefix}.profile.{loop_local_name}",
                    kind="wire",
                    local_name=loop_local_name,
                    operation=operation,
                    sketch=sketch,
                    profile_id=str(loop_payload.get("id", "profile")),
                    target_topo_id=wire.topo_id,
                )
            )

    source_edges = [
        (loop_payload, str(entity_id), source_edge)
        for _loop_profile, loop_payload, _loop_role, source_wire in source_wires
        for entity_id, source_edge in source_wire._get_runtime(
            "sketch.entity_edges", []
        )
    ]
    for edge in shape._iter_edges():
        matches = [source for source in source_edges if source[2].IsSame(edge.wrapped)]
        if len(matches) != 1:
            raise ValueError(
                "Sketch promotion cannot establish exact entity-to-edge correspondence"
            )
        loop_payload, entity_id, _source_edge = matches[0]
        entity_local_name = _sketch_topology_tag_local_name(entity_id)
        edge._add_tag_binding(
            _sketch_topology_identity_binding(
                f"{sketch_prefix}.entity.{entity_local_name}",
                kind="edge",
                local_name=entity_local_name,
                operation=operation,
                sketch=sketch,
                profile_id=str(loop_payload.get("id", "profile")),
                entity_id=entity_id,
                target_topo_id=edge.topo_id,
            )
        )
    return shape

def _promote_sketch_profile(
    sketch: Sketch,
    profile: int | str,
    *,
    target_kind: str,
    inner_profiles: Sequence[int | str] = (),
    require_fully_constrained: bool,
    strict: bool,
    tolerance: float,
    max_iterations: int,
) -> Tuple[
    Union[Wire, Face],
    SketchSolveResult,
    Dict[str, Any],
    List[Tuple[int | str, Dict[str, Any]]],
    List[Tuple[int | str, Dict[str, Any], str, Wire]],
]:
    working = sketch.clone(include_solve=False)
    solve_result = working.solve(
        require_fully_constrained=require_fully_constrained,
        strict=strict,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )
    # A face needs a closed outer loop (and closed inner loops); a wire accepts
    # closed loops and open chains alike — consumers like extrude enforce their
    # own closedness requirements on the promoted wire.
    require_closed = target_kind == "face"
    profile_payload = sketch._profile_payload(
        profile, solve_result=solve_result, require_closed=require_closed
    )
    inner_profile_payloads: List[Tuple[int | str, Dict[str, Any]]] = []
    seen_profile_ids = {str(profile_payload.get("id"))}
    for inner_profile in inner_profiles:
        inner_payload = sketch._profile_payload(
            inner_profile,
            solve_result=solve_result,
            require_closed=require_closed,
        )
        inner_profile_id = str(inner_payload.get("id"))
        if inner_profile_id in seen_profile_ids:
            raise ValueError(
                f"Sketch profile '{inner_profile_id}' was selected more than once"
            )
        seen_profile_ids.add(inner_profile_id)
        inner_profile_payloads.append((inner_profile, inner_payload))
    solve_snapshot = _sketch_solve_snapshot(solve_result)
    with suspend_graph_recording(), use_coordinate_system(WORLD_CS):
        outer_wire = sketch._wire_from_profile_payload(profile_payload)
        source_wires: List[Tuple[int | str, Dict[str, Any], str, Wire]] = [
            (profile, profile_payload, "outer", outer_wire)
        ]
        if target_kind == "wire":
            if inner_profile_payloads:
                raise ValueError("A Wire promotion accepts exactly one sketch profile")
            shape = outer_wire
        elif target_kind == "face":
            inner_wires: List[Wire] = []
            for inner_profile, inner_payload in inner_profile_payloads:
                inner_wire = sketch._wire_from_profile_payload(inner_payload)
                inner_wires.append(inner_wire)
                source_wires.append((inner_profile, inner_payload, "inner", inner_wire))
            expected_normal = np.array(sketch._plane_normal_tuple(), dtype=float)
            expected_normal = expected_normal / np.linalg.norm(expected_normal)

            def aligned_wire(wire: Wire):
                loop_face = Face(make_face_from_wire_ocp(wire.wrapped))
                loop_normal = loop_face.get_normal_at()
                loop_normal_vec = np.array(
                    [loop_normal.x, loop_normal.y, loop_normal.z],
                    dtype=float,
                )
                return (
                    wire.wrapped
                    if np.dot(expected_normal, loop_normal_vec) >= 0.0
                    else TopoDS.Wire_s(wire.wrapped.Reversed())
                )

            raw_face = (
                make_face_from_wires_ocp(
                    aligned_wire(outer_wire),
                    [aligned_wire(wire) for wire in inner_wires],
                )
                if inner_wires
                else make_face_from_wire_ocp(aligned_wire(outer_wire))
            )
            if inner_wires and not BRepCheck_Analyzer(raw_face).IsValid():
                raise ValueError(
                    "Sketch hole profiles must lie strictly inside the outer profile and must not touch or intersect another loop"
                )
            face = Face(raw_face)
            actual_normal = face.get_normal_at()
            if (
                np.dot(
                    expected_normal,
                    np.array(
                        [actual_normal.x, actual_normal.y, actual_normal.z],
                        dtype=float,
                    ),
                )
                < 0.0
            ):
                face = Face(TopoDS.Face_s(raw_face.Reversed()))
            shape = face
        else:
            raise ValueError(
                f"Unsupported sketch promotion target kind '{target_kind}'"
            )
    _apply_sketch_promotion_metadata(
        shape,
        sketch=sketch,
        profile=profile,
        profile_payload=profile_payload,
        inner_profile_payloads=inner_profile_payloads,
        source_wires=source_wires,
        solve_snapshot=solve_snapshot,
    )
    return (
        shape,
        solve_result,
        profile_payload,
        inner_profile_payloads,
        source_wires,
    )

def _assert_sketch_solve_snapshot_matches(
    result: SketchSolveResult,
    snapshot: Dict[str, Any],
    *,
    tolerance: float = 1e-7,
) -> None:
    _assert_sketch_solve_snapshot_dict_matches(
        result.to_dict(), snapshot, tolerance=tolerance
    )

def _assert_sketch_solve_snapshot_dict_matches(
    actual: Dict[str, Any],
    snapshot: Dict[str, Any],
    *,
    tolerance: float = 1e-7,
) -> None:
    if str(actual.get("status")) != str(snapshot.get("status")):
        raise ValueError(
            f"Sketch solve status changed from {snapshot.get('status')!r} to {actual.get('status')!r}"
        )
    if int(actual.get("dof", -1)) != int(snapshot.get("dof", -1)):
        raise ValueError(
            f"Sketch solve DOF changed from {snapshot.get('dof')!r} to {actual.get('dof')!r}"
        )
    if (
        abs(
            float(actual.get("residual_norm", 0.0))
            - float(snapshot.get("residual_norm", 0.0))
        )
        > tolerance
    ):
        raise ValueError("Sketch solve residual changed beyond recorded tolerance")

    actual_points = cast(Dict[str, Any], actual.get("solved_points", {}))
    expected_points = cast(Dict[str, Any], snapshot.get("solved_points", {}))
    if set(actual_points) != set(expected_points):
        raise ValueError("Sketch solve point set changed")
    for point_id, point in actual_points.items():
        expected = expected_points[point_id]
        if (
            math.dist(
                (float(point[0]), float(point[1])),
                (float(expected[0]), float(expected[1])),
            )
            > tolerance
        ):
            raise ValueError(
                f"Sketch solve point '{point_id}' changed beyond recorded tolerance"
            )

    actual_scalars = cast(Dict[str, Any], actual.get("solved_scalars", {}))
    expected_scalars = cast(Dict[str, Any], snapshot.get("solved_scalars", {}))
    if set(actual_scalars) != set(expected_scalars):
        raise ValueError("Sketch solve scalar set changed")
    for scalar_id, value in actual_scalars.items():
        if abs(float(value) - float(expected_scalars[scalar_id])) > tolerance:
            raise ValueError(
                f"Sketch solve scalar '{scalar_id}' changed beyond recorded tolerance"
            )

    actual_entities = cast(Dict[str, Any], actual.get("solved_entities", {}))
    expected_entities = cast(Dict[str, Any], snapshot.get("solved_entities", {}))
    _assert_sketch_solved_entities_match(
        actual_entities,
        expected_entities,
        tolerance=tolerance,
    )

def _assert_sketch_solved_entities_match(
    actual: Dict[str, Any],
    expected: Dict[str, Any],
    *,
    tolerance: float,
) -> None:
    if set(actual) != set(expected):
        raise ValueError("Sketch solve entity set changed")
    for entity_id, entity in actual.items():
        _assert_sketch_solved_value_matches(
            entity,
            expected[entity_id],
            tolerance=tolerance,
            path=f"Sketch solve entity '{entity_id}'",
        )

def _assert_sketch_solved_value_matches(
    actual: Any,
    expected: Any,
    *,
    tolerance: float,
    path: str,
) -> None:
    if isinstance(actual, Mapping) and isinstance(expected, Mapping):
        if set(actual) != set(expected):
            raise ValueError(f"{path} field set changed")
        for key, value in actual.items():
            _assert_sketch_solved_value_matches(
                value,
                expected[key],
                tolerance=tolerance,
                path=f"{path}.{key}",
            )
        return
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            raise ValueError(f"{path} sequence length changed")
        for index, value in enumerate(actual):
            _assert_sketch_solved_value_matches(
                value,
                expected[index],
                tolerance=tolerance,
                path=f"{path}[{index}]",
            )
        return
    if (
        isinstance(actual, (int, float))
        and not isinstance(actual, bool)
        and isinstance(expected, (int, float))
        and not isinstance(expected, bool)
    ):
        if abs(float(actual) - float(expected)) > tolerance:
            raise ValueError(f"{path} changed beyond recorded tolerance")
        return
    if actual != expected:
        raise ValueError(f"{path} changed")

def make_wire_from_sketch_rwire(
    sketch: Sketch,
    profile: int | str = 0,
    *,
    require_fully_constrained: bool = False,
    strict: bool = True,
    tolerance: float = 1e-7,
    max_iterations: int = 80,
) -> Wire:
    """Promote a sketch profile (closed loop or open chain) to a concrete wire, solving internally."""
    try:
        if not isinstance(sketch, Sketch):
            raise ValueError("Input must be a Sketch")
        (
            wire,
            solve_result,
            profile_payload,
            inner_profile_payloads,
            source_wires,
        ) = _promote_sketch_profile(
            sketch,
            profile,
            target_kind="wire",
            require_fully_constrained=require_fully_constrained,
            strict=strict,
            tolerance=tolerance,
            max_iterations=max_iterations,
        )
        solve_snapshot = _sketch_solve_snapshot(solve_result)
        finalized = cast(
            Wire,
            _finalize_derived_shape(
                cast(Wire, wire),
                op=_OP_MAKE_WIRE_FROM_SKETCH_RWIRE,
                params={
                    "profile": profile,
                    "sketch": sketch.to_dict(),
                    "require_fully_constrained": require_fully_constrained,
                    "strict": strict,
                    "tolerance": tolerance,
                    "max_iterations": max_iterations,
                    "solve_snapshot": solve_snapshot,
                    "promotion_map": _sketch_promotion_map(
                        sketch,
                        profile,
                        profile_payload,
                        inner_profile_payloads=inner_profile_payloads,
                        target_kind="wire",
                    ),
                },
                input_shapes=cast(Sequence[AnyShape], [sketch]),
                tags={"derived", "wire", "sketch"},
            ),
        )
        return cast(
            Wire,
            _apply_sketch_promotion_identity_tags(
                finalized,
                sketch=sketch,
                profile_payload=profile_payload,
                source_wires=source_wires,
                operation=_OP_MAKE_WIRE_FROM_SKETCH_RWIRE,
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_wire_from_sketch_rwire",
            what_happened="Failed to create a wire from the sketch.",
            possible_causes=[
                "The sketch has no promotable component: every non-construction "
                "edge set must be a closed loop, an open chain, or a circle.",
                "An edge set branches at a point carrying more than two edges.",
                "The sketch constraints are conflicting or invalid.",
                "The requested profile index or id does not exist.",
            ],
            how_to_fix=[
                "Build sketch paths only through sketch APIs; connect entities by "
                "sharing point ids and avoid branch points with three or more edges.",
                "Closedness is not required here — extrude and face consumers "
                "enforce it on the resulting wire.",
                "Call inspect_sketch_rsketchresult(..., strict=False) to inspect diagnostics.",
            ],
            error=e,
        )

def make_face_from_sketch_rface(
    sketch: Sketch,
    profile: int | str = 0,
    *,
    inner_profiles: Sequence[int | str] = (),
    require_fully_constrained: bool = False,
    strict: bool = True,
    tolerance: float = 1e-7,
    max_iterations: int = 80,
) -> Face:
    """Promote one outer and optional inner sketch profiles to a face."""
    try:
        if not isinstance(sketch, Sketch):
            raise ValueError("Input must be a Sketch")
        normalized_inner_profiles = tuple(inner_profiles)
        (
            face,
            solve_result,
            profile_payload,
            inner_profile_payloads,
            source_wires,
        ) = _promote_sketch_profile(
            sketch,
            profile,
            target_kind="face",
            inner_profiles=normalized_inner_profiles,
            require_fully_constrained=require_fully_constrained,
            strict=strict,
            tolerance=tolerance,
            max_iterations=max_iterations,
        )
        solve_snapshot = _sketch_solve_snapshot(solve_result)
        finalized = cast(
            Face,
            _finalize_derived_shape(
                cast(Face, face),
                op=_OP_MAKE_FACE_FROM_SKETCH_RFACE,
                params={
                    "profile": profile,
                    "inner_profiles": normalized_inner_profiles,
                    "sketch": sketch.to_dict(),
                    "require_fully_constrained": require_fully_constrained,
                    "strict": strict,
                    "tolerance": tolerance,
                    "max_iterations": max_iterations,
                    "solve_snapshot": solve_snapshot,
                    "promotion_map": _sketch_promotion_map(
                        sketch,
                        profile,
                        profile_payload,
                        inner_profile_payloads=inner_profile_payloads,
                        target_kind="face",
                    ),
                },
                input_shapes=cast(Sequence[AnyShape], [sketch]),
                tags={"derived", "face", "sketch"},
            ),
        )
        return cast(
            Face,
            _apply_sketch_promotion_identity_tags(
                finalized,
                sketch=sketch,
                profile_payload=profile_payload,
                source_wires=source_wires,
                operation=_OP_MAKE_FACE_FROM_SKETCH_RFACE,
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_face_from_sketch_rface",
            what_happened="Failed to create a face from the sketch.",
            possible_causes=[
                "The sketch has no closed profile; faces require closed loops "
                "(open chains are wire-only — promote them with "
                "make_wire_from_sketch_rwire instead).",
                "The sketch constraints are conflicting or invalid.",
                "The requested profile index or id does not exist.",
                "An inner profile is outside, intersects, or duplicates the outer profile.",
            ],
            how_to_fix=[
                "Build closed profiles with add_line_rsketch(...) or add_circle_rsketch(...).",
                "Add constraints until the profile can solve cleanly.",
                "Pass hole loops explicitly with inner_profiles=[...].",
            ],
            error=e,
        )

__all__ = tuple(name for name in globals() if not name.startswith("__"))

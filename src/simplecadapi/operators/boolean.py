"""Boolean operator implementations."""

from __future__ import annotations

from ._diagnostics import (
    _solid_copy,
    BooleanDiagnosis,
    diagnose_boolean_failure,
    render_failure_evidence,
)
from ._support import *


def _wrap_boolean_failure(
    *,
    operation: str,
    default_what_happened: str,
    default_possible_causes: Sequence[str],
    default_how_to_fix: Sequence[str],
    error: BaseException,
    operands: Optional[List[Solid]],
    effective_tol: Optional[float] = None,
    diagnosis_hint: bool = True,
) -> NoReturn:
    """Wrap a boolean failure with failure-time geometry diagnosis when available."""

    diagnosis: Optional[BooleanDiagnosis] = None
    if diagnosis_hint:
        operation_kind = operation.removeprefix("make_2d_").removesuffix("_rsolid").removesuffix("_rface")
        diagnosis = diagnose_boolean_failure(
            operands,
            effective_tol=effective_tol,
            operation_kind=operation_kind,
        )
    evidence: Tuple[ErrorEvidence, ...] = ()
    if diagnosis is not None and diagnosis.evidence_shapes:
        dedup_key: Optional[Tuple] = (operation, diagnosis.failure_kind)
        if diagnosis.failure_kind == "disjoint" and diagnosis.measurements:
            # Re-render when the geometry actually moved (new gap), skip when
            # the agent retries the same unmoved failure.
            dedup_key = (
                operation,
                diagnosis.failure_kind,
                round(float(diagnosis.measurements[0].value), 1),
            )
        # Color the two operands differently (tagged wrapper copies; the
        # user's own objects are never tagged).
        render_shapes: List[Any] = []
        highlight_tags: List[str] = []
        tag_labels: Dict[str, str] = {}
        for index, shape in enumerate(diagnosis.evidence_shapes[:2]):
            tag = f"diagnostic.operand_{index + 1}"
            copy = _solid_copy(shape)
            if copy is not None:
                copy._apply_tag(tag, propagate=False)
                render_shapes.append(copy)
                highlight_tags.append(tag)
                tag_labels[tag] = f"operand {index + 1}"
            else:
                render_shapes.append(shape)
        # No leader-line callouts here: solid-tag anchors sit inside the
        # solids and occlusion re-anchoring can land on the face nearest the
        # OTHER operand, making the label appear to point at the wrong body.
        # The legend colors + caption carry the mapping.
        rendered = render_failure_evidence(
            render_shapes,
            operation=operation,
            caption=diagnosis.evidence_caption,
            dedup_key=dedup_key,
            highlight_tags=highlight_tags,
            tag_labels=tag_labels,
            callouts=False,
        )
        if rendered is not None:
            evidence = (rendered,)
    _wrap_public_api_error(
        operation=operation,
        what_happened=(diagnosis.what_happened or default_what_happened) if diagnosis else default_what_happened,
        possible_causes=(
            diagnosis.possible_causes if diagnosis and diagnosis.possible_causes else default_possible_causes
        ),
        how_to_fix=default_how_to_fix,
        error=error,
        measurements=diagnosis.measurements if diagnosis else (),
        evidence=evidence,
        repair=diagnosis.repair if diagnosis else (),
    )

def union_rsolid(
    *solids: Union[Solid, Sequence[Solid]],
    clean: bool = True,
    glue: bool = _DEFAULT_UNION_GLUE,
    tol: Optional[float] = None,
    tracking_policy: TrackingPolicy | str = TrackingPolicy.FULL,
) -> Solid:
    """Compute the boolean union and return one manifold solid.

    Face-area contact and positive-volume overlap can produce one solid without
    artificial embedding. Edge-only, vertex-only, and point/curve tangencies
    are non-manifold connections and cannot satisfy the one-Solid contract.

    ``glue`` is an OCC optimization for compatible touching or coincident
    topology, not a geometry repair switch. If the optimized pass does not
    return one solid, SimpleCAD automatically retries the normal fuse algorithm.

    Args:
        solids: One or more Solid objects or sequences of Solid. Nested sequences are
            flattened before processing.
        clean: Unify same-domain faces and remove splitter edges when possible.
        glue: Try OCC glue optimization first, then fall back to normal fuse if
            necessary. Defaults to False.
        tol: Optional finite non-negative fuzzy-boolean tolerance used by OCC. It
            may intentionally bridge a small gap but cannot make a non-manifold
            point or edge contact into a valid solid.
        tracking_policy: FULL computes topology history and lineage. GRAPH keeps
            the replayable operation node without computing a TopoDelta.

    Returns:
        Solid: The merged union result.

    Usage:
        Accepts standalone `Solid` objects, lists of `Solid`, and nested sequences,
        but always returns exactly one `Solid`. If the kernel cannot produce
        exactly one solid result, the API raises a clear error instead of
        returning multiple pieces.

    Examples:
        body = make_box_rsolid(10, 4, 4, bottom_face_center=(0, 0, 0))
        rib = make_box_rsolid(2, 4, 4, bottom_face_center=(4, 0, 0))
        merged = union_rsolid(body, rib)
        print(merged.get_volume())
    """

    remaining: List[Solid] = []
    effective_tol: Optional[float] = None
    try:
        policy = (
            TrackingPolicy.GRAPH
            if current_tracking_policy() == TrackingPolicy.GRAPH
            else TrackingPolicy(tracking_policy)
        )
        remaining = _flatten_boolean_solids(solids, "union_rsolid")

        if not remaining:
            raise ValueError("union_rsolid 至少需要一个Solid输入")

        for solid in remaining:
            if solid.wrapped.IsNull():
                raise ValueError("输入实体无效，无法进行并集运算。")

        if len(remaining) == 1 and not clean:
            return remaining[0]

        effective_tol = _resolve_union_tol(remaining, tol)
        tracked_union_result: Optional[TrackedBooleanResult] = None
        if policy == TrackingPolicy.FULL and len(remaining) >= 2:
            tracked_union_result = _evaluate_tracked_union(
                    remaining,
                    glue=glue,
                    tol=effective_tol,
                    clean=clean,
                )
            if tracked_union_result.solid is None:
                raise ValueError("union did not produce a valid solid")
            fused_solid = tracked_union_result.solid
        else:
            fused_solid = _require_union_solid(
                fuse_shapes(
                    [solid.wrapped for solid in remaining],
                    glue=glue,
                    tol=effective_tol,
                    clean=clean,
                ),
                effective_tol,
            )

        all_metadata = {}
        for solid in remaining:
            all_metadata.update(solid._metadata)

        fused_solid._metadata = all_metadata.copy()

        params: Dict[str, object] = {
            "input_count": len(remaining),
            "clean": clean,
            "glue": glue,
            "tol": effective_tol,
            "tracking_policy": policy.value,
        }
        if tracked_union_result is not None:
            fused_solid = _finalize_tracked_solid(
                fused_solid,
                op=_OP_MAKE_UNION_RSOLID,
                params=params,
                source_solids=remaining,
                delta=tracked_union_result.delta,
                delta_entries=cast(
                    Dict[str, Dict[str, object]],
                    tracked_union_result.delta_entries,
                ),
                input_shapes=remaining,
            )
        elif policy == TrackingPolicy.GRAPH:
            fused_solid = cast(
                Solid,
                _finalize_derived_shape(
                    fused_solid,
                    op=_OP_MAKE_UNION_RSOLID,
                    params=params,
                    input_shapes=remaining,
                ),
            )
        else:
            _attach_track_summary(fused_solid, op=_OP_MAKE_UNION_RSOLID)
            record_operation_if_active(
                op=_OP_MAKE_UNION_RSOLID,
                params=params,
                outputs=fused_solid,
                input_shapes=remaining,
                context=_current_context_metadata(),
            )

        return fused_solid
    except Exception as e:
        _wrap_boolean_failure(
            operation="union_rsolid",
            default_what_happened=(
                str(e)
                if isinstance(e, ValueError) and str(e).startswith("union produced ")
                else "Failed to compute the boolean union."
            ),
            default_possible_causes=[
                "One or more inputs are not Solid objects.",
                "At least one input solid is null or invalid.",
                "The inputs are separated beyond tol, so the kernel cannot produce exactly one solid.",
                "The inputs meet only along an edge, vertex, tangent point, or tangent curve, so their union is not one manifold solid.",
            ],
            default_how_to_fix=[
                "Pass only valid Solid objects or sequences of Solid objects.",
                "For intended face contact, make the solids share a finite-area face and retry; no artificial overlap is required.",
                "For a real small gap, pass an explicit tol only when approximating that gap is acceptable.",
                "Do not expect glue or tol to turn point-, edge-, or tangent-only contact into a valid single solid.",
            ],
            error=e,
            operands=remaining,
            effective_tol=effective_tol,
        )

def cut_rsolid(
    *solids: Union[Solid, Sequence[Solid]],
    skip_non_intersecting: bool = True,
    tracking_policy: TrackingPolicy | str = TrackingPolicy.FULL,
) -> Solid:
    """Compute the boolean difference of solids.

    Args:
        solids: One or more Solid objects or sequences of Solid. Nested sequences are
            flattened before processing; the first solid is the base, the rest are
            subtracted in order.
        skip_non_intersecting: When True, tools with no meaningful intersection are
            ignored for interactive convenience. Graph replay records this flag and
            should use False for strict diagnostic workflows.
        tracking_policy: FULL computes topology history and lineage. GRAPH keeps
            the replayable operation node without computing a TopoDelta.

    Returns:
        Solid: The cut result solid.

    Usage:
        Accepts a base solid followed by one or more tool solids, including nested
        sequences, and returns a single `Solid`.
    """
    remaining: List[Solid] = []
    try:
        policy = (
            TrackingPolicy.GRAPH
            if current_tracking_policy() == TrackingPolicy.GRAPH
            else TrackingPolicy(tracking_policy)
        )
        remaining = _flatten_boolean_solids(solids, "cut_rsolid")

        if not remaining:
            raise ValueError("cut_rsolid 至少需要一个Solid输入")

        if len(remaining) == 1:
            return remaining[0]

        # 从第一个实体开始，依次减去其他实体
        result_solid = remaining[0]
        deltas: List[TopoDelta] = []
        merged_delta_entries: Dict[str, Dict[str, object]] = {}
        # Step deltas name faces by kernel hashes, which come from the shapes'
        # addresses. Every intermediate result stays alive until the merged
        # delta is recorded: a freed face's address could otherwise be reused
        # by an output face, and a stale entry would resolve to that face.
        intermediates: List[Solid] = []
        cut_performed = False

        for i in range(1, len(remaining)):
            candidate = remaining[i]

            s1 = result_solid.wrapped
            s2 = candidate.wrapped

            if s1.IsNull() or s2.IsNull():
                raise ValueError("输入实体无效，无法进行差集运算。")

            # 检查是否有交集
            intersection = common_shapes([s1, s2])
            intersection_solids = solids_of(intersection)
            if not intersection_solids:
                if skip_non_intersecting:
                    continue
                raise ValueError("差集工具实体与当前实体没有交集。")
            intersection_obj = Solid(intersection_solids[0])

            if intersection_obj.get_volume() < 1e-12:
                # 没有有效的交集，跳过此次切割
                if skip_non_intersecting:
                    continue
                raise ValueError("差集工具实体与当前实体交集体积过小。")

            tracked = (
                tracked_cut(result_solid, candidate)
                if policy == TrackingPolicy.FULL and len(remaining) == 2
                else (
                    tracked_cut(result_solid, candidate)
                    if policy == TrackingPolicy.FULL
                    else None
                )
            )
            if tracked is not None:
                if tracked.solid is None:
                    raise ValueError("差集运算失败: OCC 未返回有效实体")
                new_result = tracked.solid
            else:
                new_result = _require_single_boolean_solid(
                    solids_of(cut_shapes(s1, [s2])),
                    operation="cut_rsolid",
                    failure_reason="差集运算失败: OCC 未返回有效实体",
                )
            new_result._metadata = result_solid._metadata.copy()
            intermediates.append(result_solid)
            result_solid = new_result
            if tracked is not None:
                deltas.append(tracked.delta)
                merged_delta_entries.update(
                    cast(Dict[str, Dict[str, object]], tracked.delta_entries)
                )
            cut_performed = True

        result_solid._metadata = remaining[0]._metadata.copy()
        result_solid._apply_tag("solid.boolean.cut", propagate=False)

        merged_delta = _merge_topo_deltas(deltas)
        params: Dict[str, object] = {
            "tool_count": len(remaining) - 1,
            "skip_non_intersecting": bool(skip_non_intersecting),
            "tracking_policy": policy.value,
        }
        if cut_performed and merged_delta is not None:
            result_solid = _finalize_tracked_solid(
                result_solid,
                op=_OP_MAKE_CUT_RSOLID,
                params=params,
                source_solids=remaining,
                delta=merged_delta,
                delta_entries=merged_delta_entries or None,
                input_shapes=remaining,
            )
        elif policy == TrackingPolicy.GRAPH:
            result_solid = cast(
                Solid,
                _finalize_derived_shape(
                    result_solid,
                    op=_OP_MAKE_CUT_RSOLID,
                    params=params,
                    input_shapes=remaining,
                ),
            )
        else:
            _attach_track_summary(result_solid, op=_OP_MAKE_CUT_RSOLID)
            record_operation_if_active(
                op=_OP_MAKE_CUT_RSOLID,
                params=params,
                outputs=result_solid,
                input_shapes=remaining,
                context=_current_context_metadata(),
            )

        return result_solid
    except Exception as e:
        no_intersection_failure = (
            isinstance(e, ValueError) and "没有交集" in str(e)
        ) or (isinstance(e, ValueError) and "交集体积过小" in str(e))
        _wrap_boolean_failure(
            operation="cut_rsolid",
            default_what_happened="Failed to compute the boolean cut.",
            default_possible_causes=[
                "One or more inputs are not Solid objects.",
                "The base solid or tool solids are invalid.",
                "The kernel could not compute a valid cut result for the current geometry.",
            ],
            default_how_to_fix=[
                "Pass a valid base solid followed by valid tool solids.",
                "Check whether the tool geometry actually intersects the base solid.",
                "If the cut depends on earlier union results, verify those results first.",
            ],
            error=e,
            operands=remaining,
            diagnosis_hint=no_intersection_failure,
        )

def intersect_rsolid(*solids: Union[Solid, Sequence[Solid]]) -> Solid:
    """Compute the boolean intersection of solids.

    Args:
        solids: One or more Solid objects or sequences of Solid. Nested sequences are
            flattened before processing.

    Returns:
        Solid: The overlap region as a single solid.

    Usage:
        Accepts one or more solids, including nested sequences, and returns a single
        `Solid`. If the inputs do not overlap meaningfully, the API raises a clear
        error instead of returning an empty list.
    """
    remaining: List[Solid] = []
    try:
        remaining = _flatten_boolean_solids(solids, "intersect_rsolid")

        if not remaining:
            raise ValueError("intersect_rsolid 至少需要一个Solid输入")

        if len(remaining) == 1:
            return remaining[0]

        # 从第一个实体开始，依次与后续实体进行交集运算
        result_solid = remaining[0]
        deltas: List[TopoDelta] = []
        merged_delta_entries: Dict[str, Dict[str, object]] = {}
        # Step deltas name faces by kernel hashes, which come from the shapes'
        # addresses. Every intermediate result stays alive until the merged
        # delta is recorded: a freed face's address could otherwise be reused
        # by an output face, and a stale entry would resolve to that face.
        intermediates: List[Solid] = []
        intersect_performed = False

        for i in range(1, len(remaining)):
            candidate = remaining[i]

            s1 = result_solid.wrapped
            s2 = candidate.wrapped

            if s1.IsNull() or s2.IsNull():
                raise ValueError("输入实体无效，无法进行交集运算。")

            tracked = (
                tracked_intersect(result_solid, candidate)
                if len(remaining) == 2
                else tracked_intersect(result_solid, candidate)
            )
            if tracked.solid is None:
                raise ValueError("交集结果为空或 OCC 未返回有效实体")

            intermediates.append(result_solid)
            result_solid = tracked.solid
            deltas.append(tracked.delta)
            merged_delta_entries.update(
                cast(Dict[str, Dict[str, object]], tracked.delta_entries)
            )
            intersect_performed = True

            # 检查交集是否为空
            if result_solid.get_volume() < 1e-12:
                raise ValueError("交集结果为空或体积过小")

        all_metadata: dict = {}
        for solid in remaining:
            all_metadata.update(solid._metadata)

        result_solid._metadata = all_metadata
        result_solid._apply_tag("solid.boolean.intersect", propagate=False)

        merged_delta = _merge_topo_deltas(deltas)
        if intersect_performed and merged_delta is not None:
            result_solid = _finalize_tracked_solid(
                result_solid,
                op=_OP_MAKE_INTERSECT_RSOLID,
                params={"input_count": len(remaining)},
                source_solids=remaining,
                delta=merged_delta,
                delta_entries=merged_delta_entries or None,
                input_shapes=remaining,
            )
        else:
            _attach_track_summary(result_solid, op=_OP_MAKE_INTERSECT_RSOLID)
            record_operation_if_active(
                op=_OP_MAKE_INTERSECT_RSOLID,
                params={"input_count": len(remaining)},
                outputs=result_solid,
                input_shapes=remaining,
                context=_current_context_metadata(),
            )

        return result_solid
    except Exception as e:
        empty_result_failure = isinstance(e, ValueError) and "交集结果" in str(e)
        _wrap_boolean_failure(
            operation="intersect_rsolid",
            default_what_happened="Failed to compute the boolean intersection.",
            default_possible_causes=[
                "One or more inputs are not Solid objects.",
                "At least one input solid is invalid.",
                "The solids do not overlap enough to produce a non-empty single solid.",
                "The kernel could not compute a stable overlap region.",
            ],
            default_how_to_fix=[
                "Pass only valid Solid objects.",
                "Verify that the solids truly overlap in space.",
                "Move the solids so they share a meaningful overlap volume before intersecting.",
            ],
            error=e,
            operands=remaining,
            diagnosis_hint=empty_result_failure,
        )

def _extract_single_face(shape_ocp, operation: str) -> Face:
    """Extract exactly one Face from an OCP shape result."""
    result_faces = faces_of_ocp(shape_ocp)
    if len(result_faces) != 1:
        raise ValueError(
            f"{operation} expected exactly 1 face in the result, got {len(result_faces)}"
        )
    return Face(result_faces[0])

def make_2d_cut_rface(body: Face, tool: Face) -> Face:
    """Subtract one 2D face from another (2D boolean difference).

    Parameters
    ----------
    body : Face
        The face to subtract from.
    tool : Face
        The face to subtract (the cutter).

    Returns
    -------
    Face
        The resulting face after subtraction.  The result may contain
        inner wires (holes) if the tool was fully inside the body.
    """
    try:
        if not isinstance(body, Face):
            raise ValueError("body must be a Face")
        if not isinstance(tool, Face):
            raise ValueError("tool must be a Face")

        result_shape = cut_shapes(body.wrapped, [tool.wrapped])
        result_face = _extract_single_face(result_shape, "make_2d_cut_rface")

        result_face._metadata = body._metadata.copy()

        return cast(
            Face,
            _finalize_derived_shape(
                result_face,
                op=_OP_MAKE_CUT_RFACE,
                params={},
                input_shapes=[body, tool],
                tags={"derived", "face"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_2d_cut_rface",
            what_happened="Failed to subtract one face from another.",
            possible_causes=[
                "The body or tool is not a Face.",
                "The faces do not overlap or are not coplanar.",
                "The kernel could not compute a stable 2D difference.",
            ],
            how_to_fix=[
                "Pass two valid Face objects.",
                "Ensure both faces lie on the same plane.",
                "Verify the tool face overlaps the body face.",
            ],
            error=e,
        )

def make_2d_union_rface(face_a: Face, face_b: Face) -> Face:
    """Compute the boolean union of two 2D faces.

    Parameters
    ----------
    face_a : Face
        First face.
    face_b : Face
        Second face.

    Returns
    -------
    Face
        The merged face.  Both inputs must overlap or touch so that the
        result is a single connected face.
    """
    try:
        if not isinstance(face_a, Face):
            raise ValueError("face_a must be a Face")
        if not isinstance(face_b, Face):
            raise ValueError("face_b must be a Face")

        result_shape = fuse_shapes([face_a.wrapped, face_b.wrapped], clean=True)
        result_face = _extract_single_face(result_shape, "make_2d_union_rface")

        result_face._metadata = {**face_a._metadata, **face_b._metadata}

        return cast(
            Face,
            _finalize_derived_shape(
                result_face,
                op=_OP_MAKE_UNION_RFACE,
                params={},
                input_shapes=[face_a, face_b],
                tags={"derived", "face"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_2d_union_rface",
            what_happened="Failed to union two faces.",
            possible_causes=[
                "One or both inputs are not Face objects.",
                "The faces do not overlap or touch.",
                "The faces are not coplanar.",
            ],
            how_to_fix=[
                "Pass two valid Face objects.",
                "Ensure the faces overlap or share a boundary.",
                "Ensure both faces lie on the same plane.",
            ],
            error=e,
        )

def make_2d_intersect_rface(face_a: Face, face_b: Face) -> Face:
    """Compute the boolean intersection of two 2D faces.

    Parameters
    ----------
    face_a : Face
        First face.
    face_b : Face
        Second face.

    Returns
    -------
    Face
        The overlapping region of the two faces.
    """
    try:
        if not isinstance(face_a, Face):
            raise ValueError("face_a must be a Face")
        if not isinstance(face_b, Face):
            raise ValueError("face_b must be a Face")

        result_shape = common_shapes([face_a.wrapped, face_b.wrapped])
        result_face = _extract_single_face(result_shape, "make_2d_intersect_rface")

        result_face._metadata = {**face_a._metadata, **face_b._metadata}

        return cast(
            Face,
            _finalize_derived_shape(
                result_face,
                op=_OP_MAKE_INTERSECT_RFACE,
                params={},
                input_shapes=[face_a, face_b],
                tags={"derived", "face"},
            ),
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="make_2d_intersect_rface",
            what_happened="Failed to intersect two faces.",
            possible_causes=[
                "One or both inputs are not Face objects.",
                "The faces do not overlap.",
                "The faces are not coplanar.",
            ],
            how_to_fix=[
                "Pass two valid Face objects.",
                "Ensure the faces have a non-empty overlap region.",
                "Ensure both faces lie on the same plane.",
            ],
            error=e,
        )

__all__ = tuple(name for name in globals() if not name.startswith("__"))

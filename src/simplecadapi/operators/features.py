"""Features operator implementations."""

from __future__ import annotations

from ._diagnostics import (
    BlendDiagnosis,
    BlendVolumeViolation,
    assert_blend_volume_monotonic,
    diagnose_blend_failure,
    raise_loft_failure_if_diagnosed,
    raise_open_wire_failure,
    render_failure_evidence,
)
from ..kernel.ocp_properties import center_of_mass, distance, volume
from ..kernel.ocp_topology import faces_of
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Splitter
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle, BRepOffsetAPI_MakeOffset, BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_MakeThickSolid, BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace, BRepPrimAPI_MakePrism
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Intersection, GeomAbs_Plane
from OCP.LocOpe import LocOpe_DPrism
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_FACE, TopAbs_SHELL, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopTools import TopTools_ListOfShape
from OCP.TopoDS import TopoDS_Iterator
from OCP.gp import gp_Pln, gp_Trsf, gp_Vec
from ._support import *
from .geometry import (
    _default_plane_x_direction,
    _validated_loft_sections,
    make_face_from_wire_rface,
    make_helix_rwire,
)

from OCP.TopoDS import TopoDS_Shape

def _blend_single_edge_ok(
    solid: Solid,
    edge: Edge,
    size_value: float,
    *,
    operation_kind: str,
    distance2: Optional[float] = None,
) -> bool:
    """Diagnostic rerun: does the blend succeed on this one edge alone?"""

    try:
        if operation_kind == "chamfer":
            tracked = tracked_chamfer(solid, [edge], size_value, distance2=distance2)
        else:
            tracked = tracked_fillet(solid, [edge], size_value)
        return tracked.shape is not None
    except Exception:
        return False


def _wrap_blend_failure(
    *,
    operation: str,
    operation_kind: str,
    solid: Optional[Solid],
    edges: List[Edge],
    size_value: Optional[float],
    error: BaseException,
    retry_single: Optional[Any] = None,
    default_what_happened: str,
    default_possible_causes: Sequence[str],
    default_how_to_fix: Sequence[str],
) -> NoReturn:
    """Wrap a fillet/chamfer failure with failure-time geometry diagnosis."""

    # Mechanism-E headline: when the exit check caught impossible output,
    # its measured volumes lead what_happened (the agent must distinguish
    # "kernel refused" from "kernel silently lied"); probe explanations
    # follow as the suspected root cause.
    volume_headline = str(error) if isinstance(error, BlendVolumeViolation) else None
    diagnosis: Optional[BlendDiagnosis] = None
    if solid is not None and edges and size_value is not None:
        diagnosis = diagnose_blend_failure(
            solid,
            edges,
            size_value=size_value,
            operation_kind=operation_kind,
            retry_single=retry_single,
        )
    evidence: Tuple[ErrorEvidence, ...] = ()
    if diagnosis is not None and diagnosis.evidence_shapes:
        dedup_key: Tuple = (operation, diagnosis.failure_kind)
        if size_value is not None:
            dedup_key = (operation, diagnosis.failure_kind, round(size_value, 1))
        rendered = render_failure_evidence(
            diagnosis.evidence_shapes,
            operation=operation,
            caption=diagnosis.evidence_caption,
            dedup_key=dedup_key,
            highlight_edges=diagnosis.evidence_edges,
        )
        if rendered is not None:
            evidence = (rendered,)
    what_happened = (
        (diagnosis.what_happened or default_what_happened) if diagnosis
        else default_what_happened
    )
    if volume_headline:
        what_happened = (
            f"{volume_headline}; probes indicate: {what_happened}"
            if diagnosis and diagnosis.what_happened else volume_headline
        )
    _wrap_public_api_error(
        operation=operation,
        what_happened=what_happened,
        possible_causes=(
            diagnosis.possible_causes
            if diagnosis and diagnosis.possible_causes
            else default_possible_causes
        ),
        how_to_fix=default_how_to_fix,
        error=error,
        measurements=diagnosis.measurements if diagnosis else (),
        evidence=evidence,
        repair=diagnosis.repair if diagnosis else (),
    )

def extrude_rsolid(
    profile: Union[Wire, Face],
    direction: Tuple[float, float, float],
    distance: ScalarLike,
    *,
    tag_prefix: Optional[str] = None,
    result_tag: Optional[str] = None,
    start_face_tag: Optional[str] = None,
    end_face_tag: Optional[str] = None,
    side_faces_tag: Optional[str] = None,
) -> Solid:
    """Create a solid by extruding a profile, with optional role-based tags."""
    try:
        assignments = _normalize_operation_role_tags(
            _OP_MAKE_EXTRUDE_RSOLID,
            (
                ("extrusion.start", start_face_tag),
                ("extrusion.end", end_face_tag),
                ("extrusion.side", side_faces_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        distance_value = evaluate_scalar(distance)
        if distance_value <= 0:
            raise ValueError("拉伸距离必须大于0")

        cs = get_current_cs()
        direction_value = cast(Tuple[float, float, float], evaluate_value(direction))
        global_direction = cs.transform_vector(np.array(direction_value))

        direction_norm = float(np.linalg.norm(global_direction))
        if direction_norm <= 1e-15:
            raise ValueError("拉伸方向不能是零向量")
        direction_vec = tuple(
            (global_direction / direction_norm * distance_value).tolist()
        )

        if isinstance(profile, Wire):
            # 如果是线，先转换为面；缺口诊断（端点对+距离+证据图）随结构化错误给出
            if profile.is_closed():
                face = Face(make_face_from_wire_ocp(profile.wrapped))
            else:
                raise_open_wire_failure(
                    "extrude_rsolid", profile,
                    purpose="extrude it into a solid",
                )
        elif isinstance(profile, Face):
            face = profile
        else:
            raise ValueError("只能拉伸线或面")  # type: ignore[unreachable]

        resolved_direction = tuple(float(value) for value in global_direction)
        tracked = tracked_extrude(
                face,
                resolved_direction,
                distance_value,
            )
        solid = cast(Solid, tracked.shape)

        solid._apply_tag("solid.extrusion", propagate=False)
        solid._metadata = profile._metadata.copy()

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            solid,
            op=_OP_MAKE_EXTRUDE_RSOLID,
            params={
                "direction": direction,
                "distance": distance,
            },
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
            input_shapes=[profile],
        )
        tagged = _apply_operation_role_tags(
            finalized,
            op=_OP_MAKE_EXTRUDE_RSOLID,
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
        return _apply_feature_tag_prefix(
            tagged,
            tag_prefix=tag_prefix,
            op=_OP_MAKE_EXTRUDE_RSOLID,
            delta=tracked.delta,
            start_role="extrusion.start",
            end_role="extrusion.end",
            side_role="extrusion.side",
            source_shapes=[profile],
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="extrude_rsolid",
            what_happened="Failed to extrude the profile into a solid.",
            possible_causes=[
                "The distance is not a positive finite scalar.",
                "The direction vector is invalid.",
                "A wire profile was provided but it is not closed.",
                "The kernel rejected the profile or the extrusion direction.",
            ],
            how_to_fix=[
                "Use a distance greater than zero.",
                "Pass a valid finite direction vector.",
                "If you extrude a wire, make sure the wire is closed or convert it to a face first.",
                "Inspect the evaluated profile and direction before retrying.",
            ],
            error=e,
        )

def revolve_rsolid(
    profile: Union[Wire, Face],
    axis: Tuple[float, float, float] = (0, 0, 1),
    angle: ScalarLike = 360,
    origin: Tuple[float, float, float] = (0, 0, 0),
    *,
    tag_prefix: Optional[str] = None,
    result_tag: Optional[str] = None,
    start_face_tag: Optional[str] = None,
    end_face_tag: Optional[str] = None,
    side_faces_tag: Optional[str] = None,
) -> Solid:
    """Create a revolved solid, with optional kernel-role-based tags."""
    try:
        assignments = _normalize_operation_role_tags(
            _OP_MAKE_REVOLVE_RSOLID,
            (
                ("revolution.start", start_face_tag),
                ("revolution.end", end_face_tag),
                ("revolution.side", side_faces_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        angle_value = evaluate_scalar(angle)
        if angle_value <= 0:
            raise ValueError("旋转角度必须大于0")

        cs = get_current_cs()
        axis_value = cast(Tuple[float, float, float], evaluate_value(axis))
        origin_value = cast(Tuple[float, float, float], evaluate_value(origin))
        global_axis = cs.transform_vector(np.array(axis_value))
        global_origin = cs.transform_point(np.array(origin_value))

        # 获取轮廓对应的面
        if isinstance(profile, Wire):
            # 如果是线，先转换为面
            if profile.is_closed():
                face = Face(make_face_from_wire_ocp(profile.wrapped))
            else:
                raise ValueError("旋转的线必须是闭合的")
        elif isinstance(profile, Face):
            face = profile
        else:
            raise ValueError("只能旋转线或面")

        resolved_axis = tuple(float(value) for value in global_axis)
        resolved_origin = tuple(float(value) for value in global_origin)
        tracked = tracked_revolve(
                face,
                resolved_axis,
                resolved_origin,
                angle_value,
            )
        solid = cast(Solid, tracked.shape)

        solid._metadata = profile._metadata.copy()

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            solid,
            op=_OP_MAKE_REVOLVE_RSOLID,
            params={
                "axis": axis,
                "angle": angle,
                "origin": origin,
            },
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
            input_shapes=[profile],
        )
        tagged = _apply_operation_role_tags(
            finalized,
            op=_OP_MAKE_REVOLVE_RSOLID,
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
        return _apply_feature_tag_prefix(
            tagged,
            tag_prefix=tag_prefix,
            op=_OP_MAKE_REVOLVE_RSOLID,
            delta=tracked.delta,
            start_role="revolution.start" if angle_value < 360.0 else None,
            end_role="revolution.end" if angle_value < 360.0 else None,
            side_role="revolution.side",
            source_shapes=[profile],
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="revolve_rsolid",
            what_happened="Failed to revolve the profile into a solid.",
            possible_causes=[
                "The angle is not a positive finite scalar.",
                "The axis or origin is invalid.",
                "A wire profile was provided but it is not closed.",
                "The kernel rejected the revolve definition.",
            ],
            how_to_fix=[
                "Use an angle greater than zero.",
                "Pass a valid non-zero axis vector and a valid origin point.",
                "If you revolve a wire, ensure it is closed or convert it to a face first.",
                "Inspect the evaluated axis, origin, and profile before retrying.",
            ],
            error=e,
        )

def _normalize_shape_input(
    shapes: Union[AnyShape, Sequence[AnyShape]],
) -> List[AnyShape]:
    """Normalize rendering input into a flat list of shapes."""

    if isinstance(shapes, (_EXPORTABLE_TYPES, TopoDS_Shape)):
        return [shapes]

    if isinstance(shapes, Sequence) and not isinstance(shapes, (str, bytes)):
        normalized: List[AnyShape] = []
        for item in shapes:
            normalized.extend(_normalize_shape_input(item))
        return normalized

    raise ValueError(
        "rendering accepts Compound, Solid, Shell, Face, Wire, Edge, Vertex, "
        "raw TopoDS_Shape, or nested sequences of those types"
    )

def _screenshot_views() -> Tuple[Tuple[float, float, str], ...]:
    """Default multi-view set used by render_screenshot_rpath (engine-owned)."""
    from ..inspect.brep.render import SCREENSHOT_VIEWS

    return SCREENSHOT_VIEWS


def __getattr__(name: str):
    # 保持 SCREENSHOT_VIEWS 的模块属性兼容（PEP 562，懒加载避免 VTK 导入开销）
    if name == "SCREENSHOT_VIEWS":
        return _screenshot_views()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _RenderTagMismatch(ValueError):
    """Zero-hit ``highlight_tags`` guard.

    The message already carries the actionable payload (missing tags plus
    the tags that ARE available on these shapes); the render error handler
    promotes it to ``what_happened`` instead of demoting it into technical
    details.
    """


def _prepare_screenshot_render(
    shapes: Union[Solid, Sequence[Solid], Any],
    output_path: str,
    highlight_tags: Optional[Sequence[str]] = None,
    tag_labels: Optional[Dict[str, str]] = None,
    image_size: Tuple[int, int] = (1400, 900),
    view: Union[Tuple[float, float], str] = "auto",
    views: Optional[Sequence[Tuple[float, float, str]]] = None,
    show_axes: bool = True,
    show_legend: bool = True,
    zoom: float = 4.0,
    show_callouts: bool = True,
    linear_deflection: Optional[float] = None,
    angular_deflection: Optional[float] = None,
    style: str = "studio",
    edge_width_scale: Optional[float] = None,
    view_up: Optional[Sequence[float]] = None,
    supersample: int = 2,
    highlight_edges: Optional[Sequence[Any]] = None,
    highlight_edge_width: float = 4.5,
    worker_isolated: bool = False,
) -> Any:
    """Normalize inputs and build render datasets for one screenshot.

    Imports VTK/OCP and tessellates — main thread only. Pair with
    :func:`_execute_screenshot_render`, which is thread-safe.
    """
    try:
        from ..inspect.brep.render import _execute_polydata_render, _prepare_sdk_screenshot

        shape_list = _normalize_shape_input(shapes)
        solids = [
            shape for shape in shape_list if isinstance(shape, (Solid, TopoDS_Shape))
        ]
        if len(solids) != len(shape_list) or not solids:
            raise ValueError(
                "render_screenshot_rpath supports Solid or raw TopoDS_Shape inputs"
            )
        resolved_views = views
        if resolved_views is None and (view is None or view == "auto"):
            resolved_views = _screenshot_views()
        # Agent-facing contract: a requested tag that matches nothing is
        # almost certainly a typo or a tag from a different build stage —
        # fail loudly instead of silently labelling empty air.
        missing = sorted(
            tag
            for tag in (str(item) for item in (highlight_tags or ()))
            if not any(
                isinstance(shape, Solid) and shape._has_tag(tag)
                or (
                    isinstance(shape, Solid)
                    and any(face._has_tag(tag) for face in shape._iter_faces())
                )
                for shape in solids
            )
        )
        if missing:
            # Name what IS available: the typo guess ("was it boss_root or
            # boss-root?") is answerable only from the shapes themselves.
            available = sorted(
                {
                    tag
                    for shape in solids
                    if isinstance(shape, Solid)
                    for tag in (
                        *shape._list_tags(),
                        *(face_tag for face in shape._iter_faces()
                          for face_tag in face._list_tags()),
                    )
                }
            )
            shown = ", ".join(available[:24]) or "none"
            more = (
                f" (+{len(available) - 24} more)"
                if len(available) > 24 else ""
            )
            raise _RenderTagMismatch(
                "highlight_tags matched no geometry: "
                + ", ".join(missing)
                + f" — available tags on these shapes: {shown}{more}; "
                "check tag names and the build stage that produced them"
            )
        return _prepare_sdk_screenshot(
            solids,
            output_path,
            highlight_tags=tuple(highlight_tags or ()),
            tag_labels=tag_labels,
            image_size=image_size,
            view=view,
            show_axes=show_axes,
            show_legend=show_legend,
            zoom=zoom,
            show_callouts=show_callouts,
            linear_deflection=linear_deflection,
            angular_deflection=angular_deflection,
            views=resolved_views,
            style=style,
            edge_width_scale=edge_width_scale,
            view_up=tuple(float(value) for value in view_up) if view_up is not None else None,
            supersample=supersample,
            highlight_edges=tuple(highlight_edges) if highlight_edges else (),
            highlight_edge_width=highlight_edge_width,
            worker_isolated=worker_isolated,
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="render_screenshot_rpath",
            # Mechanism-A promotion: the zero-hit guard's payload (missing
            # + available tags) is the headline fact, not a footnote.
            what_happened=(
                str(e) if isinstance(e, _RenderTagMismatch)
                else "Failed to render the screenshot."
            ),
            possible_causes=[
                "The input does not contain any valid Solid objects.",
                "The rendering view or zoom configuration is invalid.",
                "The output path is invalid or not writable.",
            ],
            how_to_fix=[
                "Pass a Solid or a sequence of Solid objects.",
                "Use a supported view preset or a valid (elev, azim) tuple.",
                "Check that the output path is writable.",
            ],
            error=e,
        )


def _execute_screenshot_render(prepared: Any) -> str:
    """Run the prepared render (GL work); thread-safe via the render plan.

    On macOS the GL work runs in the crash-isolated worker subprocess;
    elsewhere it runs in-process and therefore belongs on the main
    thread — the diagnostic evidence channel always requests
    ``worker_isolated`` so its daemon thread only ever touches a
    subprocess.
    """
    from ..inspect.brep.render import _execute_polydata_render

    return str(_execute_polydata_render(prepared))


def render_screenshot_rpath(
    shapes: Union[Solid, Sequence[Solid], Any],
    output_path: str,
    highlight_tags: Optional[Sequence[str]] = None,
    tag_labels: Optional[Dict[str, str]] = None,
    image_size: Tuple[int, int] = (1400, 900),
    view: Union[Tuple[float, float], str] = "auto",
    views: Optional[Sequence[Tuple[float, float, str]]] = None,
    show_axes: bool = True,
    show_legend: bool = True,
    zoom: float = 4.0,
    show_callouts: bool = True,
    linear_deflection: Optional[float] = None,
    angular_deflection: Optional[float] = None,
    style: str = "studio",
    edge_width_scale: Optional[float] = None,
    view_up: Optional[Sequence[float]] = None,
    supersample: int = 2,
    highlight_edges: Optional[Sequence[Any]] = None,
    highlight_edge_width: float = 4.5,
) -> str:
    """Render solids or raw TopoDS shapes through the one OCCT/VTK pipeline.

    ``shapes`` accepts SDK ``Solid`` objects (with full tag highlight,
    callout and legend support) or raw ``TopoDS_Shape`` entries from the
    STEP inspection family (same engine, same edge ink and supersampling,
    no tag features).

    ``highlight_edges`` draws the given edges (SDK ``Edge`` objects or raw
    ``TopoDS_Edge``) as crisp orange highlight lines exactly on the edge —
    the failure-marking channel used by the blend diagnostics.

    There is exactly one output form: a multi-view grid of one to four
    panels, each carrying annotations. ``view="auto"`` (default) uses the
    standard four-view set; an explicit preset name or ``(elevation,
    azimuth)`` pair renders a single full-frame panel; ``views`` accepts
    up to four explicit ``(elevation, azimuth, label)`` triples.
    ``zoom`` applies to single-panel renders only.

    ``supersample (default 2) renders at an integer multiple and
    downsamples with LANCZOS for deterministic crisp edges; 1 renders 1:1.
    ``style="studio"`` turns the single-view path into a product shot
    (gradient backdrop, three-point lighting, bold tubed BRep edges);
    ``linear_deflection``/``angular_deflection`` tighten the tessellation
    for high-resolution exports. ``edge_width_scale`` tunes the studio edge
    tube radius as a fraction of model span (default 0.0026; use ~0.001 for
    exploded stacks so the ink does not swamp small parts).

    The prepare half (validation + tessellation) runs on the calling
    thread; the GL work runs in a crash-isolated worker subprocess, so a
    native VTK crash can never take the caller down.
    """
    prepared = _prepare_screenshot_render(
        shapes,
        output_path,
        highlight_tags=highlight_tags,
        tag_labels=tag_labels,
        image_size=image_size,
        view=view,
        views=views,
        show_axes=show_axes,
        show_legend=show_legend,
        zoom=zoom,
        show_callouts=show_callouts,
        linear_deflection=linear_deflection,
        angular_deflection=angular_deflection,
        style=style,
        edge_width_scale=edge_width_scale,
        view_up=view_up,
        supersample=supersample,
        highlight_edges=highlight_edges,
        highlight_edge_width=highlight_edge_width,
    )
    try:
        return _execute_screenshot_render(prepared)
    except Exception as e:
        _wrap_public_api_error(
            operation="render_screenshot_rpath",
            what_happened="Failed to render the screenshot.",
            possible_causes=[
                "The rendering view or zoom configuration is invalid.",
                "The output path is invalid or not writable.",
            ],
            how_to_fix=[
                "Use a supported view preset or a valid (elev, azim) tuple.",
                "Check that the output path is writable.",
            ],
            error=e,
        )


def fillet_rsolid(
    solid: Solid,
    edges: Union[Sequence[Edge], ShapeSelector],
    radius: ScalarLike,
    *,
    result_tag: Optional[str] = None,
    generated_faces_tag: Optional[str] = None,
) -> Solid:
    """Apply fillets, with optional tagging of kernel-proven patch faces."""
    selected_edges: List[Edge] = []
    radius_value: Optional[float] = None
    try:
        assignments = _normalize_operation_role_tags(
            _OP_MAKE_FILLET_RSOLID,
            (("fillet.patch", generated_faces_tag),),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        radius_value = evaluate_scalar(radius)
        if radius_value <= 0:
            raise ValueError("圆角半径必须大于0")

        selected_edges = cast(List[Edge], _resolve_selector_or_shapes(solid, edges))
        if not selected_edges:
            raise ValueError("圆角操作至少需要一条边")

        tracked = tracked_fillet(solid, selected_edges, radius_value)
        result = cast(Solid, tracked.shape)

        # Mechanism E: the kernel can hand back impossible geometry without
        # raising (observed: all-edge r=6 on a 10-cube "succeeds" with a
        # larger volume); catch it at the exit instead of returning it.
        assert_blend_volume_monotonic(
            solid,
            result,
            operation="fillet_rsolid",
            operation_kind="fillet",
            size_value=radius_value,
            edges=selected_edges,
        )

        result._metadata = solid._metadata.copy()

        selected_edge_refs = _serialize_shape_refs(selected_edges)
        selected_edge_node_ids = _ensure_geo_selection_node_ids(solid, selected_edges)

        selection_params: Dict[str, object] = {
            "radius": radius,
            "edge_count": len(selected_edges),
            "selected_edges": selected_edge_refs,
        }
        if selected_edge_node_ids:
            selection_params["selected_edge_node_ids"] = selected_edge_node_ids
        else:
            selection_params["selected_edge_indices"] = _serialize_selection_indices(
                selected_edges, solid._iter_edges()
            )

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            result,
            op=_OP_MAKE_FILLET_RSOLID,
            params=selection_params,
            source_solid=solid,
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
            input_shapes=[solid, *selected_edges],
        )
        return _apply_operation_role_tags(
            finalized,
            op=_OP_MAKE_FILLET_RSOLID,
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
    except Exception as e:
        _wrap_blend_failure(
            operation="fillet_rsolid",
            operation_kind="fillet",
            solid=solid,
            edges=selected_edges,
            size_value=radius_value,
            error=e,
            retry_single=(
                lambda edge: _blend_single_edge_ok(
                    solid, edge, radius_value, operation_kind="fillet"
                )
                if radius_value is not None
                else None
            ),
            default_what_happened="Failed to apply the fillet operation.",
            default_possible_causes=[
                "The radius is not a positive finite scalar.",
                "No valid edges were selected.",
                "The selected edges are incompatible with the requested fillet radius.",
            ],
            default_how_to_fix=[
                "Use a positive fillet radius.",
                "Select at least one valid edge or use a selector that resolves to edges.",
                "If the kernel rejects the fillet, try a smaller radius or a simpler edge set.",
            ],
        )

def _chamfer_reference_face_pairs(
    edges: Sequence[Edge],
    reference_direction: Tuple[float, float, float],
) -> List[Tuple[Edge, Edge]]:
    """Order each edge's adjacent faces as (reference, other).

    The reference face is the adjacent face whose outward normal has the
    largest dot product with ``reference_direction``.
    """
    direction = np.array(reference_direction, dtype=float)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-12:
        raise ValueError("chamfer reference_direction must be non-zero")
    direction = direction / norm
    pairs: List[Tuple[Edge, Edge]] = []
    for edge in edges:
        faces = edge.get_incident_faces()
        if len(faces) < 2:
            raise ValueError(
                "An angled chamfer needs two adjacent faces per selected edge"
            )
        def alignment(face: Edge) -> float:
            normal = face.get_normal_at()
            return float(
                normal.x * direction[0]
                + normal.y * direction[1]
                + normal.z * direction[2]
            )

        ranked = sorted(faces, key=alignment, reverse=True)
        pairs.append((ranked[0], ranked[1]))
    return pairs


def chamfer_rsolid(
    solid: Solid,
    edges: Union[Sequence[Edge], ShapeSelector],
    distance: ScalarLike,
    *,
    angle: Optional[float] = None,
    reference_direction: Optional[Tuple[float, float, float]] = None,
    result_tag: Optional[str] = None,
    generated_faces_tag: Optional[str] = None,
) -> Solid:
    """Apply chamfers, with optional tagging of kernel-proven patch faces.

    Without ``angle`` the chamfer is symmetric (both legs equal
    ``distance``). With ``angle`` — measured in degrees between the chamfer
    face and the reference face — the chamfer is asymmetric with the second
    leg at ``distance * tan(angle)`` on the non-reference side;
    ``reference_direction`` picks, per edge, the adjacent face whose outward
    normal best matches it as the reference face.
    """
    selected_edges: List[Edge] = []
    distance_value: Optional[float] = None
    chamfer_distance2: Optional[float] = None
    try:
        assignments = _normalize_operation_role_tags(
            _OP_MAKE_CHAMFER_RSOLID,
            (("chamfer.patch", generated_faces_tag),),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        distance_value = evaluate_scalar(distance)
        if distance_value <= 0:
            raise ValueError("倒角距离必须大于0")

        selected_edges = cast(List[Edge], _resolve_selector_or_shapes(solid, edges))
        if not selected_edges:
            raise ValueError("倒角操作至少需要一条边")

        chamfer_distance2: Optional[float] = None
        edge_face_pairs: Optional[List[Tuple[Edge, Edge]]] = None
        if angle is not None:
            if reference_direction is None:
                raise ValueError(
                    "An angled chamfer requires reference_direction to pick "
                    "the face anchoring the distance"
                )
            angle_radians = math.radians(float(angle))
            if not (0.0 < angle_radians < 0.5 * math.pi):
                raise ValueError("Chamfer angle must be between 0 and 90 degrees")
            chamfer_distance2 = distance_value * math.tan(angle_radians)
            edge_face_pairs = _chamfer_reference_face_pairs(
                selected_edges, reference_direction
            )

        tracked = tracked_chamfer(
            solid,
            selected_edges,
            distance_value,
            distance2=chamfer_distance2,
            edge_face_pairs=edge_face_pairs,
        )
        result = cast(Solid, tracked.shape)

        # Mechanism E: same impossible-output guard as the fillet path (the
        # effective size of an angled chamfer spans both legs).
        assert_blend_volume_monotonic(
            solid,
            result,
            operation="chamfer_rsolid",
            operation_kind="chamfer",
            size_value=(
                max(distance_value, chamfer_distance2)
                if chamfer_distance2 is not None else distance_value
            ),
            edges=selected_edges,
        )

        result._metadata = solid._metadata.copy()

        selected_edge_refs = _serialize_shape_refs(selected_edges)
        selected_edge_node_ids = _ensure_geo_selection_node_ids(solid, selected_edges)

        selection_params: Dict[str, object] = {
            "distance": distance,
            "edge_count": len(selected_edges),
            "selected_edges": selected_edge_refs,
            "angle": angle,
            "reference_direction": reference_direction,
        }
        if chamfer_distance2 is not None:
            selection_params["distance2"] = chamfer_distance2
        if selected_edge_node_ids:
            selection_params["selected_edge_node_ids"] = selected_edge_node_ids
        else:
            selection_params["selected_edge_indices"] = _serialize_selection_indices(
                selected_edges, solid._iter_edges()
            )

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            result,
            op=_OP_MAKE_CHAMFER_RSOLID,
            params=selection_params,
            source_solid=solid,
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
            input_shapes=[solid, *selected_edges],
        )
        return _apply_operation_role_tags(
            finalized,
            op=_OP_MAKE_CHAMFER_RSOLID,
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
    except Exception as e:
        effective_size = (
            max(distance_value, chamfer_distance2 or 0.0)
            if distance_value is not None
            else None
        )
        _wrap_blend_failure(
            operation="chamfer_rsolid",
            operation_kind="chamfer",
            solid=solid,
            edges=selected_edges,
            size_value=effective_size,
            error=e,
            retry_single=(
                lambda edge: _blend_single_edge_ok(
                    solid,
                    edge,
                    distance_value,
                    operation_kind="chamfer",
                    distance2=chamfer_distance2,
                )
                if distance_value is not None
                else None
            ),
            default_what_happened="Failed to apply the chamfer operation.",
            default_possible_causes=[
                "The distance is not a positive finite scalar.",
                "No valid edges were selected.",
                "The selected edges are incompatible with the requested chamfer size.",
            ],
            default_how_to_fix=[
                "Use a positive chamfer distance.",
                "Select at least one valid edge or use a selector that resolves to edges.",
                "If the kernel rejects the chamfer, try a smaller distance or fewer edges.",
            ],
        )

def shell_rsolid(
    solid: Solid,
    faces_to_remove: Union[Sequence[Face], ShapeSelector],
    thickness: ScalarLike,
    *,
    result_tag: Optional[str] = None,
    body_faces_tag: Optional[str] = None,
    offset_faces_tag: Optional[str] = None,
    closing_faces_tag: Optional[str] = None,
    wall_edges_tag: Optional[str] = None,
) -> Solid:
    """Shell a solid, with optional kernel-role-based face tags."""
    try:
        assignments = _normalize_operation_role_tags(
            _OP_MAKE_SHELL_RSOLID,
            (
                ("shell.body_face", body_faces_tag),
                ("shell.offset_face", offset_faces_tag),
                ("shell.closing_descendant", closing_faces_tag),
                ("shell.wall", wall_edges_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        thickness_value = evaluate_scalar(thickness)
        if thickness_value <= 0:
            raise ValueError("壁厚必须大于0")

        selected_faces = cast(
            List[Face], _resolve_selector_or_shapes(solid, faces_to_remove)
        )
        if not selected_faces:
            raise ValueError("抽壳操作至少需要一个待移除面")

        tracked = tracked_shell(solid, selected_faces, thickness_value)
        result = cast(Solid, tracked.shape)

        result._metadata = solid._metadata.copy()

        selected_face_refs = _serialize_shape_refs(selected_faces)
        selected_face_node_ids = _ensure_geo_selection_node_ids(solid, selected_faces)

        selection_params: Dict[str, object] = {
            "thickness": thickness,
            "removed_face_count": len(selected_faces),
            "selected_faces": selected_face_refs,
        }
        if selected_face_node_ids:
            selection_params["selected_face_node_ids"] = selected_face_node_ids
        else:
            selection_params["selected_face_indices"] = _serialize_selection_indices(
                selected_faces, solid._iter_faces()
            )

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            result,
            op=_OP_MAKE_SHELL_RSOLID,
            params=selection_params,
            source_solid=solid,
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
            input_shapes=[solid, *selected_faces],
        )
        return _apply_operation_role_tags(
            finalized,
            op=_OP_MAKE_SHELL_RSOLID,
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="shell_rsolid",
            what_happened="Failed to apply the shell operation.",
            possible_causes=[
                "The thickness is not a positive finite scalar.",
                "No valid faces were selected for removal.",
                "The requested shell thickness is incompatible with the current solid.",
            ],
            how_to_fix=[
                "Use a positive shell thickness.",
                "Select at least one valid face to remove.",
                "If the shell fails, try a smaller thickness or a different face selection.",
            ],
            error=e,
        )

def loft_rsolid(
    profiles: Sequence[Union[Wire, Vertex]],
    ruled: bool = False,
    *,
    tracking_policy: TrackingPolicy | str = TrackingPolicy.FULL,
    tag_prefix: Optional[str] = None,
    result_tag: Optional[str] = None,
    start_face_tag: Optional[str] = None,
    end_face_tag: Optional[str] = None,
    side_faces_tag: Optional[str] = None,
) -> Solid:
    """Create a lofted solid, with optional kernel-role-based tags."""
    try:
        profile_list = _validated_loft_sections(profiles, operation="loft_rsolid")
        if start_face_tag is not None and isinstance(profile_list[0], Vertex):
            raise ValueError("start_face_tag requires a Wire start section")
        if end_face_tag is not None and isinstance(profile_list[-1], Vertex):
            raise ValueError("end_face_tag requires a Wire end section")
        policy = (
            TrackingPolicy.GRAPH
            if current_tracking_policy() == TrackingPolicy.GRAPH
            else TrackingPolicy(tracking_policy)
        )
        assignments = _normalize_operation_role_tags(
            _OP_MAKE_LOFT_RSOLID,
            (
                ("loft.start", start_face_tag),
                ("loft.end", end_face_tag),
                ("loft.side", side_faces_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        profiles = profile_list

        if policy == TrackingPolicy.GRAPH and (assignments or tag_prefix is not None):
            raise ValueError(
                "GRAPH tracking does not provide loft face-role evidence; "
                "use FULL tracking for tag_prefix, start_face_tag, end_face_tag, "
                "or side_faces_tag"
            )

        tracked = (
            tracked_loft(profiles, ruled=ruled)
            if policy == TrackingPolicy.FULL
            else None
        )
        result = (
            cast(Solid, tracked.shape)
            if tracked is not None
            else Solid(
                make_loft_solid((profile.wrapped for profile in profiles), ruled=ruled)
            )
        )

        all_metadata = {}
        for profile in profiles:
            all_metadata.update(profile._metadata)

        result._metadata = all_metadata

        params: Dict[str, object] = {
            "profile_count": len(profiles),
            "ruled": ruled,
            "tracking_policy": policy.value,
        }
        if tracked is not None:
            target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
            finalized = _finalize_tracked_solid(
                result,
                op=_OP_MAKE_LOFT_RSOLID,
                params=params,
                delta=tracked.delta,
                delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
                input_shapes=profiles,
            )
        else:
            target_kinds = {}
            finalized = cast(
                Solid,
                _finalize_derived_shape(
                    result,
                    op=_OP_MAKE_LOFT_RSOLID,
                    params=params,
                    input_shapes=profiles,
                ),
            )
        tagged = _apply_operation_role_tags(
            finalized,
            op=_OP_MAKE_LOFT_RSOLID,
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
        if tracked is None:
            return tagged
        return _apply_feature_tag_prefix(
            tagged,
            tag_prefix=tag_prefix,
            op=_OP_MAKE_LOFT_RSOLID,
            delta=tracked.delta,
            start_role=("loft.start" if isinstance(profiles[0], Wire) else None),
            end_role=("loft.end" if isinstance(profiles[-1], Wire) else None),
            side_role="loft.side",
            source_shapes=profiles,
        )
    except Exception as e:
        # Section-compatibility diagnosis first (coincident stations, edge
        # counts, closure, ordering); the kernel names nothing itself.  When
        # no verdict lands, fall through to the generic wrap.
        if not isinstance(e, SimpleCADError):
            try:
                raise_loft_failure_if_diagnosed(profiles, "loft_rsolid")
            except SimpleCADError:
                raise
            except Exception:
                pass
        _wrap_public_api_error(
            operation="loft_rsolid",
            what_happened="Failed to loft the input profiles into a solid.",
            possible_causes=[
                "Fewer than two sections were provided.",
                "A Vertex section was used away from the start or end.",
                "One or more Wire/Vertex sections are invalid or incompatible.",
                "The kernel rejected the loft because the section geometry is inconsistent.",
            ],
            how_to_fix=[
                "Pass at least two Wire or endpoint Vertex sections.",
                "Keep Wire topology compatible across sections.",
                "If loft fails, inspect each section individually and simplify its geometry.",
            ],
            error=e,
        )

def sweep_rsolid(
    profile: Face,
    path: Wire,
    is_frenet: bool = False,
    *,
    tag_prefix: Optional[str] = None,
    result_tag: Optional[str] = None,
    start_face_tag: Optional[str] = None,
    end_face_tag: Optional[str] = None,
    side_faces_tag: Optional[str] = None,
) -> Solid:
    """Create a swept solid, with optional kernel-role-based tags."""
    make_solid = True  # 默认创建实体
    try:
        assignments = _normalize_operation_role_tags(
            _OP_MAKE_SWEEP_RSOLID,
            (
                ("sweep.start", start_face_tag),
                ("sweep.end", end_face_tag),
                ("sweep.side", side_faces_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        tracked = tracked_sweep(profile, path, is_frenet=is_frenet)
        result = cast(Solid, tracked.shape)

        result._metadata = {**profile._metadata, **path._metadata}

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            result,
            op=_OP_MAKE_SWEEP_RSOLID,
            params={"is_frenet": bool(is_frenet)},
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
            input_shapes=[profile, path],
        )
        tagged = _apply_operation_role_tags(
            finalized,
            op=_OP_MAKE_SWEEP_RSOLID,
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
        return _apply_feature_tag_prefix(
            tagged,
            tag_prefix=tag_prefix,
            op=_OP_MAKE_SWEEP_RSOLID,
            delta=tracked.delta,
            start_role="sweep.start",
            end_role="sweep.end",
            side_role="sweep.side",
            source_shapes=[profile],
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="sweep_rsolid",
            what_happened="Failed to sweep the profile along the path.",
            possible_causes=[
                "The profile face is invalid.",
                "The path wire is invalid or unsuitable for sweep.",
                "The kernel rejected the sweep orientation or geometry.",
            ],
            how_to_fix=[
                "Pass a valid Face profile and a valid Wire path.",
                "Check that the path wire is continuous and geometrically reasonable.",
                "If sweep fails, simplify the profile or path before retrying.",
            ],
            error=e,
        )

def twisted_sweep_rsolid(
    profile: Face,
    distance: ScalarLike,
    twist_angle: ScalarLike,
    axis: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    *,
    guide_radius: ScalarLike = 1.0,
    tag_prefix: Optional[str] = None,
    result_tag: Optional[str] = None,
    start_face_tag: Optional[str] = None,
    end_face_tag: Optional[str] = None,
    side_faces_tag: Optional[str] = None,
) -> Solid:
    """Sweep a planar profile along a straight axis with linear rotation.

    ``twist_angle`` is the signed total rotation in degrees. The operation uses
    a cylindrical auxiliary spine to define a continuous rotation law, yielding
    one continuous side face per profile edge instead of a segmented ruled loft.
    """
    try:
        if not isinstance(profile, Face):
            raise TypeError("profile must be a Face")
        distance_value = float(evaluate_scalar(distance))
        twist_value = float(evaluate_scalar(twist_angle))
        guide_radius_value = float(evaluate_scalar(guide_radius))
        if not math.isfinite(distance_value) or distance_value <= 0.0:
            raise ValueError("distance must be a finite positive number")
        if not math.isfinite(twist_value):
            raise ValueError("twist_angle must be finite")
        if not math.isfinite(guide_radius_value) or guide_radius_value <= 0.0:
            raise ValueError("guide_radius must be a finite positive number")

        axis_value = cast(Tuple[float, float, float], evaluate_value(axis))
        origin_value = cast(Tuple[float, float, float], evaluate_value(origin))
        if len(axis_value) != 3 or len(origin_value) != 3:
            raise ValueError("axis and origin must each contain three values")
        cs = get_current_cs()
        global_axis = cs.transform_vector(np.asarray(axis_value, dtype=float))
        global_origin = cs.transform_point(np.asarray(origin_value, dtype=float))
        axis_norm = float(np.linalg.norm(global_axis))
        if not math.isfinite(axis_norm) or axis_norm <= 1.0e-15:
            raise ValueError("axis must be a finite non-zero vector")
        global_axis /= axis_norm
        resolved_axis = tuple(float(value) for value in global_axis)
        resolved_origin = tuple(float(value) for value in global_origin)

        assignments = _normalize_operation_role_tags(
            _OP_MAKE_TWISTED_SWEEP_RSOLID,
            (
                ("twisted_sweep.start", start_face_tag),
                ("twisted_sweep.end", end_face_tag),
                ("twisted_sweep.side", side_faces_tag),
            ),
        )
        normalized_result_tag = (
            normalize_tag(result_tag, strict=True) if result_tag is not None else None
        )
        tracked = tracked_twisted_sweep(
                profile,
                axis=resolved_axis,
                origin=resolved_origin,
                distance=distance_value,
                twist_angle=twist_value,
                guide_radius=guide_radius_value,
            )
        result = cast(Solid, tracked.shape)
        kernel_metadata = result.get_metadata("twisted_sweep.kernel", {})
        result._metadata = profile._metadata.copy()
        result.set_metadata("twisted_sweep.kernel", kernel_metadata)

        target_kinds = _validate_operation_output_roles(tracked.delta, assignments)
        finalized = _finalize_tracked_solid(
            result,
            op=_OP_MAKE_TWISTED_SWEEP_RSOLID,
            params={
                "axis": axis,
                "origin": origin,
                "distance": distance,
                "twist_angle": twist_angle,
                "guide_radius": guide_radius,
            },
            delta=tracked.delta,
            delta_entries=cast(Dict[str, Dict[str, object]], tracked.delta_entries),
            input_shapes=[profile],
        )
        tagged = _apply_operation_role_tags(
            finalized,
            op=_OP_MAKE_TWISTED_SWEEP_RSOLID,
            assignments=assignments,
            target_kinds=target_kinds,
            result_tag=normalized_result_tag,
        )
        return _apply_feature_tag_prefix(
            tagged,
            tag_prefix=tag_prefix,
            op=_OP_MAKE_TWISTED_SWEEP_RSOLID,
            delta=tracked.delta,
            start_role="twisted_sweep.start",
            end_role="twisted_sweep.end",
            side_role="twisted_sweep.side",
            source_shapes=[profile],
        )
    except Exception as e:
        _wrap_public_api_error(
            operation="twisted_sweep_rsolid",
            what_happened="Failed to sweep the profile with a linear axial rotation.",
            possible_causes=[
                "The profile is invalid or contains inner wires.",
                "The distance, twist angle, axis, or guide radius is invalid.",
                "The requested twist causes self-intersection or kernel failure.",
            ],
            how_to_fix=[
                "Pass a valid planar Face without inner wires.",
                "Use a positive distance and guide radius with a non-zero axis.",
                "Reduce the twist angle or simplify the profile.",
            ],
            error=e,
        )

def helical_sweep_rsolid(
    profile: Wire,
    pitch: float,
    height: float,
    radius: float,
    center: Tuple[float, float, float] = (0, 0, 0),
    dir: Tuple[float, float, float] = (0, 0, 1),
    *,
    handedness: str = "Right",
) -> Solid:
    """Create a solid by sweeping a profile along a helical path."""
    try:
        if get_active_session() is not None:
            helix = make_helix_rwire(
                pitch, height, radius, center=center, dir=dir,
                handedness=handedness,
            )
            return sweep_rsolid(
                make_face_from_wire_rface(profile), helix, is_frenet=True
            )

        if pitch <= 0:
            raise ValueError("螺距必须大于0")
        if height <= 0:
            raise ValueError("高度必须大于0")
        if radius <= 0:
            raise ValueError("半径必须大于0")

        cs = get_current_cs()
        global_center = cs.transform_point(np.array(center))
        global_dir = cs.transform_vector(np.array(dir))
        global_x_direction = cs.transform_vector(_default_plane_x_direction(dir))

        result_shape = make_helical_sweep_solid(
            profile.wrapped,
            pitch,
            height,
            radius,
            global_center,
            global_dir,
            x_direction=global_x_direction,
        )
        result = Solid(result_shape)

        result._metadata = profile._metadata.copy()
        result._apply_tag("solid.feature.helical_sweep", propagate=False)

        return result
    except Exception as e:
        _wrap_public_api_error(
            operation="helical_sweep_rsolid",
            what_happened="Failed to create the helical sweep solid.",
            possible_causes=[
                "Pitch, height, or radius is not positive.",
                "The input profile wire is invalid or cannot form a face.",
                "The center or direction vector is invalid.",
                "The underlying helix or sweep construction failed.",
            ],
            how_to_fix=[
                "Use positive pitch, height, and radius values.",
                "Pass a valid profile wire that can be turned into a face.",
                "Validate the center and direction inputs before retrying.",
                "If the sweep still fails, try the explicit macro path: helix wire -> face from profile -> sweep.",
            ],
            error=e,
        )


def offset_rsolid(
    solid: Solid,
    amount: ScalarLike,
    openings: Sequence[Face] | ShapeSelector = (),
    *,
    tolerance: float = 1e-4,
    kind: str = "ARC",
) -> Solid:
    """Offset a solid outward (positive) or inward (negative).

    The amount must be finite and nonzero. Faces passed as ``openings`` form an
    open shell; with no openings the result is the closed offset solid. The
    join ``kind`` is ``ARC`` or ``INTERSECTION``. Invalid kernel results raise
    an error. The operation is recorded as ``make_offset_rsolid`` with explicit
    face selections; topology tag lineage is conservatively partial.
    ``shell_rsolid`` keeps its own contract (a positive inward wall thickness);
    this one supports both signs.

    Args:
        solid: The solid to offset.
        amount: Offset distance; positive outward, negative inward.
        openings: Faces of ``solid`` (or a QL selector) left open.
        tolerance: Kernel tolerance of the offset.
        kind: Join type, ``"ARC"`` or ``"INTERSECTION"``.

    Returns:
        The offset solid.

    Raises:
        ValueError: ``amount`` is zero or not finite, ``tolerance`` is not
            finite and positive, ``kind`` is unknown, ``openings`` do not select
            faces, or the kernel produced an invalid result.
    """
    distance = evaluate_scalar(amount)
    if not math.isfinite(distance) or distance == 0:
        raise ValueError("amount must be finite and nonzero")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    joins = {"ARC": GeomAbs_Arc, "INTERSECTION": GeomAbs_Intersection}
    if kind not in joins:
        raise ValueError("kind must be ARC or INTERSECTION")
    faces = list(_resolve_selector_or_shapes(solid, openings))
    if any(not isinstance(face, Face) for face in faces):
        raise ValueError("openings must select faces")
    selected_ids = _ensure_geo_selection_node_ids(solid, faces)
    face_list = TopTools_ListOfShape()
    for face in faces:
        face_list.Append(face.wrapped)
    builder = BRepOffsetAPI_MakeThickSolid()
    builder.MakeThickSolidByJoin(solid.wrapped, face_list, distance, tolerance,
                                Intersection=True, RemoveIntEdges=True, Join=joins[kind])
    builder.Build()
    if not builder.IsDone():
        raise ValueError("kernel could not offset the solid")
    params = {"amount": amount, "tolerance": tolerance, "kind": kind,
              "removed_face_count": len(faces), "selected_faces": _serialize_shape_refs(faces)}
    if selected_ids:
        params["selected_face_node_ids"] = selected_ids
    return _finish(solid, builder.Shape(), "make_offset_rsolid", params, [solid, *faces])


def draft_rsolid(
    solid: Solid,
    faces_to_draft: Sequence[Face] | ShapeSelector,
    angle: ScalarLike,
    plane_origin: Sequence[float] = (0, 0, 0),
    plane_normal: Sequence[float] = (0, 0, 1),
) -> Solid:
    """Draft planar, cylindrical or conical faces by a signed angle in degrees.

    The neutral plane fixes the unchanged section: the selected faces lean
    toward or away from it. Its origin and normal are in current
    coordinate-system coordinates. Face selection is checked against the input
    body and retained as graph inputs for strict replay. The input solid is
    preserved, the output must be one valid solid, and a zero angle records an
    unchanged result. Other surface families are explicitly rejected.

    The operation is recorded as ``make_draft_rsolid``; the body and selected
    faces are ordered inputs, and the angle, neutral plane and face selection
    nodes are parameters, so model JSON replay is strict.

    Args:
        solid: The body to draft.
        faces_to_draft: Faces of ``solid``, or a QL selector that picks them.
        angle: Draft angle in degrees, strictly between -90 and 90.
        plane_origin: A point of the neutral plane.
        plane_normal: Normal of the neutral plane; must be nonzero.

    Returns:
        The drafted solid.

    Raises:
        TypeError: ``solid`` is not a Solid.
        ValueError: Empty selection, a selection that is not made of faces of
            ``solid``, an unsupported surface family, a zero plane normal, or
            a nonfinite or out-of-range angle.

    Examples:
        import simplecadapi as scad
        from simplecadapi import ql
        body = scad.make_box_rsolid(10, 10, 10)
        right = ql.faces().where(ql.prop("geom.normal.x", ">", 0.9)).exactly(1)
        drafted = scad.draft_rsolid(body, right, angle=10)
    """
    if not isinstance(solid, Solid):
        raise TypeError("solid must be a Solid")
    degrees = float(evaluate_scalar(angle))
    if not math.isfinite(degrees) or abs(degrees) >= 90:
        raise ValueError("angle must be finite and strictly between -90 and 90 degrees")
    origin = _finite_vector(plane_origin, "plane_origin")
    normal = _finite_vector(plane_normal, "plane_normal")
    cs = get_current_cs()
    global_origin = cs.transform_point(np.asarray(origin))
    global_normal = cs.transform_vector(np.asarray(normal))
    magnitude = float(np.linalg.norm(global_normal))
    if magnitude <= 1e-14:
        raise ValueError("plane_normal must be nonzero")
    global_normal = global_normal / magnitude
    selected = list(_resolve_selector_or_shapes(solid, faces_to_draft))
    if not selected:
        raise ValueError("draft requires at least one selected face")
    original_faces = solid._iter_faces()
    for face in selected:
        if not isinstance(face, Face):
            raise ValueError("faces_to_draft must select only Face objects")
        if not any(face.wrapped.IsSame(other.wrapped) for other in original_faces):
            raise ValueError("selected draft faces must belong to the input solid")
        if BRepAdaptor_Surface(face.wrapped).GetType() not in {GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone}:
            raise ValueError("draft supports only planar, cylindrical, and conical faces")
    # Remove repeated references without changing the ordered face selection.
    selected = list({face.topo_id: face for face in selected}.values())
    selected_ids = _ensure_geo_selection_node_ids(solid, selected)
    if degrees == 0:
        shape = solid.wrapped
    else:
        direction = gp_Dir(*global_normal)
        plane = gp_Pln(gp_Pnt(*global_origin), direction)
        builder = BRepOffsetAPI_DraftAngle(solid.wrapped)
        for face in selected:
            builder.Add(face.wrapped, direction, math.radians(degrees), plane, True)
            if not builder.AddDone():
                raise ValueError("kernel could not add the requested draft angle to a selected face")
        builder.Build()
        if not builder.IsDone():
            raise ValueError("kernel could not build the drafted solid")
        shape = builder.Shape()
    params = {"angle": angle, "plane_origin": plane_origin, "plane_normal": plane_normal,
              "selected_face_count": len(selected), "selected_faces": _serialize_shape_refs(selected)}
    if selected_ids:
        params["selected_face_node_ids"] = selected_ids
    return _finish(solid, shape, "make_draft_rsolid", params, [solid, *selected])


def extrude_taper_rsolid(
    profile: Face,
    vector: Sequence[float],
    taper: float,
    flip_inner: bool = True,
) -> Solid:
    """Extrude a planar sketch face by a vector, with a taper in degrees.

    The vector is nonzero and in current coordinate-system coordinates. The
    finite taper angle lies strictly between -90 and 90; a positive taper
    shrinks the outer section, and inner loops taper the opposite way when
    ``flip_inner`` is true. An analytic draft prism is used where applicable
    and exact offset sections with lofts otherwise. Collapsed loops and invalid
    topology raise errors. The operation is recorded as
    ``make_extrude_taper_rsolid`` for replay.

    Args:
        profile: The planar face to extrude.
        vector: Extrusion vector (nonzero).
        taper: Taper angle in degrees, strictly between -90 and 90.
        flip_inner: Taper inner loops in the opposite direction.

    Returns:
        The tapered solid.

    Raises:
        ValueError: A zero vector, an out-of-range taper, a nonplanar profile,
            collapsed loops or an invalid result.
    """
    values = _finite_vector(vector, "vector")
    angle = float(evaluate_scalar(taper))
    if not math.isfinite(angle) or abs(angle) >= 90:
        raise ValueError("taper must be finite and between -90 and 90 degrees")
    displacement = get_current_cs().transform_vector(np.asarray(values))
    length = float(np.linalg.norm(displacement))
    if length <= 1e-12:
        raise ValueError("extrusion vector must be nonzero")
    surface = BRepAdaptor_Surface(profile.wrapped, True)
    if surface.GetType() != GeomAbs_Plane:
        raise ValueError("taper extrusion requires a planar profile")
    normal = np.asarray(tuple(profile.get_normal_at()), dtype=float)
    outer = BRepTools.OuterWire_s(profile.wrapped)
    wires = [outer]
    explorer = TopExp_Explorer(profile.wrapped, TopAbs_WIRE)
    while explorer.More():
        wire = TopoDS.Wire_s(explorer.Current())
        if not wire.IsSame(outer):
            wires.append(wire)
        explorer.Next()
    if angle == 0:
        shape = BRepPrimAPI_MakePrism(profile.wrapped, gp_Vec(*displacement)).Shape()
    elif np.linalg.norm(displacement / length - normal) < 1e-8 and normal[2] > 0 and len(wires) == 1 and angle > 0:
        shape = LocOpe_DPrism(profile.wrapped, length / math.cos(math.radians(angle)), math.radians(angle)).Shape()
    else:
        # Offset in the profile plane before translating the final section.
        move = gp_Trsf()
        move.SetTranslation(gp_Vec(*displacement))
        solids = []
        for i, wire in enumerate(wires):
            # Face inner wires wind opposite to the outer boundary. Normalize
            # their winding before applying the signed 2-D offset so that
            # flip_inner controls geometry rather than kernel wire orientation.
            if i:
                wire = TopoDS.Wire_s(wire.Reversed())
            offset = -length * math.tan(math.radians(angle)) * (-1 if i and flip_inner else 1)
            builder = BRepOffsetAPI_MakeOffset(wire, GeomAbs_Intersection, False)
            builder.Perform(offset)
            if not builder.IsDone():
                raise ValueError("taper collapses a profile loop")
            offset_shape = builder.Shape()
            exp = TopExp_Explorer(offset_shape, TopAbs_WIRE)
            found = []
            while exp.More():
                found.append(TopoDS.Wire_s(exp.Current()))
                exp.Next()
            if len(found) != 1:
                raise ValueError("taper changes loop connectivity")
            moved = BRepBuilderAPI_Transform(found[0], move, True).Shape()
            loft = BRepOffsetAPI_ThruSections(True, False)
            loft.AddWire(wire)
            loft.AddWire(TopoDS.Wire_s(moved))
            loft.Build()
            if not loft.IsDone():
                raise ValueError("kernel could not build tapered sections")
            solids.append(loft.Shape())
        shape = solids[0]
        for tool in solids[1:]:
            cut = BRepAlgoAPI_Cut(shape, tool)
            cut.Build()
            if not cut.IsDone():
                raise ValueError("kernel could not subtract tapered inner loop")
            shape = cut.Shape()
    return _finish(profile, shape, "make_extrude_taper_rsolid",
                   {"vector": vector, "taper": taper, "flip_inner": flip_inner}, [profile])


def sweep_multisection_rsolid(
    profiles: Sequence[Face | Wire],
    path: Wire,
    is_frenet: bool = False,
    binormal: Sequence[float] | Wire | None = None,
) -> Solid:
    """Sweep through explicit ordered sections along a continuous path.

    At least two ordered sections are needed. Face sections supply their outer
    wire, matching build123d's multi-section sweep contract. ``binormal`` is an
    optional direction vector or an auxiliary spine. The kernel must produce
    one valid solid. Every section and the path are recorded as inputs of
    ``make_sweep_multisection_rsolid``, so model JSON preserves the
    construction.

    Args:
        profiles: Ordered section faces or wires (at least two).
        path: The continuous path wire.
        is_frenet: Use the Frenet frame along the path.
        binormal: A direction, or an auxiliary spine wire, that fixes the
            section orientation.

    Returns:
        The swept solid.

    Raises:
        TypeError: A section is neither a Face nor a Wire.
        ValueError: Fewer than two sections, a zero ``binormal`` direction, or
            the kernel could not make a solid.
    """
    sections = list(profiles)
    if len(sections) < 2:
        raise ValueError("multi-section sweep requires at least two sections")
    builder = BRepOffsetAPI_MakePipeShell(path.wrapped)
    rotate = False
    if isinstance(binormal, Wire):
        builder.SetMode(binormal.wrapped, True)
    elif binormal is not None:
        values = _finite_vector(binormal, "binormal")
        direction = get_current_cs().transform_vector(np.asarray(values))
        if np.linalg.norm(direction) < 1e-12:
            raise ValueError("binormal direction must be nonzero")
        builder.SetMode(gp_Dir(*direction))
        rotate = True
    else:
        builder.SetMode(bool(is_frenet))
    for section in sections:
        if not isinstance(section, (Face, Wire)):
            raise TypeError("sections must be Face or Wire")
        wire = BRepTools.OuterWire_s(section.wrapped) if isinstance(section, Face) else section.wrapped
        builder.Add(wire, False, rotate)
    builder.Build()
    if not builder.IsDone() or not builder.MakeSolid():
        raise ValueError("kernel could not make a solid multi-section sweep")
    inputs = [*sections, path]
    params = {"profile_count": len(sections), "is_frenet": bool(is_frenet), "binormal": None}
    if isinstance(binormal, Wire):
        inputs.append(binormal)
        params["binormal_is_wire"] = True
    elif binormal is not None:
        params["binormal"] = binormal
    return _finish(sections[0], builder.Shape(), "make_sweep_multisection_rsolid", params, inputs)


def _top_level(shape):
    if shape.ShapeType() != TopAbs_COMPOUND:
        return [shape]
    output = []
    iterator = TopoDS_Iterator(shape)
    while iterator.More():
        output.extend(_top_level(iterator.Value()))
        iterator.Next()
    return output


def _crosses_direction(face, axis):
    """Ignore side walls tangent to the extrusion, including coincident walls."""
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    properties = BRepGProp_Face(face)
    for u in (.25, .5, .75):
        for v in (.25, .5, .75):
            point, normal = gp_Pnt(), gp_Vec()
            properties.Normal(u0 + u * (u1-u0), v0 + v * (v1-v0), point, normal)
            length = normal.Magnitude()
            if length > 1e-14 and abs(normal.X()*axis[0] + normal.Y()*axis[1] + normal.Z()*axis[2]) / length > 1e-8:
                return True
    return False


def _contact_surfaces(target, prism, axis):
    common = BRepAlgoAPI_Common(target, prism)
    common.Build()
    if not common.IsDone() or not faces_of(common.Shape()):
        raise ValueError("No intersection: extrusion does not contact target")
    history = common.History()
    modified = []
    intersection_faces = faces_of(common.Shape())
    for face in faces_of(target):
        affected = list(history.Modified(face))
        if affected:
            modified.extend(TopoDS.Face_s(item) for item in affected if item.ShapeType() == TopAbs_FACE)
        elif not history.IsRemoved(face) and any(item.IsSame(face) for item in intersection_faces):
            # A whole target may lie inside the temporary prism, in which case
            # unchanged boundary faces are still genuine contact surfaces.
            modified.append(face)
    if not modified:
        raise ValueError("No target boundary surfaces found in extrusion intersection")
    sewing = BRepBuilderAPI_Sewing(1e-6)
    for face in modified:
        if _crosses_direction(face, axis):
            sewing.Add(face)
    sewing.Perform()
    surfaces = _top_level(sewing.SewedShape())
    if not surfaces or any(part.ShapeType() not in {TopAbs_FACE, TopAbs_SHELL} for part in surfaces):
        raise ValueError("Kernel could not sew target contact surfaces")
    return surfaces


def _split_on_surface(prism, surface, keep_top):
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(prism)
    tools.Append(surface)
    splitter = BRepAlgoAPI_Splitter()
    splitter.SetArguments(arguments)
    splitter.SetTools(tools)
    splitter.Build()
    if not splitter.IsDone():
        raise ValueError("Kernel could not split extrusion on target surface")
    reference_face = TopoDS.Face_s(surface) if surface.ShapeType() == TopAbs_FACE else faces_of(surface)[0]
    u0, u1, v0, v1 = BRepTools.UVBounds_s(reference_face)
    point, normal = gp_Pnt(), gp_Vec()
    BRepGProp_Face(reference_face).Normal((u0+u1)/2, (v0+v1)/2, point, normal)
    if normal.Magnitude() <= 1e-14:
        raise ValueError("Undefined normal on termination surface")
    normal.Normalize()
    reference = point.Translated(normal)
    if surface.ShapeType() == TopAbs_FACE:
        halfspace = BRepPrimAPI_MakeHalfSpace(TopoDS.Face_s(surface), reference).Solid()
    else:
        halfspace = BRepPrimAPI_MakeHalfSpace(TopoDS.Shell_s(surface), reference).Solid()
    candidates = []
    for part in solids_of(splitter.Shape()):
        common = BRepAlgoAPI_Common(part, halfspace)
        common.Build()
        if not common.IsDone():
            raise ValueError("Kernel could not classify the termination side")
        properties = GProp_GProps()
        BRepGProp.LinearProperties_s(common.Shape(), properties)
        is_top = properties.Mass() >= 1e-6
        if is_top == keep_top:
            candidates.append(part)
    return candidates


def extrude_until_rsolid(
    profile: Face,
    target: Solid | Sequence[Solid],
    direction: Sequence[float] = (0, 0, 1),
    until: str = "NEXT",
) -> Solid:
    """Extrude a planar face until a target surface, including curved surfaces.

    The direction is interpreted in the current coordinate system and
    normalized before construction. ``until`` selects the termination:
    ``NEXT`` (forward, nearest intersecting target surface), ``LAST`` (forward,
    farthest), ``PREVIOUS`` (reverse, nearest) and ``FIRST`` (reverse,
    farthest). The temporary prism is intersected with the target, the target's
    boundary faces are taken from kernel history and sewn into surfaces, and
    the prism is split on the selected one. Bounding boxes only size the
    temporary prism; they do not define the termination surface, and side
    walls parallel to the direction do not join separate near and far limits.

    Targets must cover the profile at the requested contact: an uncovered,
    open or disconnected output is rejected, as are a missing contact, an
    invalid mode, a zero or nonfinite direction and an empty target sequence.
    Inputs are preserved. The operation is recorded as
    ``make_extrude_until_rsolid``; its ordered inputs are the profile followed
    by every target solid and its parameters keep ``direction``, ``until`` and
    ``target_count``, so a changed target is recomputed on replay (no final
    BRep is embedded).

    Args:
        profile: The planar face to extrude.
        target: A solid, or a sequence of solids, that bounds the extrusion.
        direction: Extrusion direction in current coordinate-system
            coordinates.
        until: ``"NEXT"``, ``"LAST"``, ``"PREVIOUS"`` or ``"FIRST"``.

    Returns:
        One valid solid.

    Raises:
        TypeError: ``profile`` is not a Face, or ``target`` is not a Solid or
            a sequence of Solid.
        ValueError: No target, no contact, insufficient coverage, a bad mode
            or direction, or an invalid kernel result.

    Examples:
        import simplecadapi as scad
        profile = scad.make_rectangle_rface(2, 2)
        ceiling = scad.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 5))
        near = scad.extrude_until_rsolid(profile, ceiling, until="NEXT")  # volume 20
        far = scad.extrude_until_rsolid(profile, ceiling, until="LAST")  # volume 28
        sphere = scad.make_sphere_rsolid(5, center=(0, 0, 10))
        curved = scad.extrude_until_rsolid(profile, sphere)
    """
    if not isinstance(profile, Face):
        raise TypeError("profile must be a Face")
    targets = [target] if isinstance(target, Solid) else list(target)
    if not targets:
        raise ValueError("target must contain at least one Solid")
    if any(not isinstance(item, Solid) for item in targets):
        raise TypeError("target must be a Solid or a sequence of Solid")
    mode = str(getattr(until, "name", until)).upper()
    if mode not in {"NEXT", "LAST", "PREVIOUS", "FIRST"}:
        raise ValueError("until must be NEXT, LAST, PREVIOUS, or FIRST")
    values = _finite_vector(direction, "direction")
    global_direction = get_current_cs().transform_vector(np.asarray(values))
    magnitude = float(np.linalg.norm(global_direction))
    if not math.isfinite(magnitude) or magnitude <= 1e-14:
        raise ValueError("direction must be a finite nonzero vector")
    axis = global_direction / magnitude
    if mode in {"PREVIOUS", "FIRST"}:
        axis = -axis
    bound_target = make_compound_always([item.wrapped for item in targets])
    box = bounding_box(make_compound_always([profile.wrapped, bound_target]))
    length = math.sqrt((box.xmax-box.xmin)**2 + (box.ymax-box.ymin)**2 + (box.zmax-box.zmin)**2)
    if length <= 1e-12:
        raise ValueError("Degenerate profile and target bounds")
    prism = BRepPrimAPI_MakePrism(profile.wrapped, gp_Vec(*(axis * length))).Shape()
    surfaces = sorted(_contact_surfaces(bound_target, prism, axis), key=lambda part: distance(part, profile.wrapped))
    nearest = mode in {"NEXT", "PREVIOUS"}
    surface = surfaces[0] if nearest else surfaces[-1]
    candidates = _split_on_surface(prism, surface, keep_top=nearest)
    if not candidates:
        raise ValueError("Extrusion produced no solid on the requested side of the target")
    origin = np.asarray(tuple(center_of_mass(profile.wrapped)))
    chosen = min(candidates, key=lambda part: np.dot(np.asarray(tuple(center_of_mass(part))) - origin, axis))
    if abs(volume(chosen) - volume(prism)) <= max(1e-8, abs(volume(prism))*1e-9):
        raise ValueError("Target termination surface does not completely cover the extrusion profile")
    if volume(chosen) <= 1e-12 or not BRepCheck_Analyzer(chosen).IsValid():
        raise ValueError("Target surface did not completely cover a valid limited extrusion")
    result = _finish(profile, chosen, "make_extrude_until_rsolid",
                     {"direction": direction, "until": mode, "target_count": len(targets)}, [profile, *targets])
    result._apply_tag("solid.extrusion", propagate=False)
    return result

__all__ = tuple(name for name in globals() if not name.startswith("__"))

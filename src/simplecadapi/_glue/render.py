"""``render_screenshot_rpath`` on native shapes: the C++ software renderer.

The 3D layer (tessellation, rasterisation, edge ink, id buffer) is ``simplecadapi._cpp``'s renderer; the legend,
callouts and axes labels are drawn on it by ``simplecadapi._cpp.screenshot`` (Pillow).  Nothing here needs OCP, VTK or
a display.  The prepare/execute pair keeps the shape of ``operators/features.py``: callers (failure-evidence
renders) prepare on the calling thread and execute wherever they like.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from ..errors import raise_harness_error


def _shape_types() -> tuple:
    import simplecadapi._cpp as n

    return (n.Compound, n.Solid, n.Shell, n.Face, n.Wire, n.Edge, n.Vertex)


class _RenderTagMismatch(ValueError):
    """Zero-hit ``highlight_tags`` guard (the message names the tags that exist)."""


def _screenshot_views() -> Tuple[Tuple[float, float, str], ...]:
    from simplecadapi._cpp.screenshot import SCREENSHOT_VIEWS

    return SCREENSHOT_VIEWS



def _normalize_shape_input(shapes: Any) -> List[Any]:
    if isinstance(shapes, _shape_types()):
        return [shapes]
    if isinstance(shapes, Sequence) and not isinstance(shapes, (str, bytes)):
        normalized: List[Any] = []
        for item in shapes:
            normalized.extend(_normalize_shape_input(item))
        return normalized
    raise ValueError(
        "rendering accepts Compound, Solid, Shell, Face, Wire, Edge, Vertex, "
        "or nested sequences of those types"
    )


@dataclass
class _Prepared:
    """A validated render request: everything the renderer needs, nothing that touches a display."""

    solids: List[Any]
    output_path: str
    options: Dict[str, Any] = field(default_factory=dict)


def _prepare_screenshot_render(
    shapes: Any,
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
    import simplecadapi._cpp as n

    try:
        shape_list = _normalize_shape_input(shapes)
        solids = [shape for shape in shape_list if isinstance(shape, n.Solid)]
        if len(solids) != len(shape_list) or not solids:
            raise ValueError("render_screenshot_rpath supports Solid inputs")
        resolved_views = views
        if resolved_views is None and (view is None or view == "auto"):
            resolved_views = _screenshot_views()
        missing = sorted(
            tag
            for tag in (str(item) for item in (highlight_tags or ()))
            if not any(
                isinstance(shape, n.Solid)
                and (shape._has_tag(tag) or any(face._has_tag(tag) for face in shape._iter_faces()))
                for shape in solids
            )
        )
        if missing:
            available = sorted(
                {
                    tag
                    for shape in solids
                    if isinstance(shape, n.Solid)
                    for tag in (
                        *shape._list_tags(),
                        *(face_tag for face in shape._iter_faces() for face_tag in face._list_tags()),
                    )
                }
            )
            shown = ", ".join(available[:24]) or "none"
            more = f" (+{len(available) - 24} more)" if len(available) > 24 else ""
            raise _RenderTagMismatch(
                "highlight_tags matched no geometry: "
                + ", ".join(missing)
                + f" — available tags on these shapes: {shown}{more}; "
                "check tag names and the build stage that produced them"
            )
        return _Prepared(
            solids,
            str(output_path),
            dict(
                highlight_tags=tuple(highlight_tags or ()),
                tag_labels=tag_labels,
                image_size=image_size,
                view=view,
                show_axes=show_axes,
                show_legend=show_legend,
                zoom=zoom,
                show_callouts=show_callouts,
                linear_deflection=0.35 if linear_deflection is None else linear_deflection,
                angular_deflection=0.22 if angular_deflection is None else angular_deflection,
                views=resolved_views,
                style=style,
                edge_width_scale=0.0019 if edge_width_scale is None else edge_width_scale,
                view_up=tuple(float(value) for value in view_up) if view_up is not None else None,
                supersample=supersample,
                highlight_edges=tuple(highlight_edges) if highlight_edges else (),
                highlight_edge_width=highlight_edge_width,
            ),
        )
    except Exception as e:
        raise_harness_error(
            operation="render_screenshot_rpath",
            what_happened=(
                str(e) if isinstance(e, _RenderTagMismatch) else "Failed to render the screenshot."
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
    from simplecadapi._cpp.screenshot import render_screenshot

    render_screenshot(prepared.solids, prepared.output_path, **prepared.options)
    return prepared.output_path


def render_screenshot_rpath(
    shapes: Any,
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
    """Render solids through the software renderer (no OCP, VTK or display needed).

    Same contract as ``simplecadapi.render_screenshot_rpath`` of the ``ocp`` backend.
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
        raise_harness_error(
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

"""The BREP-inspection pictures, drawn on the C++ software renderer: no VTK, no GPU, no display.

The geometry of a picture is plain NumPy data (:class:`MeshData`, :class:`LineData`, :class:`PointData`); ``render_views``
puts it in a ``simplecadapi._cpp.RenderScene`` (shaded surfaces with per-triangle colours, ink-width BREP edges,
highlight groups, points), asks the renderer for the panels, and lays the text over them with Pillow: titles, legend,
axis letters and the callouts with their leader lines.  A callout whose anchor is hidden in a panel is moved to the
nearest visible pixel of the geometry it points at (the id buffer of the renderer says which pixels those are).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

_STANDARD_BASE = (0.55, 0.64, 0.73)
_STUDIO_BASE = (0.66, 0.68, 0.72)
_EDGE_INK = (0.16, 0.21, 0.27)
_HIGHLIGHT_SURFACE = (0.94, 0.18, 0.30)
_HIGHLIGHT_LINE = (0.78, 0.0, 0.0)


@dataclass(eq=False)
class MeshData:
    """Triangles with per-vertex normals; ``colors`` is an optional (triangles, 4) uint8 RGBA, one colour per triangle."""

    points: np.ndarray
    normals: np.ndarray
    triangles: np.ndarray
    colors: np.ndarray | None = None

    @property
    def triangle_count(self) -> int:
        return int(len(self.triangles))

    def bounds(self) -> tuple[float, float, float, float, float, float]:
        low, high = self.points.min(axis=0), self.points.max(axis=0)
        return (float(low[0]), float(high[0]), float(low[1]), float(high[1]), float(low[2]), float(high[2]))


@dataclass(eq=False)
class LineData:
    """Polylines: ``starts`` are offsets into ``points``, ``len(lines) + 1`` of them (polyline ``k`` is
    ``points[starts[k]:starts[k + 1]]``; the last offset is the number of points)."""

    points: np.ndarray
    starts: np.ndarray

    @property
    def line_count(self) -> int:
        return int(len(self.starts)) - 1

    def bounds(self) -> tuple[float, float, float, float, float, float]:
        low, high = self.points.min(axis=0), self.points.max(axis=0)
        return (float(low[0]), float(high[0]), float(low[1]), float(high[1]), float(low[2]), float(high[2]))


@dataclass(eq=False)
class PointData:
    points: np.ndarray

    @property
    def point_count(self) -> int:
        return int(len(self.points))

    def bounds(self) -> tuple[float, float, float, float, float, float]:
        low, high = self.points.min(axis=0), self.points.max(axis=0)
        return (float(low[0]), float(high[0]), float(low[1]), float(high[1]), float(low[2]), float(high[2]))


def _rgb8(color: Sequence[float]) -> tuple[int, int, int]:
    return tuple(int(round(255 * float(v))) for v in color[:3])  # type: ignore[return-value]


def _add_mesh(scene, mesh: MeshData, color: Sequence[float], opacity: float, *, studio: bool) -> int:
    triangles = np.ascontiguousarray(mesh.triangles, dtype=np.uint32)
    if mesh.colors is not None:
        # one "face" per triangle: the renderer colours by face id
        face_ids = np.arange(len(triangles), dtype=np.uint32)
        face_colors = np.ascontiguousarray(mesh.colors, dtype=np.float32) / 255.0
    else:
        face_ids = np.zeros(len(triangles), dtype=np.uint32)
        face_colors = None
    return scene.add_mesh_arrays(
        np.ascontiguousarray(mesh.points, dtype=np.float32),
        np.ascontiguousarray(mesh.normals, dtype=np.float32),
        triangles,
        face_ids,
        color=tuple(float(v) for v in color),
        opacity=float(opacity),
        studio_material=studio,
        lit=True,
        face_colors=face_colors,
    )


def _add_lines(scene, lines: LineData, color, *, ink: bool, width_px: float | None) -> int:
    return scene.add_polylines(
        np.ascontiguousarray(lines.points, dtype=np.float32),
        np.ascontiguousarray(lines.starts, dtype=np.uint32),
        color=tuple(float(v) for v in color),
        ink=ink,
        width_px=width_px,
    )


def _visible_pixels(panel, depth: np.ndarray, points, tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    """Pixels (image coordinates) of those ``points`` that are in the panel and not behind the nearest surface there."""

    if points is None or len(points) == 0:
        return np.empty(0), np.empty(0)
    sample = np.asarray(points)
    if len(sample) > 3000:
        sample = sample[:: len(sample) // 3000 + 1]
    xs, ys = [], []
    for point in sample:
        x, y, distance, in_view = panel.project(tuple(float(v) for v in point))
        if not in_view:
            continue
        column, row = int(x), int(y)
        if not (0 <= column < depth.shape[1] and 0 <= row < depth.shape[0]):
            continue
        if distance <= depth[row, column] + tolerance:
            xs.append(x)
            ys.append(y)
    return np.asarray(xs), np.asarray(ys)


def render_views(
    base: MeshData | None,
    output_path: str | Path,
    *,
    title: str,
    views: Sequence[tuple[float, float, str]],
    image_size: tuple[float, float],
    dpi: int,
    context_opacity: float = 1.0,
    highlight_edge_width: float = 4.5,
    highlight_point_size: float = 15.0,
    brep_edges: LineData | None = None,
    highlighted: MeshData | None = None,
    highlighted_edges: LineData | None = None,
    highlighted_points: PointData | None = None,
    highlighted_groups: Sequence[tuple[MeshData, Sequence[float], float]] | None = None,
    highlighted_edge_groups: Sequence[tuple[LineData, Sequence[float]]] | None = None,
    highlighted_point_groups: Sequence[tuple[PointData, Sequence[float]]] | None = None,
    legend: Sequence[tuple[str, Sequence[float]]] | None = None,
    legend_columns: int = 1,
    legend_panel: bool = False,
    show_axes: bool = False,
    callouts: Sequence[tuple] | None = None,
    edge_width_scale: float = 0.0019,
    supersample: int = 1,
    style: str = "standard",
    zoom: float | None = None,
    view_up: Sequence[float] | None = None,
    datasets: Mapping[str, Any] | None = None,
) -> Path:
    """Draw ``views`` of the geometry into one PNG (or JPEG, by the suffix of ``output_path``)."""

    from PIL import Image, ImageDraw

    from simplecadapi import _cpp as native
    from simplecadapi._cpp.screenshot import _blend_box, _draw_callouts, _font

    if not views:
        raise ValueError("at least one render view is required")
    if dpi < 1 or image_size[0] <= 0.0 or image_size[1] <= 0.0:
        raise ValueError("image size and DPI must be greater than zero")
    if highlight_edge_width <= 0.0:
        raise ValueError("highlight_edge_width must be greater than zero")
    if highlight_point_size <= 0.0:
        raise ValueError("highlight_point_size must be greater than zero")
    if legend_columns < 1:
        raise ValueError("legend_columns must be at least one")
    if style not in ("standard", "studio"):
        raise ValueError(f"unknown render style: {style!r} (expected 'standard' or 'studio')")
    supersample = max(1, min(4, int(supersample)))
    studio = style == "studio"
    width = max(1, int(round(image_size[0] * dpi)))
    height = max(1, int(round(image_size[1] * dpi)))

    scene = native.RenderScene()
    mesh_index: dict[int, int] = {}  # id(geometry) -> index of its mesh in the scene, for the callout re-anchoring

    def surface(mesh: MeshData, color, opacity) -> None:
        mesh_index[id(mesh)] = _add_mesh(scene, mesh, color, opacity, studio=False)

    if base is not None:
        mesh_index[id(base)] = _add_mesh(scene, base, _STUDIO_BASE if studio else _STANDARD_BASE, context_opacity,
                                         studio=studio)
    if brep_edges is not None:
        if edge_width_scale > 0.0:
            _add_lines(scene, brep_edges, _EDGE_INK, ink=True, width_px=None)
        else:
            _add_lines(scene, brep_edges, _EDGE_INK, ink=False, width_px=1.0)
    if highlighted_groups:
        for mesh, color, opacity in highlighted_groups:
            surface(mesh, color, opacity)
    elif highlighted is not None:
        surface(highlighted, _HIGHLIGHT_SURFACE, 1.0)
    edge_px = highlight_edge_width / supersample
    if highlighted_edge_groups:
        for lines, color in highlighted_edge_groups:
            _add_lines(scene, lines, color, ink=False, width_px=edge_px)
    elif highlighted_edges is not None:
        _add_lines(scene, highlighted_edges, _HIGHLIGHT_LINE, ink=False, width_px=edge_px)
    point_px = highlight_point_size / supersample
    if highlighted_point_groups:
        for points, color in highlighted_point_groups:
            scene.add_points(np.ascontiguousarray(points.points, dtype=np.float32),
                             color=tuple(float(v) for v in color), size_px=point_px)
    elif highlighted_points is not None:
        scene.add_points(np.ascontiguousarray(highlighted_points.points, dtype=np.float32),
                         color=_HIGHLIGHT_LINE, size_px=point_px)

    callouts = list(callouts or ())
    legend = list(legend or ())
    panel_fraction = 0.30 if legend and legend_panel else 0.0
    frame = native.render_scene(
        scene, width, height, supersample=supersample, style=style,
        views=[(float(a), float(b), str(c)) for a, b, c in views],
        legend_panel_fraction=panel_fraction,
        view_up=tuple(float(v) for v in view_up) if view_up is not None else None,
        zoom=(float(zoom) / 4.0) if (len(views) == 1 and zoom is not None) else 1.0,
        edge_width_scale=edge_width_scale, show_axes=show_axes,
        anchors=[tuple(float(v) for v in entry[1]) for entry in callouts],
    )
    image = Image.fromarray(np.asarray(frame.rgba)[:, :, :3].copy())
    draw = ImageDraw.Draw(image)
    columns = min(2, len(views))
    rows = (len(views) + columns - 1) // columns
    ink = (0.85, 0.89, 0.94) if studio else (0.08, 0.11, 0.15)
    mesh_ids = np.asarray(frame.mesh_id)
    depth = np.asarray(frame.depth)
    low, high = scene.bounds()
    tolerance = max(float(max(h - l for l, h in zip(low, high))), 1e-9) * 0.002  # as the renderer's own anchor test

    for index, panel in enumerate(frame.panels):
        title_font = _font(max(14, min(width // columns, height // rows) // 34))
        text = f"{title}\n{panel.label}" if index == 0 else panel.label
        draw.multiline_text((panel.x + 16, panel.y + panel.height - 14), text, font=title_font, fill=_rgb8(ink),
                            anchor="ld")
        if show_axes:
            axis_font = _font(max(10, panel.height // 40), bold=False)
            for (tip_x, tip_y), (name, color) in zip(
                panel.axes_tips, (("X", (1, .3, .3)), ("Y", (.3, 1, .3)), ("Z", (.4, .55, 1)))
            ):
                draw.text((tip_x + 3, tip_y - 3), name, font=axis_font, fill=_rgb8(color))
        if callouts:
            callout_font = _font(max(18, min(28, min(width // columns, height // rows) // 30)))
            items = []
            for k, entry in enumerate(callouts):
                label, color = entry[0], entry[2]
                tag = entry[3] if len(entry) > 3 else None
                x, y, _depth, _in_view, visible = panel.anchors[k]
                if visible:
                    items.append((label, (x, y), color))
                    continue
                target = datasets.get(str(tag)) if (tag and datasets) else None
                if target is None:
                    continue  # nothing to re-anchor on: the callout is dropped for this panel
                found = mesh_index.get(id(target))
                if found is not None:  # a surface: the pixels the id buffer says belong to it
                    region = mesh_ids[panel.y:panel.y + panel.height, panel.x:panel.x + panel.width] == found
                    ys, xs = np.nonzero(region)
                    xs, ys = xs + panel.x, ys + panel.y
                else:  # edges and points: their own points that the depth buffer shows
                    xs, ys = _visible_pixels(panel, depth, getattr(target, "points", None), tolerance)
                if len(xs) == 0:
                    continue
                step = max(1, len(xs) // 4000)
                xs, ys = xs[::step], ys[::step]
                nearest = int(np.argmin((xs - x) ** 2 + (ys - y) ** 2))
                items.append((label, (float(xs[nearest]) + 0.5, float(ys[nearest]) + 0.5), color))
            _draw_callouts(draw, items, panel, callout_font)

    if legend:
        if panel_fraction:
            font = _font(max(12, min(20, height // 52)))
            spacing = int(font.size * 1.55)
            panel_x = int(round(width * (1 - panel_fraction)))
            column_width = (width - panel_x) / legend_columns
            per_column = (len(legend) + legend_columns - 1) // legend_columns
            for k, (label, color) in enumerate(legend):
                column, row = k // per_column, k % per_column
                draw.text((panel_x + 12 + column * column_width, spacing * 2 + row * spacing), "■ " + label, font=font,
                          fill=_rgb8(color))
        else:
            viewport_w, viewport_h = width // columns, height // rows
            font = _font(max(12, min(20, min(viewport_w, viewport_h) // 34)))
            spacing = int(font.size * 1.55)
            per_column = (len(legend) + legend_columns - 1) // legend_columns
            column_width = max(112, max(int(len(label) * font.size * 0.62) + 26 for label, _ in legend))
            start_x = max(16, viewport_w - column_width * legend_columns - 16)
            background = (0.02, 0.02, 0.04) if studio else (0.94, 0.96, 0.98)
            for k, (label, color) in enumerate(legend):
                column, row = k // per_column, k % per_column
                x = start_x + column * column_width
                y = max(48, 18) + row * spacing
                _blend_box(draw, (x - 2, y - 2, x + column_width - 8, y + spacing - 4), _rgb8(background), 0.8, image)
                draw.text((x, y), "■ " + label, font=font, fill=_rgb8(color))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in (".jpg", ".jpeg"):
        image.save(output, quality=95)
    else:
        image.save(output, compress_level=1)
    return output


def render_comparison(
    models: Sequence[tuple[str, str, MeshData, LineData | None]],
    output_path: str | Path,
    *,
    views: Sequence[tuple[float, float, str]],
    image_size: tuple[float, float],
    dpi: int,
    shared_bounds: tuple[float, float, float, float, float, float],
) -> Path:
    """Models side by side (one column each), one row per view, all with the same camera fit and scale.

    The renderer fits its camera to the scene it is given, so every cell carries an invisible triangle spanning
    ``shared_bounds`` (the union of the models' boxes): the fit, and so the scale, is then the same in every cell.
    """

    from PIL import Image, ImageDraw

    from simplecadapi import _cpp as native
    from simplecadapi._cpp.screenshot import _font

    if not views:
        raise ValueError("at least one render view is required")
    if dpi < 1 or image_size[0] <= 0.0 or image_size[1] <= 0.0:
        raise ValueError("image size and DPI must be greater than zero")
    width = max(1, int(round(image_size[0] * dpi)))
    height = max(1, int(round(image_size[1] * dpi)))
    columns, rows = len(models), len(views)
    cell_w, cell_h = width // columns, height // rows
    xmin, xmax, ymin, ymax, zmin, zmax = shared_bounds
    span = np.array([[xmin, ymin, zmin], [xmax, ymax, zmax], [xmin, ymin, zmin]], dtype=np.float32)
    up = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (3, 1))
    canvas = Image.new("RGB", (cell_w * columns, cell_h * rows), (240, 245, 250))
    draw = ImageDraw.Draw(canvas)
    font = _font(max(13, min(cell_w, cell_h) // 34))
    for row, (elevation, azimuth, view_title) in enumerate(views):
        for column, (model_title, filename, mesh, edges) in enumerate(models):
            scene = native.RenderScene()
            _add_mesh(scene, mesh, _STANDARD_BASE, 1.0, studio=False)
            if edges is not None:
                _add_lines(scene, edges, _EDGE_INK, ink=False, width_px=1.0)
            scene.add_mesh_arrays(span, up, np.array([[0, 1, 2]], dtype=np.uint32), np.zeros(1, dtype=np.uint32),
                                  opacity=0.0)
            frame = native.render_scene(scene, cell_w, cell_h, supersample=2, style="standard",
                                        views=[(float(elevation), float(azimuth), str(view_title))])
            cell = Image.fromarray(np.asarray(frame.rgba)[:, :, :3].copy())
            canvas.paste(cell, (column * cell_w, row * cell_h))
            draw.multiline_text((column * cell_w + 14, (row + 1) * cell_h - 12), f"{model_title}: {filename}\n{view_title}",
                                font=font, fill=_rgb8((0.08, 0.11, 0.15)), anchor="ld")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, compress_level=1)
    return output

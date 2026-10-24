"""SDK-style screenshots on the software renderer: the 3D layer comes from the C++ renderer, the text from PIL.

`render_screenshot` follows `simplecadapi.render_screenshot_rpath` (tag highlights, legend, callouts with per-view
occlusion suppression, multiview grid, axes labels, supersampling).  Requires numpy and Pillow.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import _native as _n

_PALETTE = ("#f39c12", "#9b59b6", "#f1c40f", "#1abc9c", "#e67e22", "#e84393", "#16a085", "#d35400")
SCREENSHOT_VIEWS = ((28.0, -45.0, "isometric"), (90.0, -90.0, "top / X-Y"), (0.0, -90.0, "front / X-Z"), (0.0, 0.0, "side / Y-Z"))


def _hex(value: str):
    t = value.lstrip("#")
    return tuple(int(t[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _font(size: int, bold: bool = True):
    from PIL import ImageFont

    for name in (("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Helvetica.ttc") if bold else ("DejaVuSans.ttf", "Arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _rgb8(c):
    return tuple(int(round(255 * v)) for v in c)


def _blend_box(draw, box, fill, opacity, img):
    from PIL import Image

    x0, y0, x1, y1 = (int(v) for v in box)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.width, x1), min(img.height, y1)
    if x1 <= x0 or y1 <= y0:
        return
    patch = Image.new("RGB", (x1 - x0, y1 - y0), fill)
    region = img.crop((x0, y0, x1, y1))
    img.paste(Image.blend(region, patch, opacity), (x0, y0))


def _select_callouts(frame, panel_index, callouts, tag_faces, panel):
    """Per-panel admission with occlusion re-anchoring (render.py _select_panel_callouts) using the id buffer."""
    import numpy as np

    out = []
    for k, (label, anchor, color, tag) in enumerate(callouts):
        x, y, depth, in_view, visible = panel.anchors[k]
        if visible:
            out.append((label, (x, y), color))
            continue
        faces = tag_faces.get(tag)
        if not faces:
            continue
        sub_ids = np.asarray(frame.face_id)[panel.y:panel.y + panel.height, panel.x:panel.x + panel.width]
        mask = np.isin(sub_ids, list(faces)) & (np.asarray(frame.mesh_id)[panel.y:panel.y + panel.height, panel.x:panel.x + panel.width] >= 0)
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            continue
        step = max(1, len(xs) // 4000)
        xs, ys = xs[::step] + panel.x, ys[::step] + panel.y
        j = int(np.argmin((xs - x) ** 2 + (ys - y) ** 2))
        out.append((label, (float(xs[j]) + 0.5, float(ys[j]) + 0.5), color))
    return out


def _draw_callouts(draw, items, panel, font):
    margin = font.size // 2
    line_h = font.size + 8
    placed = []

    def overlaps(b):
        return any(b[0] < o[2] and b[2] > o[0] and b[1] < o[3] and b[3] > o[1] for o in placed)

    for index, (label, (ax, ay), color) in enumerate(items):
        ax -= panel.x
        ay = panel.height - (ay - panel.y)  # VTK display coords: y up (placement heuristics are mirrored below)
        lw = max(88, int(len(label) * font.size * 0.62) + 12)
        ox = 18 if index % 2 == 0 else -lw - 18
        oy = 14 if index % 4 < 2 else -line_h - 14
        lx = min(max(ax + ox, margin), panel.width - lw - margin)
        ly = min(max(ay + oy, margin), panel.height - line_h - margin)
        box = (lx, ly, lx + lw, ly + line_h)
        attempts = 0
        while overlaps(box) and attempts < 24:
            ly += line_h if attempts % 2 == 0 else -2 * line_h
            ly = min(max(ly, margin), panel.height - line_h - margin)
            if attempts % 4 == 3:
                lx = min(max(lx + lw + 16, margin), panel.width - lw - margin)
            box = (lx, ly, lx + lw, ly + line_h)
            attempts += 1
        placed.append(box)
        ex = lx if lx >= ax else lx + lw
        ey = ly + line_h * 0.5
        # back to image coordinates (y down)
        flip = lambda yy: panel.y + panel.height - yy
        draw.line([(panel.x + ax, flip(ay)), (panel.x + ex, flip(ey))], fill=_rgb8(color), width=2)
        by0, by1 = flip(ly + line_h), flip(ly)
        draw.rectangle([panel.x + lx, by0, panel.x + lx + lw, by1], fill=_rgb8((0.04, 0.05, 0.07)))
        draw.text((panel.x + lx + 6, by0 + 3), label, font=font, fill=_rgb8(color))


def render_screenshot(
    shapes,
    output_path,
    *,
    highlight_tags: Sequence[str] = (),
    tag_labels: Mapping[str, str] | None = None,
    image_size=(1400, 900),
    view="auto",
    views=None,
    show_axes: bool = True,
    show_legend: bool = True,
    zoom: float = 4.0,
    show_callouts: bool = True,
    linear_deflection: float = 0.35,
    angular_deflection: float = 0.22,
    style: str = "studio",
    edge_width_scale: float = 0.0019,
    view_up=None,
    supersample: int = 2,
    highlight_edges: Sequence[Any] = (),
    highlight_edge_width: float = 4.5,
    return_frame: bool = False,
):
    import numpy as np
    from PIL import Image, ImageDraw

    if not isinstance(shapes, (list, tuple)):
        shapes = [shapes]
    if not shapes:
        raise ValueError("At least one Solid is required")
    if style not in ("standard", "studio"):
        raise ValueError(f"unknown render style: {style!r} (expected 'standard' or 'studio')")
    if int(supersample) not in (1, 2, 3):
        raise ValueError("supersample must be 1, 2, or 3")
    if not 0.0 <= edge_width_scale <= 0.02:
        raise ValueError("edge_width_scale must be within [0, 0.02] (fraction of model span)")
    tags = tuple(str(t) for t in highlight_tags)
    labels = dict(tag_labels or {})
    colors = {t: _hex(_PALETTE[i % len(_PALETTE)]) for i, t in enumerate(tags)}
    base_color = (0.66, 0.68, 0.72) if style == "studio" else (0.55, 0.64, 0.73)

    scene = _n.RenderScene()
    callouts: list[tuple[str, tuple, tuple, str]] = []
    tag_faces: dict[str, set[int]] = {}
    mesh_of_shape = []
    for solid in shapes:
        face_colors = None
        solid_tag = next((t for t in tags if solid._has_tag(t)), None)
        faces = solid.faces() if tags else []
        if tags:
            face_colors = np.full((max(1, len(faces)), 4), np.nan, dtype=np.float32)
            for i, face in enumerate(faces):
                tag = next((t for t in tags if face._has_tag(t)), None) or solid_tag
                if tag is None:
                    continue
                face_colors[i] = (*colors[tag], 1.0)
                tag_faces.setdefault(tag, set())
                if face._has_tag(tag):
                    c = face.get_center()
                    if not any(cc[3] == tag for cc in callouts):
                        callouts.append((labels.get(tag, tag), (c.x, c.y, c.z), colors[tag], tag))
        idx = scene.add_shape(solid, color=base_color, studio_material=(style == "studio"), face_colors=face_colors,
                              linear_deflection=linear_deflection, angular_deflection=angular_deflection,
                              edges=True, ink=True, edge_deflection=min(linear_deflection, 0.04))
        mesh_of_shape.append(idx)
        if tags:
            for i, face in enumerate(faces):
                tag = next((t for t in tags if face._has_tag(t)), None) or solid_tag
                if tag is not None:
                    tag_faces.setdefault(tag, set()).add(i)
            if solid_tag is not None and not any(cc[3] == solid_tag for cc in callouts):
                (lo, hi) = scene.bounds()
                callouts.append((labels.get(solid_tag, solid_tag), tuple((a + b) / 2 for a, b in zip(lo, hi)), colors[solid_tag], solid_tag))
    legend = []
    edge_rgb = (0.953, 0.612, 0.071)
    if highlight_edges:
        for e in highlight_edges:
            scene.add_edges(e, color=edge_rgb, width_px=highlight_edge_width / max(1, supersample), deflection=min(linear_deflection, 0.04))
    if show_legend and (tags or show_axes):
        legend += [(labels.get(t, t), colors[t]) for t in tags]
        if show_axes:
            legend += [("+X", (1.0, 0.35, 0.35)), ("+Y", (0.35, 1.0, 0.55)), ("+Z", (0.45, 0.65, 1.0))]
        if highlight_edges and show_legend:
            legend.append(("highlighted edges", edge_rgb))

    if views is not None:
        vs = [(float(a), float(b), str(c)) for a, b, c in views]
        if not vs:
            raise ValueError("views must contain at least one (elevation, azimuth, label)")
        if len(vs) > 4:
            raise ValueError("views accepts at most four (elevation, azimuth, label) entries")
    elif isinstance(view, str) and view.strip().lower() == "auto":
        vs = list(SCREENSHOT_VIEWS)
    else:
        el, az = _n.render_view_preset(view) if isinstance(view, str) else (float(view[0]), float(view[1]))
        vs = [(el, az, view.strip().lower() if isinstance(view, str) else "view")]
    single = len(vs) == 1
    w, h = int(image_size[0]), int(image_size[1])
    panel_frac = 0.30 if len(legend) > 8 else 0.0
    frame = _n.render_scene(
        scene, w, h, supersample=int(supersample), style=style, views=vs, legend_panel_fraction=panel_frac,
        view_up=tuple(view_up) if view_up is not None else None, zoom=(zoom / 4.0) if single else 1.0,
        edge_width_scale=edge_width_scale, show_axes=show_axes,
        anchors=[c[1] for c in callouts] if show_callouts else [],
    )
    img = Image.fromarray(np.asarray(frame.rgba)[:, :, :3].copy())
    draw = ImageDraw.Draw(img)
    cols = min(2, len(vs))
    rows = (len(vs) + cols - 1) // cols
    ink = (0.85, 0.89, 0.94) if style == "studio" else (0.08, 0.11, 0.15)
    for i, panel in enumerate(frame.panels):
        tfont = _font(max(14, min(w // cols, h // rows) // 34))
        text = ("SDK screenshot\n" + panel.label) if i == 0 else panel.label
        draw.multiline_text((panel.x + 16, panel.y + panel.height - 14), text, font=tfont, fill=_rgb8(ink), anchor="ld")
        if show_axes:
            afont = _font(max(10, panel.height // 40), bold=False)
            for (tx, ty), (name, col) in zip(panel.axes_tips, (("X", (1, .3, .3)), ("Y", (.3, 1, .3)), ("Z", (.4, .55, 1)))):
                draw.text((tx + 3, ty - 3), name, font=afont, fill=_rgb8(col))
        if show_callouts and callouts:
            cfont = _font(max(18, min(28, min(w // cols, h // rows) // 30)))
            items = _select_callouts(frame, i, callouts, tag_faces, panel)
            _draw_callouts(draw, items, panel, cfont)
    if legend:
        if panel_frac:
            font = _font(max(12, min(20, h // 52)))
            sp = int(font.size * 1.55)
            x0 = int(round(w * (1 - panel_frac))) + 12
            for k, (text, col) in enumerate(legend):
                draw.text((x0, sp * 2 + k * sp), "■ " + text, font=font, fill=_rgb8(col))
        else:
            vw, vh = w // cols, h // rows
            font = _font(max(12, min(20, min(vw, vh) // 34)))
            sp = int(font.size * 1.55)
            colw = max(112, max(int(len(t) * font.size * 0.62) + 26 for t, _ in legend))
            x0 = max(16, vw - colw - 16)
            for k, (text, col) in enumerate(legend):
                y = max(48, 18) + k * sp
                bg = (0.02, 0.02, 0.04) if style == "studio" else (0.94, 0.96, 0.98)
                _blend_box(draw, (x0 - 2, y - 2, x0 + colw - 8, y + sp - 4), _rgb8(bg), 0.8, img)
                draw.text((x0, y), "■ " + text, font=font, fill=_rgb8(col))
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        img.save(out, quality=95)
    else:
        img.save(out, compress_level=1)  # screenshots are large and written often: speed over size
    return (str(out), frame) if return_frame else str(out)

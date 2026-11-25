"""Add scaled details to a solved engineering sheet and render its print page."""

from __future__ import annotations

import math

from ezdxf.enums import TextEntityAlignment
from ezdxf.math import BoundingBox2d, Vec2
from ezdxf.math.clipping import CohenSutherlandLineClipping2d
from ezdxf.xclip import XClip

PREVIEW_LONG_SIDE_PX = 3600
DIAMETER_STYLE = "DXF_EXPORTER_DIM_SYMBOL"


def rectangle(center, size):
    half = size / 2
    return BoundingBox2d((center - half, center + half))


def draw_rectangle(msp, box, layer):
    x0, y0 = box.extmin
    x1, y1 = box.extmax
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={"layer": layer},
    )


def place_details(doc, plan, rows):
    from simplecadapi.dxf_engine.refs import project
    from simplecadapi.dxf_engine.render import _draw_view_edges
    from simplecadapi.dxf_engine.sheet import scale_text

    outlines = "DETAIL_OUTLINE"
    doc.layers.new(
        outlines, dxfattribs={"color": 7, "lineweight": 18, "linetype": "DASHED_GB"}
    )
    doc.header["$XCLIPFRAME"] = (
        0  # The separate outline remains available as DXF geometry.
    )
    msp = doc.modelspace()
    free = BoundingBox2d((plan.fmt.free[:2], plan.fmt.free[2:]))
    occupied = [
        BoundingBox2d(((box.x0, box.y0), (box.x1, box.y1)))
        for box in (view["bbox"] for view in plan.views.values())
    ]
    for _, x, y, width, height, angle in plan.text_obbs:
        theta = math.radians(angle)
        c, s = abs(math.cos(theta)), abs(math.sin(theta))
        occupied.append(
            rectangle(Vec2(x, y), Vec2(width * c + height * s, width * s + height * c))
        )

    records = []
    for row in rows:
        label, parent, center, scale, hidden = (
            row[key] for key in ("label", "parent", "center", "scale", "hidden")
        )
        size, at = Vec2(row["size"]), Vec2(row["at"])
        source = plan.views[parent]
        source_uv = Vec2(project(center, source["frame"]))
        source_local = rectangle(source_uv, size)
        clip = CohenSutherlandLineClipping2d(source_local.extmin, source_local.extmax)
        selected = [
            (ad, pts, visible)
            for ad, pts, visible in source["edges"]
            if (visible or hidden)
            and any(clip.clip_line(a, b) for a, b in zip(pts, pts[1:]))
        ]
        if not selected:
            raise ValueError(f"Detail {label}: crop contains no projected geometry")

        detail_box = rectangle(at, size * scale)
        # Include space for the centered title below the detail frame.
        title_width = len(f"DETAIL {label}  {scale_text(scale)}") * 2.0
        reserved = BoundingBox2d(
            (
                detail_box.extmin - (2, 9),
                detail_box.extmax + (2, 2),
                (at.x - title_width / 2, detail_box.extmin.y - 9),
                (at.x + title_width / 2, detail_box.extmin.y - 9),
            )
        )
        if not all(free.inside(p) for p in (reserved.extmin, reserved.extmax)):
            raise ValueError(
                f"Detail {label}: detail and title must fit within the drawing area"
            )
        box_clip = CohenSutherlandLineClipping2d(reserved.extmin, reserved.extmax)
        if any(reserved.has_intersection(box) for box in occupied) or any(
            box_clip.clip_line(p, q) for _, p, q in plan.segments
        ):
            raise ValueError(
                f"Detail {label}: choose a position clear of views, dimensions and other details"
            )
        occupied.append(reserved)

        source_sheet = rectangle(Vec2(plan.tx(parent, source_uv)), size * plan.s)
        name = f"DXF_EXPORTER_DETAIL_{label}"
        block = doc.blocks.new(name, base_point=plan.tx(parent, source_uv))
        _draw_view_edges(block, plan, {**source, "edges": selected})
        factor = scale / plan.s
        insert = msp.add_blockref(
            name, at, dxfattribs={"xscale": factor, "yscale": factor, "zscale": factor}
        )
        XClip(insert).set_wcs_clipping_path((detail_box.extmin, detail_box.extmax))
        draw_rectangle(msp, source_sheet, outlines)
        draw_rectangle(msp, detail_box, "TEXT")
        msp.add_text(label, dxfattribs={"layer": "TEXT", "height": 3.5}).set_placement(
            source_sheet.extmax + (2, 1)
        )
        msp.add_text(
            f"DETAIL {label}  {scale_text(scale)}",
            dxfattribs={"layer": "TEXT", "height": 3.5},
        ).set_placement(
            (at.x, detail_box.extmin.y - 6), align=TextEntityAlignment.MIDDLE_CENTER
        )
        records.append(
            dict(
                label=label,
                parent=parent,
                center_model_mm=center,
                source_center_uv_mm=tuple(source_uv),
                size_model_mm=tuple(size),
                scale=scale,
                position_sheet_mm=tuple(at),
                keeps_hidden_lines=hidden,
                block=name,
                source_edges=len(block),
                clip_sheet_mm=[tuple(detail_box.extmin), tuple(detail_box.extmax)],
            )
        )
    return records


def use_diameter_font(doc):
    """Use a diameter-capable font for numeric diameter labels in the saved DXF."""
    style = DIAMETER_STYLE
    for dimension in doc.modelspace().query("DIMENSION"):
        block = doc.blocks.get(dimension.dxf.geometry)
        for text in block.query("TEXT"):
            label = text.dxf.text
            if "%%c" not in label.lower() or not all(
                c.isascii() or c in "×±" for c in label
            ):
                continue
            if style not in doc.styles:
                doc.styles.new(style, dxfattribs={"font": "DejaVuSans.ttf"})
            text.dxf.style = style
            override = dimension.override()
            override["dimtxsty"] = style
            override.commit()
    return style in doc.styles


def render_print_page(doc, path, fmt, *, pdf):
    from pathlib import Path

    import matplotlib
    from simplecadapi.inspect.drawing._pymupdf import pymupdf
    from ezdxf.addons.drawing import (
        Frontend,
        RenderContext,
        config,
        layout,
        pymupdf as backend_module,
    )
    from ezdxf.fonts import fonts

    if DIAMETER_STYLE in doc.styles:
        fonts.font_manager.scan_folder(
            Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        )

    backend = backend_module.PyMuPdfBackend()
    style = config.Configuration(
        background_policy=config.BackgroundPolicy.WHITE,
        color_policy=config.ColorPolicy.BLACK,
    )
    Frontend(RenderContext(doc), backend, config=style).draw_layout(doc.modelspace())
    page = layout.Page(fmt.w, fmt.h, layout.Units.mm)
    paper = BoundingBox2d(((0, 0), (fmt.w, fmt.h)))
    width_pt, height_pt = (value * 72 / 25.4 for value in (fmt.w, fmt.h))
    # ezdxf 1.4.5 truncates page points and uses that integer for content scaling.
    # Correct that scaling, then place those vectors on the exact page at unit magnification.
    long_side_pt = max(width_pt, height_pt)
    settings = layout.Settings(
        fit_page=False,
        scale=long_side_pt / int(long_side_pt),
        page_alignment=layout.PageAlignment.TOP_LEFT,
    )
    data = backend.get_pdf_bytes(page, render_box=paper, settings=settings)
    with (
        pymupdf.open(stream=data, filetype="pdf") as source,
        pymupdf.open() as document,
    ):
        printed = document.new_page(width=width_pt, height=height_pt)
        printed.show_pdf_page(source[0].rect, source, 0)
        dpi = min(180, math.floor((PREVIEW_LONG_SIDE_PX - 1) * 72 / long_side_pt))
        pixmap = printed.get_pixmap(dpi=dpi, alpha=False)
        pixmap.save(path.with_suffix(".png"))
        preview = dict(
            dpi=dpi,
            pixels=[pixmap.width, pixmap.height],
            long_side_limit_px=PREVIEW_LONG_SIDE_PX,
        )
        del pixmap
        if pdf:
            document.save(path.with_suffix(".pdf"), deflate=True)
    return preview

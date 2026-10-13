"""Evidence viewport rendering: full-page overviews and region crops."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    import pymupdf
else:
    from ._pymupdf import pymupdf

from ._pdf import open_page
from ._provenance import page_metadata, pixel_transform

_DEFAULT_PAD_FRACTION = 0.2


def _resolve_rect(
    pymupdf_page: pymupdf.Page,
    rect: Sequence[float] | None,
    anchor: Mapping[str, Any] | None,
    pad_fraction: float,
) -> pymupdf.Rect:
    if rect is not None and anchor is not None:
        raise ValueError("pass either rect or anchor, not both")
    if anchor is not None:
        if pad_fraction < 0:
            raise ValueError("pad_fraction must be non-negative")
        box = anchor.get("box")
        if box is None:
            raise ValueError("anchor must carry a 'box' (from rwords/rstrokes output)")
        native = pymupdf.Rect(box)
        return pymupdf.Rect(
            native.x0 - native.width * pad_fraction,
            native.y0 - native.height * pad_fraction,
            native.x1 + native.width * pad_fraction,
            native.y1 + native.height * pad_fraction,
        )
    if rect is not None:
        if len(rect) != 4 or rect[0] >= rect[2] or rect[1] >= rect[3]:
            raise ValueError(f"rect must be [x0, y0, x1, y1] with x1 > x0, y1 > y0")
        return pymupdf.Rect(rect)
    return pymupdf_page.rect


def render_drawing_view_rpath(
    path: str | Path,
    page: int = 0,
    *,
    rect: Sequence[float] | None = None,
    anchor: Mapping[str, Any] | None = None,
    pad_fraction: float = _DEFAULT_PAD_FRACTION,
    dpi: int = 300,
    out_dir: str | Path = ".",
    stem: str | None = None,
) -> Path:
    """Render one page (or one region of it) to PNG for visual judgment.

    Pass neither ``rect`` nor ``anchor`` for a full-page overview; pass
    ``rect`` (display-space ``[x0, y0, x1, y1]``, the same coordinates the
    other drawing-inspection functions report) for a region crop; or pass an
    ``anchor`` (a word or cluster dict from ``extract_drawing_text_rwords``)
    to frame that annotation with ``pad_fraction`` margin so its leader lines
    stay attached. A ``<png>.json`` sidecar records the source file, page,
    display-space rect, and dpi so every viewed pixel is traceable back to
    sheet coordinates. Visual reading through this viewport is evidence for
    annotation attachment and small print, never for precise numbers: those
    come from the vector layer.
    The sidecar distinguishes requested and effective crop rectangles and records
    the integer pixmap origin, page-to-pixel and inverse homogeneous matrices.
    Page units are pt; pixel units are px, using pixel-edge coordinates. Source
    hash, page boxes, rotation, coordinate space and result version are included.
    """
    if dpi <= 0:
        raise ValueError("dpi must be positive")

    source = Path(path)
    document, pymupdf_page = open_page(source, page)
    try:
        metadata = page_metadata(source, pymupdf_page)
        if anchor is not None:
            for key in ("source_id", "page", "coordinate_space", "units"):
                if key in anchor and anchor[key] != metadata[key]:
                    raise ValueError(f"anchor {key} differs from viewport source")
        region = _resolve_rect(pymupdf_page, rect, anchor, pad_fraction)
        requested_region = list(region)
        region = region & pymupdf_page.rect
        if region.is_empty or region.width <= 0 or region.height <= 0:
            raise ValueError(
                f"rect {list(rect) if rect else rect} does not intersect page"
            )

        output_dir = Path(out_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        name_stem = stem if stem else f"{source.stem}.p{page}.dpi{dpi}"
        png_path = output_dir / f"{name_stem}.png"
        sidecar_path = output_dir / f"{name_stem}.json"

        matrix = pymupdf.Matrix(dpi / 72, dpi / 72)
        pixmap = pymupdf_page.get_pixmap(matrix=matrix, clip=region)
        pixmap.save(png_path)
        sidecar_path.write_text(
            json.dumps(
                {
                    **metadata,
                    "metadata": metadata,
                    **pixel_transform(dpi / 72, pixmap.x, pixmap.y),
                    "source_pdf": str(source.resolve()),
                    "requested_rect_display": requested_region,
                    "effective_rect_display": list(region),
                    "page": page,
                    "rect_display": [
                        region.x0,
                        region.y0,
                        region.x1,
                        region.y1,
                    ],
                    "pad_fraction": pad_fraction if anchor is not None else None,
                    "dpi": dpi,
                    "pixel_size": [pixmap.width, pixmap.height],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return png_path
    finally:
        document.close()

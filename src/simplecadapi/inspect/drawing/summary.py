"""Route-deciding health summary for one PDF drawing document."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pymupdf
else:
    from ._pymupdf import pymupdf

from ._pdf import color_to_hex, item_kind


@dataclass(frozen=True)
class DrawingSummary:
    """Facts-only health report for one PDF drawing document.

    ``route`` recommends how the downstream analysis should treat the file:
    ``vector`` (mine the text and vector layers), ``raster`` (render-only
    reading), ``mixed`` (both layers present), ``text_only`` (no graphics at
    all), or ``empty`` (nothing extractable). The verdict is counted from
    per-page facts; no geometric or semantic interpretation happens here.
    """

    source: str
    page_count: int
    route: str
    metadata: dict[str, Any]
    fonts: list[str]
    pages: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path, *, indent: int = 2) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=indent), encoding="utf-8")
        return output


def _page_route(path_count: int, image_count: int, text_count: int) -> str:
    if path_count > 0 and image_count == 0:
        return "vector"
    if path_count == 0 and image_count > 0:
        return "raster"
    if path_count > 0 and image_count > 0:
        return "mixed"
    if text_count > 0:
        return "text_only"
    return "empty"


def _summarize_page(document: pymupdf.Document, page: int) -> dict[str, Any]:
    pymupdf_page = document[page]
    words = pymupdf_page.get_text("words")
    drawings = pymupdf_page.get_drawings()
    images = pymupdf_page.get_images(full=True)

    primitive_count = 0
    primitive_kinds: dict[str, int] = {}
    stroke_colors: dict[str, int] = {}
    fill_colors: dict[str, int] = {}
    for drawing in drawings:
        stroke = color_to_hex(drawing.get("color"))
        fill = color_to_hex(drawing.get("fill"))
        if stroke is not None:
            stroke_colors[stroke] = stroke_colors.get(stroke, 0) + 1
        if fill is not None:
            fill_colors[fill] = fill_colors.get(fill, 0) + 1
        for item in drawing["items"]:
            primitive_count += 1
            kind = item_kind(item[0])
            primitive_kinds[kind] = primitive_kinds.get(kind, 0) + 1

    fonts = sorted({entry[3] for entry in pymupdf_page.get_fonts()})
    return {
        "index": page,
        "width_pt": float(pymupdf_page.rect.width),
        "height_pt": float(pymupdf_page.rect.height),
        "rotation": int(pymupdf_page.rotation),
        "text_object_count": len(words),
        "image_count": len(images),
        "vector": {
            "path_count": len(drawings),
            "primitive_count": primitive_count,
            "primitive_kinds": primitive_kinds,
            "stroke_colors": stroke_colors,
            "fill_colors": fill_colors,
        },
        "fonts": fonts,
        "route": _page_route(len(drawings), len(images), len(words)),
    }


def inspect_drawing_rsummary(path: str | Path) -> DrawingSummary:
    """Summarize one PDF drawing document and recommend an analysis route.

    Collects per-page facts only: display-space size and stored rotation,
    text object counts, vector path/primitive counts with kind and color
    census, embedded image counts, document metadata, and font names. The
    ``route`` verdict decides whether the drawing can be mined as vector
    evidence or only read through rendered views; a ``mixed`` or ``raster``
    verdict means measured claims are not available from the file alone.
    """
    source = Path(path)
    with pymupdf.open(source) as document:
        pages = [_summarize_page(document, index) for index in range(len(document))]
        metadata = {
            key: value
            for key, value in (document.metadata or {}).items()
            if value not in (None, "")
        }

    routes = {page["route"] for page in pages}
    route = routes.pop() if len(routes) == 1 else "mixed"

    return DrawingSummary(
        source=str(source),
        page_count=len(pages),
        route=route,
        metadata=metadata,
        fonts=sorted({font for page in pages for font in page["fonts"]}),
        pages=pages,
    )

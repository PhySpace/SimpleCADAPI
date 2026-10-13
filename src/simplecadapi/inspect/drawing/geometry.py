"""Vector primitive extraction: the measurement ground truth of a drawing."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    import pymupdf
else:
    from ._pymupdf import pymupdf

from ._pdf import color_to_hex, item_kind, open_page, parse_color, point_to_display
from ._provenance import page_metadata


@dataclass(frozen=True)
class DrawingStrokes:
    """Normalized path primitives of one page in display space.

    ``strokes`` are flattened one entry per path item: ``line`` carries two
    endpoints, ``bezier`` carries all four control points (first and last are
    on-curve), ``quad`` carries the four corners in perimeter order, ``rect``
    carries four corners in perimeter order. ``total_primitives`` counts every item on
    the page; ``matched`` counts the entries that survived the filters. Only
    verified vector coordinates support calibrated measurements; coordinate
    preflight and feature-association checks are still required.
    """

    source: str
    page: int
    rotation: int
    width_pt: float
    height_pt: float
    total_primitives: int
    matched: int
    strokes: list[dict[str, Any]]
    stroke_color_census: dict[str, int]
    fill_color_census: dict[str, int]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path, *, indent: int = 2) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=indent), encoding="utf-8")
        return output


def _stroke_box(points: Sequence[Sequence[float]]) -> pymupdf.Rect:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))


def _item_points(item: tuple, matrix: pymupdf.Matrix) -> list[list[float]] | None:
    kind = item[0]
    if kind == "l":
        points = item[1:3]
    elif kind == "c":
        points = item[1:5]
    elif kind == "qu":
        quad = item[1]
        points = [quad.ul, quad.ur, quad.lr, quad.ll]
    elif kind == "re":
        rect = item[1]
        points = [rect.tl, rect.tr, rect.br, rect.bl]
    else:
        return None
    return [point_to_display(point, matrix) for point in points]


def extract_drawing_primitives_rstrokes(
    path: str | Path,
    page: int = 0,
    *,
    rect: Sequence[float] | None = None,
    color: str | Sequence[float] | None = None,
    fill: str | Sequence[float] | None = None,
    kinds: Sequence[str] | None = None,
) -> DrawingStrokes:
    """Extract the vector primitives of one page in display-space coordinates.

    Vector coordinates are measurement evidence after coordinate preflight
    and feature-association checks. All coordinates are
    mapped through the page rotation matrix, so distances measured here are
    directly comparable with annotation anchors and rendered views. Filter
    per view with ``rect`` (display-space ``[x0, y0, x1, y1]``) — large
    drawings carry tens of thousands of primitives and unfiltered dumps are
    unusable. ``color`` matches the stroke color, ``fill`` the fill color
    (either as ``"#rrggbb"`` or 0-1 RGB floats); run with no filters first
    and read the color census to discover what exists (hatch fills, axis
    lines) before narrowing. Color semantics are per-drawing conventions:
    the census reports facts, assigning meaning ("this red line is a hole
    axis") is the caller's job. ``kinds`` selects among ``line``, ``bezier``,
    ``quad``, ``rect``.
    Rectangles now carry four perimeter corners (result version 2.0). Region
    filtering is inclusive bounding-box overlap, not exact curve clipping;
    Bezier boxes bound control points. IDs refer to unfiltered page item order.
    Metadata includes SHA-256, page/rotation/MediaBox/CropBox, pt units and version.
    """
    wanted_color = parse_color(color) if color is not None else None
    wanted_fill = parse_color(fill) if fill is not None else None
    wanted_kinds = set(kinds) if kinds is not None else None
    if rect is not None and (
        len(rect) != 4 or rect[0] >= rect[2] or rect[1] >= rect[3]
    ):
        raise ValueError("rect must be [x0, y0, x1, y1] with x1 > x0, y1 > y0")
    filter_rect = (
        pymupdf.Rect(rect[0], rect[1], rect[2], rect[3]) if rect is not None else None
    )

    source = Path(path)
    document, pymupdf_page = open_page(source, page)
    try:
        matrix = pymupdf_page.rotation_matrix
        strokes: list[dict[str, Any]] = []
        total = 0
        stroke_census: dict[str, int] = {}
        fill_census: dict[str, int] = {}

        for drawing in pymupdf_page.get_drawings():
            stroke = color_to_hex(drawing.get("color"))
            fill_hex = color_to_hex(drawing.get("fill"))
            if stroke is not None:
                stroke_census[stroke] = stroke_census.get(stroke, 0) + 1
            if fill_hex is not None:
                fill_census[fill_hex] = fill_census.get(fill_hex, 0) + 1
            width = drawing.get("width")
            dashes = drawing.get("dashes")
            for item in drawing["items"]:
                total += 1
                kind = item_kind(item[0])
                if wanted_kinds is not None and kind not in wanted_kinds:
                    continue
                if wanted_color is not None and stroke != wanted_color:
                    continue
                if wanted_fill is not None and fill_hex != wanted_fill:
                    continue
                raw_points = _item_points(item, matrix)
                if raw_points is None:
                    continue
                box = _stroke_box(raw_points)
                # Rect.intersects rejects degenerate line boxes. Use inclusive
                # AABB overlap, also for Bezier control hulls (not curve clipping).
                if filter_rect is not None and (
                    box.x1 < filter_rect.x0
                    or box.x0 > filter_rect.x1
                    or box.y1 < filter_rect.y0
                    or box.y0 > filter_rect.y1
                ):
                    continue
                strokes.append(
                    {
                        "id": total - 1,
                        "path_id": drawing.get("seqno"),
                        "kind": kind,
                        "points": raw_points,
                        "box": [box.x0, box.y0, box.x1, box.y1],
                        "stroke": stroke,
                        "fill": fill_hex,
                        "width": float(width) if width is not None else None,
                        "dashes": dashes,
                    }
                )
        return DrawingStrokes(
            source=str(source),
            page=page,
            rotation=int(pymupdf_page.rotation),
            width_pt=float(pymupdf_page.rect.width),
            height_pt=float(pymupdf_page.rect.height),
            total_primitives=total,
            matched=len(strokes),
            strokes=strokes,
            stroke_color_census=stroke_census,
            fill_color_census=fill_census,
            metadata=page_metadata(source, pymupdf_page),
        )
    finally:
        document.close()

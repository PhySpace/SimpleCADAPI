"""Shared PDF access helpers for the drawing inspection namespace.

Every public function in this package reports geometry in *display space*:
the coordinate system of the page as a reader sees it, matching
``page.rect`` and the pixels of a rendered PNG. PDF pages may carry a stored
rotation (e.g. landscape drawings saved with ``/Rotate 270``); PyMuPDF's
text-extraction and drawing-extraction interfaces then return coordinates in
the *unrotated* storage space, so every box and point is mapped through
``page.rotation_matrix`` exactly once before it leaves this package.
Render clips are taken in display space, which keeps annotation coordinates,
vector coordinates, and rendered pixels mutually consistent for calibration.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import pymupdf
else:
    from ._pymupdf import pymupdf

_ITEM_KINDS = {"l": "line", "c": "bezier", "qu": "quad", "re": "rect"}


def open_page(path: str | Path, page: int) -> tuple[pymupdf.Document, pymupdf.Page]:
    """Open ``path`` and return ``(document, page)`` with range validation."""
    document = pymupdf.open(path)
    if page < 0 or page >= len(document):
        page_count = len(document)
        document.close()
        raise ValueError(
            f"page index {page} out of range for {path} ({page_count} pages)"
        )
    return document, document[page]


def item_kind(raw: str) -> str:
    """Map a PyMuPDF path-item tag to a stable public kind name."""
    return _ITEM_KINDS.get(raw, "other")


def point_to_display(point: pymupdf.Point, matrix: pymupdf.Matrix) -> list[float]:
    """Map one storage-space point to display space as ``[x, y]``."""
    mapped = point * matrix
    return [mapped.x, mapped.y]


def box_to_display(box: Sequence[float], matrix: pymupdf.Matrix) -> list[float]:
    """Map one storage-space ``[x0, y0, x1, y1]`` box to display space."""
    mapped = pymupdf.Rect(box) * matrix
    return [mapped.x0, mapped.y0, mapped.x1, mapped.y1]


def color_to_hex(value: object) -> str | None:
    """Normalize a PyMuPDF stroke/fill color (``None`` or RGB floats) to hex."""
    if value is None:
        return None
    channels = tuple(float(component) for component in value)
    if len(channels) == 1:
        channels = (channels[0], channels[0], channels[0])
    if len(channels) != 3:
        return None
    return "#{:02x}{:02x}{:02x}".format(
        *(min(255, max(0, int(round(component * 255)))) for component in channels)
    )


def parse_color(value: str | Sequence[float]) -> str:
    """Accept ``"#rrggbb"`` or 0-1 RGB floats and return normalized hex."""
    if isinstance(value, str):
        text = value.strip().lower()
        if len(text) == 4 and text.startswith("#"):
            text = "#" + "".join(character * 2 for character in text[1:])
        if len(text) != 7 or not text.startswith("#"):
            raise ValueError(f"color must be '#rrggbb' or RGB floats, got {value!r}")
        int(text[1:], 16)
        return text
    normalized = color_to_hex(value)
    if normalized is None:
        raise ValueError(f"color must be '#rrggbb' or RGB floats, got {value!r}")
    return normalized

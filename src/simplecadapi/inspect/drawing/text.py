"""Text-layer extraction with display-space coordinates and annotation clustering."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pymupdf
else:
    from ._pymupdf import pymupdf

from ._pdf import box_to_display, open_page
from ._provenance import page_metadata


@dataclass(frozen=True)
class DrawingText:
    """All text objects of one page plus proximity clusters.

    Word and cluster boxes are in display space (matching ``page.rect`` and
    the image after the explicit pt-to-px transform). Clusters are proximity
    combination candidates, not verified tolerance stacks or feature mappings.
    Original word objects and display-space directions are preserved. Metadata
    supplies source hash, zero-based page, rotation, page boxes, units and version.
    """

    source: str
    page: int
    rotation: int
    width_pt: float
    height_pt: float
    words: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path, *, indent: int = 2) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=indent), encoding="utf-8")
        return output

    def cluster_box(self, cluster_id: int) -> list[float]:
        """Return the display-space box of one cluster by its id."""
        for cluster in self.clusters:
            if cluster["id"] == cluster_id:
                return list(cluster["box"])
        raise ValueError(f"unknown cluster id {cluster_id}")


def _cluster_words(words: list[dict[str, Any]], gap_pt: float) -> list[dict[str, Any]]:
    """Group words whose boxes, expanded by ``gap_pt``, intersect."""
    count = len(words)
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    boxes = [pymupdf.Rect(word["box"]) for word in words]
    expanded = [
        pymupdf.Rect(box.x0 - gap_pt, box.y0 - gap_pt, box.x1 + gap_pt, box.y1 + gap_pt)
        for box in boxes
    ]
    for left in range(count):
        for right in range(left + 1, count):
            if expanded[left].intersects(expanded[right]):
                union(left, right)

    groups: dict[int, list[int]] = {}
    for index in range(count):
        groups.setdefault(find(index), []).append(index)

    clusters: list[dict[str, Any]] = []
    for cluster_id, (root, members) in enumerate(
        sorted(groups.items(), key=lambda item: item[1][0])
    ):
        ordered = sorted(
            members, key=lambda index: (words[index]["box"][1], words[index]["box"][0])
        )
        box = boxes[members[0]]
        for index in members[1:]:
            box |= boxes[index]
        clusters.append(
            {
                "id": cluster_id,
                "box": [box.x0, box.y0, box.x1, box.y1],
                "members": [words[index]["id"] for index in ordered],
                "text": " ".join(words[index]["text"] for index in ordered),
                "status": "combination_candidate",
                "association_status": "unresolved",
            }
        )
    return clusters


def extract_drawing_text_rwords(
    path: str | Path,
    page: int = 0,
    *,
    cluster_gap_pt: float = 2.5,
) -> DrawingText:
    """Extract every text object of one page in display-space coordinates.

    Word boxes are mapped through the page rotation matrix, so they line up
    with rendered views and with :func:`extract_drawing_primitives_rstrokes`
    output after coordinate preflight. ``cluster_gap_pt`` controls proximity
    combination candidates; it cannot confirm tolerance stacks or feature
    assignment. Pass ``cluster_gap_pt=0`` for bare words. Metadata includes source
    hash/page/rotation/MediaBox/CropBox/space/units/result version. Each word keeps
    its original object and display-space direction vector.
    The text layer is the complete "what exists on the sheet" inventory, but
    reading order is not visual order: never read dimensions from this layer
    alone, confirm attachment on a rendered view.
    """
    if cluster_gap_pt < 0:
        raise ValueError("cluster_gap_pt must be non-negative")

    source = Path(path)
    document, pymupdf_page = open_page(source, page)
    try:
        matrix = pymupdf_page.rotation_matrix
        raw_words = pymupdf_page.get_text("words")
        directions = {
            (block["number"], line_index): line["dir"]
            for block in pymupdf_page.get_text("dict")["blocks"]
            if block["type"] == 0
            for line_index, line in enumerate(block["lines"])
        }
        metadata = page_metadata(source, pymupdf_page)
        rotation = int(pymupdf_page.rotation)
        width_pt = float(pymupdf_page.rect.width)
        height_pt = float(pymupdf_page.rect.height)
    finally:
        document.close()

    def direction(raw):
        dx, dy = directions[(int(raw[5]), int(raw[6]))]
        return [dx * matrix.a + dy * matrix.c, dx * matrix.b + dy * matrix.d]

    words = [
        {
            "id": index,
            "text": raw[4],
            "box": box_to_display(raw[:4], matrix),
            "block": int(raw[5]),
            "line": int(raw[6]),
            "word": int(raw[7]),
            "raw_object": list(raw),
            "direction": direction(raw),
            "page": page,
            "coordinate_space": "page_display",
            "units": "pt",
            "source_id": metadata["source_id"],
        }
        for index, raw in enumerate(raw_words)
    ]
    clusters = (
        _cluster_words(words, cluster_gap_pt) if cluster_gap_pt > 0 and words else []
    )
    for cluster in clusters:
        cluster.update(
            {k: metadata[k] for k in ("source_id", "page", "coordinate_space", "units")}
        )

    return DrawingText(
        source=str(source),
        page=page,
        rotation=rotation,
        width_pt=width_pt,
        height_pt=height_pt,
        words=words,
        clusters=clusters,
        metadata=metadata,
    )

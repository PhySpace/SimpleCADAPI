"""Section annotation layout and auditable leader/text geometry."""

import math

from ._pymupdf import pymupdf
from ._provenance import digest

COLOR = (0.0, 0.0, 0.75)
FONT_SIZE = 8.0
LINE_HEIGHT = 11.0


def label_rows(dimensions):
    rows = []
    top = 16.0
    for index, dimension in enumerate(dimensions):
        value = dimension.get("measured")
        decimals = dimension.get("display_decimals", 2)
        if not isinstance(decimals, int) or not 0 <= decimals <= 12:
            raise ValueError("display_decimals must be an integer from 0 to 12")
        label = str(dimension.get("dim_id", f"DIM-{index:03d}"))
        if value is not None:
            if not math.isfinite(float(value)):
                raise ValueError("annotated value must be finite")
            label += f": {value:.{decimals}f}"
        lines = [label]
        if dimension.get("feature_id"):
            lines.append(f"feature: {dimension['feature_id']}")
        if dimension.get("nominal") is not None:
            lines.append(
                f"sheet: {dimension['nominal']} {dimension.get('tol') or ''}".rstrip()
            )
        fontname = "china-s" if any(ord(c) > 255 for t in lines for c in t) else "helv"
        width = max(
            pymupdf.get_text_length(t, fontname=fontname, fontsize=FONT_SIZE)
            for t in lines
        )
        rows.append(
            {
                "lines": lines,
                "width": width,
                "top": top,
                "height": len(lines) * LINE_HEIGHT,
                "display_decimals": decimals,
                "fontname": fontname,
            }
        )
        top += len(lines) * LINE_HEIGHT + 14.0
    return rows, max((r["width"] for r in rows), default=0.0) + 40, top + 16


def draw_annotations(page, dimensions, rows, geometry_width, project, binding_report):
    records = []
    checked = {d["dim_id"]: d for d in (binding_report or {}).get("dimensions", [])}
    # Align each label with its anchor, then resolve vertical collisions in
    # anchor order. Reserve space for all remaining rows before placing one.
    desired = [
        (
            project(d["anchor"])[1] - r["height"] / 2
            if d.get("anchor") is not None
            else r["top"]
        )
        for d, r in zip(dimensions, rows)
    ]
    order = sorted(range(len(rows)), key=lambda i: desired[i])
    cursor = 16.0
    remaining = sum(rows[i]["height"] + 14 for i in order)
    for i in order:
        row = rows[i]
        row["top"] = max(cursor, min(desired[i], page.rect.height - remaining))
        cursor = row["top"] + row["height"] + 14
        remaining -= row["height"] + 14
    for dimension, row in zip(dimensions, rows):
        font = pymupdf.Font(row["fontname"])
        left, top = geometry_width + 20, row["top"]
        baseline = top + font.ascender * FONT_SIZE
        box = [
            left,
            top,
            left + row["width"],
            baseline
            + (len(row["lines"]) - 1) * LINE_HEIGHT
            - font.descender * FONT_SIZE,
        ]
        anchor = dimension.get("anchor")
        path = []
        if anchor is not None:
            if len(anchor) != 2 or not all(math.isfinite(float(v)) for v in anchor):
                raise ValueError("anchor must be a finite 2D point")
            anchor_canvas = list(project(anchor))
            path = [
                anchor_canvas,
                [geometry_width + 8, (box[1] + box[3]) / 2],
                [left - 3, (box[1] + box[3]) / 2],
            ]
            for a, b in zip(path, path[1:]):
                page.draw_line(a, b, color=COLOR, width=0.6)
            page.draw_circle(anchor_canvas, 1.5, color=COLOR, width=0.6)
        else:
            anchor_canvas = None
        for index, line in enumerate(row["lines"]):
            page.insert_text(
                (left, baseline + index * LINE_HEIGHT),
                line,
                fontsize=FONT_SIZE,
                fontname=row["fontname"],
                color=COLOR,
            )
        binding = checked.get(dimension.get("dim_id"), {})
        records.append(
            {
                **dict(dimension),
                "annotation_id": digest(dimension),
                "unrounded_value": dimension.get("measured"),
                "display_text": row["lines"],
                "display_decimals": row["display_decimals"],
                "fontname": row["fontname"],
                "anchor_kind": (
                    "placeholder"
                    if anchor is None
                    else dimension.get("anchor_kind", "caller_unverified")
                ),
                "anchor_canvas_pt": anchor_canvas,
                "text_box_pt": box,
                "text_positions_pt": [
                    [left, baseline + i * LINE_HEIGHT] for i in range(len(row["lines"]))
                ],
                "leader_path_pt": path,
                "association_status": binding.get("status", "unverified"),
            }
        )
    clipped = [
        r.get("dim_id")
        for r in records
        if not page.rect.contains(pymupdf.Rect(r["text_box_pt"]))
    ]
    overlaps = [
        [a.get("dim_id"), b.get("dim_id")]
        for i, a in enumerate(records)
        for b in records[i + 1 :]
        if pymupdf.Rect(a["text_box_pt"]).intersects(pymupdf.Rect(b["text_box_pt"]))
    ]
    return records, {
        "text_clipped": clipped,
        "text_overlaps": overlaps,
        "automatic_status": "passed" if not clipped and not overlaps else "failed",
        "readability_review": "pending",
        "feature_association_review": "pending",
        "leader_path_review": "pending",
    }

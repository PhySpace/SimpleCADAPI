"""dxf_engine.sheet — the sheet itself: format, frame, title block, notes area, standard scales, view arrangement.

GB/T 14689 (sheet sizes and frame, with a binding edge) · GB/T 14690 (scales) · GB/T 10609.1 (title block, simplified).
Everything here is in sheet millimetres.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

FORMATS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0),
           "A1": (841.0, 594.0), "A0": (1189.0, 841.0)}
STD_SCALES = (10.0, 5.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01)    # GB/T 14690, first series
DIM_MARGIN = 22.0          # room kept around the views: a row of dimensions and a second row's figures
TITLE_W, TITLE_H = 180.0, 56.0


@dataclass(frozen=True)
class SheetFormat:
    name: str
    w: float
    h: float
    frame: tuple           # x0, y0, x1, y1
    title: tuple
    notes: tuple

    @property
    def free(self):
        """The area views and their dimensions may use: inside the frame, above the title block and the notes."""
        y0 = max(self.title[3], self.notes[3]) + 4.0
        return (self.frame[0] + 2.0, y0, self.frame[2] - 2.0, self.frame[3] - 2.0)


PARAM_COL = 38.0           # width of one column of the parameter table


def param_cols(width):
    return max(1, int((width - 6.0) // PARAM_COL))


def notes_height(n_notes, n_params, width):
    """Height the notes area needs for its content (0 when there is none)."""
    h = 0.0
    if n_notes:
        h += 4.6 + 4.2 * n_notes + 6.0
    if n_params:
        h += 4.6 + 3.4 * math.ceil(n_params / param_cols(width)) + 3.0
    return h + 5.0 if h else 0.0


def sheet_format(name="A3", notes_zone=None, n_notes=0, n_params=0):
    """The sheet. The notes area is as high as the declared notes and parameters need, unless `notes_zone` fixes it."""
    if name not in FORMATS:
        raise ValueError(f"sheet is one of {', '.join(FORMATS)}, got {name!r}")
    w, h = FORMATS[name]
    c = 5.0 if name in ("A3", "A4") else 10.0
    frame = (25.0, c, w - c, h - c)
    title = (frame[2] - TITLE_W, frame[1], frame[2], frame[1] + TITLE_H)
    notes = tuple(notes_zone) if notes_zone else (
        frame[0], frame[1], title[0] - 3.0, frame[1] + notes_height(n_notes, n_params, title[0] - 3.0 - frame[0]))
    return SheetFormat(name, w, h, frame, title, notes)


def scale_text(s):
    """0.5 → "1 : 2", 2 → "2 : 1"."""
    if s >= 1.0:
        return f"{s:g} : 1"
    return f"1 : {1.0 / s:g}"


def arrange(views, front, scale):
    """Origins of the views for a front view at (0, 0).

    views: {name: (local bbox x0, y0, x1, y1 in model units, align dict)} in solving order (front first).
    `gap` is the clear distance between two views on the sheet. Returns ({name: (ox, oy)}, {name: how})."""
    pos, how, box = {front: (0.0, 0.0)}, {front: "front view"}, {}

    def sheet_box(name):
        ox, oy = pos[name]
        b = views[name][0]
        return (ox + b[0] * scale, oy + b[1] * scale, ox + b[2] * scale, oy + b[3] * scale)

    box[front] = sheet_box(front)
    for name, (b, align) in views.items():
        if name == front:
            continue
        if not align or align.get("to") not in pos:
            raise ValueError(f"view {name!r}: align={{'to': <a view declared before it>, 'side': below|right|above|left, "
                             f"'gap': mm}} is required for every view but the front view")
        base, side, gap = align["to"], align.get("side", "below"), float(align.get("gap", 20.0))
        bx0, by0, bx1, by1 = box[base]
        box_o = pos[base]
        if side == "below":
            pos[name] = (box_o[0], by0 - gap - b[3] * scale)
            how[name] = f"length-aligned below {base}, gap {gap:g}"
        elif side == "above":
            pos[name] = (box_o[0], by1 + gap - b[1] * scale)
            how[name] = f"length-aligned above {base}, gap {gap:g}"
        elif side == "right":
            pos[name] = (bx1 + gap - b[0] * scale, box_o[1])
            how[name] = f"height-aligned right of {base}, gap {gap:g}"
        elif side == "left":
            pos[name] = (bx0 - gap - b[2] * scale, box_o[1])
            how[name] = f"height-aligned left of {base}, gap {gap:g}"
        else:
            raise ValueError(f"view {name!r}: align side is below, right, above or left, got {side!r}")
        box[name] = sheet_box(name)
    return pos, how, box


def _union(boxes):
    bs = list(boxes)
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def choose_scale(views, front, fmt):
    """The largest standard scale at which the views and DIM_MARGIN around them fit the free area."""
    fx0, fy0, fx1, fy1 = fmt.free
    for s in STD_SCALES:
        _pos, _how, box = arrange(views, front, s)
        u = _union(box.values())
        if (u[2] - u[0] + 2 * DIM_MARGIN <= fx1 - fx0) and (u[3] - u[1] + 2 * DIM_MARGIN <= fy1 - fy0):
            return s
    return STD_SCALES[-1]


def centre_anchor(views, front, scale, fmt):
    """The front view's origin that centres the whole arrangement in the free area."""
    _pos, _how, box = arrange(views, front, scale)
    u = _union(box.values())
    fx0, fy0, fx1, fy1 = fmt.free
    return ((fx0 + fx1) / 2 - (u[0] + u[2]) / 2, (fy0 + fy1) / 2 - (u[1] + u[3]) / 2)


# ---------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------

def _rect(msp, b, layer):
    msp.add_lwpolyline([(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])], close=True,
                       dxfattribs={"layer": layer})


def draw_frame(msp, plan):
    """Frame and title block. An empty title-block field stays empty: nothing is filled in that was not declared."""
    fmt, d = plan.fmt, plan.d
    _rect(msp, fmt.frame, "01_THICK_SOLID")
    tb = fmt.title
    _rect(msp, tb, "01_THICK_SOLID")
    y0 = tb[1]
    for dy in (14.0, 28.0, 42.0):
        msp.add_line((tb[0], y0 + dy), (tb[2], y0 + dy), dxfattribs={"layer": "01_THIN_SOLID"})
    xm = tb[0] + 95.0
    msp.add_line((xm, tb[1]), (xm, tb[3]), dxfattribs={"layer": "01_THIN_SOLID"})

    def cell(label, value, x, y, h=3.2):
        msp.add_text(label, dxfattribs={"layer": "TEXT", "style": "CJK", "height": 2.4}
                     ).set_placement((x + 1.5, y + 9.5))
        if value:
            msp.add_text(value, dxfattribs={"layer": "TEXT", "style": "CJK", "height": h}
                         ).set_placement((x + 1.5, y + 4.0))

    from ezdxf.enums import TextEntityAlignment
    msp.add_text(d.title, dxfattribs={"layer": "TEXT", "style": "CJK", "height": 4.5}
                 ).set_placement(((tb[0] + xm) / 2, y0 + 49.0), align=TextEntityAlignment.MIDDLE_CENTER)
    cell("DESIGN", d.designer, tb[0], y0 + 28.0)
    cell("DWG NO.", d.dwg_no, xm, y0 + 28.0)
    cell("SCALE", scale_text(plan.s), tb[0], y0 + 14.0)
    cell("UNIT", "mm · GB first-angle", tb[0] + 45.0, y0 + 14.0)
    cell("MATERIAL", d.material, xm, y0 + 14.0)
    cell("DATE", time.strftime("%Y-%m-%d"), tb[0], y0)
    cell("REV", d.revision, tb[0] + 45.0, y0)
    cell("SHEET", f"1 / 1 · {fmt.name}", xm, y0)


def draw_notes(msp, plan):
    """Technical requirements and the parameter table, in the notes area."""
    d, nz = plan.d, plan.fmt.notes
    x, ny = nz[0] + 3.0, nz[3] - 5.0
    if d.notes:
        msp.add_text("NOTES:", dxfattribs={"layer": "TEXT", "style": "CJK", "height": 3.0}).set_placement((x, ny))
        ny -= 4.6
        for line in d.notes:
            msp.add_text(line, dxfattribs={"layer": "TEXT", "style": "CJK", "height": 2.2}).set_placement((x, ny))
            ny -= 4.2
        ny -= 6.0
    keys = list(d.params.keys())
    if not keys:
        return
    msp.add_text("PARAMETERS:", dxfattribs={"layer": "TEXT", "style": "CJK", "height": 3.0}).set_placement((x, ny))
    ny -= 4.6
    rows = math.ceil(len(keys) / param_cols(nz[2] - nz[0]))
    col_w = PARAM_COL
    for i, k in enumerate(keys):
        col, row = i // rows, i % rows
        v = d.params[k]
        vs = f"{v:g}" if isinstance(v, float) else str(v)
        msp.add_text(f"{k}={vs}", dxfattribs={"layer": "TEXT", "style": "CJK", "height": 2.0}
                     ).set_placement((x + col * col_w, ny - row * 3.4))

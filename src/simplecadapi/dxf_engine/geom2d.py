"""dxf_engine.geom2d — plane geometry of the sheet: boxes, rotated text boxes, segment tests, text width.

Rotated text collides through an OBB (separating-axis test), not a rough AABB. Sheet millimetres throughout.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

DIM_TXT, DIM_ASZ, DIM_EXO, DIM_EXE, DIM_GAP = 3.5, 3.0, 0.75, 2.0, 0.8
TEXT_H = DIM_TXT
ROW_PITCH, BASE_OFF = 11.0, 8.0
TOL_H = 0.6               # height of a stacked tolerance, as a fraction of the text height
TOL_GAP = 0.6             # mm between the number and its stacked tolerance


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def overlaps(self, b: "Box") -> bool:
        return not (self.x1 < b.x0 or self.x0 > b.x1 or
                    self.y1 < b.y0 or self.y0 > b.y1)

    def inflate(self, d: float) -> "Box":
        return Box(self.x0 - d, self.y0 - d, self.x1 + d, self.y1 + d)


def _cjk_font_name() -> str:
    import glob
    import os

    pats = ["/System/Library/Fonts/*PingFang*", "/System/Library/Fonts/Supplemental/*",
            "/System/Library/Fonts/*", "/Library/Fonts/*.ttf",
            "C:/Windows/Fonts/sim*.tt?", "C:/Windows/Fonts/msyh*"]
    want = ("pingfang", "songti", "stheiti", "hiragino", "simsun", "simhei",
            "msyh", "arial unicode")
    seen = []
    for pat in pats:
        for f in glob.glob(pat):
            low = os.path.basename(f).lower()
            seen.append(low)
            if any(w in low for w in want) and low.endswith((".ttf", ".ttc", ".otf")):
                return low
    return next(iter(seen), "txt")


_FONT = []


def _font():
    """The font the sheet is lettered in, for measuring (None when it cannot be loaded)."""
    if not _FONT:
        try:
            from ezdxf.fonts import fonts
            _FONT.append(fonts.make_font(_cjk_font_name(), 1.0))
        except Exception:
            _FONT.append(None)
    return _FONT[0]


def _plain_width(text, h):
    """Width of a single-line text of cap height h, measured in the sheet's font: a box that is checked is as wide as
    the text that is drawn. Without the font: an estimate on the wide side."""
    f = _font()
    if f is not None:
        try:
            return f.text_width(text.replace("⌀", "Ø")) * h
        except Exception:
            pass
    return sum(h * (1.4 if ord(ch) > 0x2E80 else 0.78) for ch in text)


def _text_width(text, h=3.5):
    """Width of a text of height h. A stacked tolerance "{+0.021|0}" counts once, at its reduced height."""
    i = text.find("{")
    j = text.find("}", i + 1)
    if i < 0 or j < 0 or "|" not in text[i:j]:
        return _plain_width(text, h)
    up, lo = text[i + 1:j].split("|", 1)
    return (_plain_width(text[:i], h) + TOL_GAP + max(_plain_width(up, h * TOL_H), _plain_width(lo, h * TOL_H))
            + _plain_width(text[j + 1:], h))


def norm_rot(angle_deg):
    """The rotation of a text along a line at angle_deg, never upside down: in (-90, 90]."""
    rot = (angle_deg % 180.0 + 180.0) % 180.0
    return rot - 180.0 if rot > 90.0 else rot


class Geom2D:
    """Static plane-geometry helpers, mixed into SheetPlan (the solver, the evaluation and the tests call them there)."""

    @staticmethod
    def _obb_corners(cx, cy, w, h, rot_deg):
        rr = math.radians(rot_deg)
        ca, sa = math.cos(rr), math.sin(rr)
        hw, hh = w / 2.0, h / 2.0
        return [(cx + ca * sx + sa * sy - sa * 0 - 0, cy + sa * sx - ca * sy)
                for sx, sy in ((hw, hh), (-hw, hh), (-hw, -hh), (hw, -hh))]

    @staticmethod
    def _obb_sat(cx, cy, w, h, rot_deg, box: Box) -> bool:
        """Separating-axis test of a rotated rectangle (OBB) against an axis-aligned box."""
        rr = math.radians(rot_deg)
        ca, sa = math.cos(rr), math.sin(rr)
        axes = ((1.0, 0.0), (0.0, 1.0), (ca, sa), (-sa, ca))
        corners = Geom2D._obb_corners(cx, cy, w, h, rot_deg)
        bxc = [(box.x0, box.y0), (box.x1, box.y0), (box.x1, box.y1), (box.x0, box.y1)]
        for ax, ay in axes:
            ovals = [ (x * ax + y * ay) for x, y in corners ]
            bvals = [ (x * ax + y * ay) for x, y in bxc ]
            if max(ovals) < min(bvals) or min(ovals) > max(bvals):
                return False
        return True

    @staticmethod
    def _pt_in_obb(px, py, cx, cy, w, h, rot_deg, pad=0.6):
        rr = math.radians(rot_deg)
        ca, sa = math.cos(rr), math.sin(rr)
        dx, dy = px - cx, py - cy
        lu, lv = dx * ca + dy * sa, -dx * sa + dy * ca
        return (abs(lu) <= w / 2 + pad) and (abs(lv) <= h / 2 + pad)

    @staticmethod
    def _obb_obb(cx1, cy1, w1, h1, r1, cx2, cy2, w2, h2, r2):
        """Separating-axis test of two rotated rectangles."""
        corners1 = Geom2D._obb_corners(cx1, cy1, w1, h1, r1)
        corners2 = Geom2D._obb_corners(cx2, cy2, w2, h2, r2)
        rr1, rr2 = math.radians(r1), math.radians(r2)
        axes = [(math.cos(rr1), math.sin(rr1)), (-math.sin(rr1), math.cos(rr1)),
                (math.cos(rr2), math.sin(rr2)), (-math.sin(rr2), math.cos(rr2)),
                (1.0, 0.0), (0.0, 1.0)]
        for ax, ay in axes:
            v1 = [x * ax + y * ay for x, y in corners1]
            v2 = [x * ax + y * ay for x, y in corners2]
            if max(v1) < min(v2) or min(v1) > max(v2):
                return False
        return True

    @staticmethod
    def _seg_obb(p, q, cx, cy, w, h, rot_deg):
        n = max(2, int(math.dist(p, q) / 1.5))
        for i in range(n + 1):
            t = i / n
            x = p[0] + (q[0] - p[0]) * t
            y = p[1] + (q[1] - p[1]) * t
            if Geom2D._pt_in_obb(x, y, cx, cy, w, h, rot_deg):
                return True
        return False


    @staticmethod
    def _seg_hits_box(p, q, box: Box, step=1.5):
        b = box.inflate(0.6)
        n = max(2, int(math.dist(p, q) / step))
        for i in range(n + 1):
            t = i / n
            x = p[0] + (q[0] - p[0]) * t
            y = p[1] + (q[1] - p[1]) * t
            if b.x0 <= x <= b.x1 and b.y0 <= y <= b.y1:
                return True
        return False

    @staticmethod
    def _seg_cross(p1, q1, p2, q2):
        l1 = math.dist(p1, q1)
        n = max(2, int(l1 / 2.0))
        for i in range(n + 1):
            t = i / n
            x = p1[0] + (q1[0] - p1[0]) * t
            y = p1[1] + (q1[1] - p1[1]) * t
            b = Box(x - 0.4, y - 0.4, x + 0.4, y + 0.4)
            if Geom2D._seg_hits_box(p2, q2, b, step=1.5):
                return True
        return False

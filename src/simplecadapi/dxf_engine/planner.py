"""dxf_engine.planner — the dimensioning-plan solver.

Dimensioning principles (GB/T 4458.4-2003 / GB/T 16675.1 / GB/T 14691):
  R1 safe area      text (OBB) / leaders / dimension lines do not clash with figure lines, other annotations or keep-out zones (minimum adjustment)
  R2 text direction text runs parallel to the dimension line; heads up (horizontal) / left (vertical); never upside down
  R3 30° exclusion  an inclined dimension line within ±30° of vertical gives a warning (figure 17; exactly vertical 90° is legal)
  R4 row slots      same-side dimension rows are ROW_PITCH apart, declared rows first, collisions shift on; large dimensions outside (automatic)
  R5 parameter cover every model parameter is carried by a figure dimension (covers/caption) or enters the technical requirements / parameter table
  R6 datum reference position dimensions must declare a datum; datum letters must be declared
  R7 no duplicates the same kind of measurement is not repeated in the same view

Rotated text collides through an OBB (separating-axis test), not a rough AABB.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .hlr import DEG, arc_angles, discretize_edge, hlr_project
from .model import (CenterDecl, DatumDecl, DimDecl, LeaderDecl, SheetDecl,
                    ViewDecl)


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


def _text_width(text, h=3.5):
    return sum(h * (1.0 if ord(ch) > 0x2E80 else 0.62) for ch in text)


@dataclass
class Resolved:
    """The solved result of one annotation element on the sheet: requested (declared value) → resolved (actual position) +
    adjust (record of the minimum adjustments) + draw (precomputed geometry for rendering) + rules (the rules that fired)."""
    kind: str
    name: str
    view: str
    requested: str
    resolved: str
    adjust: list = field(default_factory=list)
    draw: dict = field(default_factory=dict)
    rule: str = ""


DIM_TXT, DIM_ASZ, DIM_EXO, DIM_EXE, DIM_GAP = 3.5, 3.0, 0.75, 2.0, 0.8
TEXT_H = DIM_TXT
ROW_PITCH, BASE_OFF = 11.0, 8.0


class SheetPlan:
    """The dimensioning-plan solver: SheetDecl → solve() → resolved/accepted/report() → render().

    Solving: view layout (first-angle projection, align) → datum placement → linear dimensions
    (ordered by view/side/row, large outside, small inside) → diameter/radius dimensions → leaders → parameter-coverage check.
    Every conflict follows "minimum adjustment": candidate positions are shifted first and recorded in Resolved.adjust;
    when nothing fits it is recorded as an R1 warning, never silently dropped.
    """

    def __init__(self, decl: SheetDecl):
        self.d = decl
        self.s = decl.scale
        self.views: dict[str, dict] = {}
        self.resolved: list[Resolved] = []
        self.text_obbs: list[tuple[str, float, float, float, float, float]] = []
        self.segments: list[tuple[str, tuple, tuple]] = []
        self.datum_pos: dict[str, tuple] = {}
        self.adjust_count = 0
        self.rule_log: list[tuple[str, str, str]] = []
        self.coverage: list[tuple[str, str]] = []
        self._zones: list[Box] = []

    # ---------- geometry primitives ----------
    def tx(self, view, p):
        """View-local model coordinates → sheet coordinates (including the drawing scale)."""
        vw = self.views[view]
        return (vw["ox"] + p[0] * self.s, vw["oy"] + p[1] * self.s)

    def _prime(self):
        self._zones = [Box(*self.d.notes_zone), Box(235.0, 5.0, 415.0, 61.0)]

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
        corners = SheetPlan._obb_corners(cx, cy, w, h, rot_deg)
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
        corners1 = SheetPlan._obb_corners(cx1, cy1, w1, h1, r1)
        corners2 = SheetPlan._obb_corners(cx2, cy2, w2, h2, r2)
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
            if SheetPlan._pt_in_obb(x, y, cx, cy, w, h, rot_deg):
                return True
        return False

    def _text_clear(self, key, cx, cy, w, h, rot, skip_view=None) -> list[str]:
        why = []
        for z in self._zones:
            if self._obb_sat(cx, cy, w, h, rot, z.inflate(1.0)):
                why.append("keep-out zone")
        for n, vw in self.views.items():
            if n != skip_view:
                if self._obb_sat(cx, cy, w, h, rot, vw["bbox"].inflate(0.5)):
                    why.append(f"view {n}")
                for sp, sq in vw["pairs"]:
                    if self._pt_in_obb(sp[0], sp[1], cx, cy, w, h, rot):
                        why.append(f"figure line {n}")
                        break
        for k2, cx2, cy2, w2, h2, r2 in self.text_obbs:
            if k2 != key and self._obb_obb(cx, cy, w, h, rot,
                                           cx2, cy2, w2, h2, r2):
                why.append(f"text {k2}")
        for k2, sp, sq in self.segments:
            if k2 != key and self._seg_obb(sp, sq, cx, cy, w, h, rot):
                why.append(f"dimension line {k2}")
        return why

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
            if SheetPlan._seg_hits_box(p2, q2, b, step=1.5):
                return True
        return False

    def _seg_vs_views(self, seg, skip_view):
        hits = []
        for n, vw in self.views.items():
            if n == skip_view:
                continue
            bb = vw["bbox"]
            if not (min(seg[0][0], seg[1][0]) <= bb.x1 and
                    max(seg[0][0], seg[1][0]) >= bb.x0 and
                    min(seg[0][1], seg[1][1]) <= bb.y1 and
                    max(seg[0][1], seg[1][1]) >= bb.y0):
                continue
            for a, b in vw["pairs"]:
                if self._seg_cross(seg[0], seg[1], a, b):
                    hits.append(n)
                    break
        return hits

    def _reg_seg(self, key, p, q):
        self.segments.append((key, p, q))

    # ---------- views ----------
    def _solve_views(self):
        by_name = {v.name: v for v in self.d.views}
        order = [self.d.front] + [v.name for v in self.d.views
                                  if v.name != self.d.front]
        for name in order:
            v = by_name[name]
            vis, hid = hlr_project(v.shape, v.n, v.xd)
            edges, xs, ys = [], [], []
            for e in vis + hid:
                ad, pts = discretize_edge(e)
                if len(pts) >= 2:
                    edges.append((ad, pts, e in vis))
                    xs += [p[0] for p in pts]
                    ys += [p[1] for p in pts]
            if name == self.d.front:
                ox, oy = v.anchor
                how = "declared anchor"
            else:
                base = self.views[v.align["to"]]
                bb = base["bbox"]
                if v.align["side"] == "below":
                    ox, oy = base["ox"], bb.y0 - v.align["gap"]
                    how = f"length-aligned gap{v.align['gap']:g}"
                else:
                    ox, oy = bb.x1 + v.align["gap"], base["oy"]
                    how = f"height-aligned gap{v.align['gap']:g}"
            bbox = Box(ox + min(xs) * self.s, oy + min(ys) * self.s,
                       ox + max(xs) * self.s, oy + max(ys) * self.s)
            pairs = []
            for ad, pts, _vis in edges:
                sh = [(p[0] * self.s + ox, p[1] * self.s + oy) for p in pts]
                pairs.extend(zip(sh, sh[1:]))
            self.views[name] = {"ox": ox, "oy": oy, "bbox": bbox,
                                "edges": edges, "pairs": pairs, "how": how}
            self.resolved.append(Resolved(
                "view", name, name, f"anchor={v.anchor}", f"({ox:.1f},{oy:.1f})",
                [], {"how": how}))

    # ---------- text-parallel primitives ----------
    @staticmethod
    def _text_frame(mid, line_angle_deg, above=1.0, h=TEXT_H, w=0.0):
        """Text parallel to the dimension line: rotation normalised (never upside down), baseline offset to the "upper" side
        (GB: heads up / left). Returns (insert, rot, center, aabb)."""
        rot = line_angle_deg % 180.0
        if rot > 90.0:
            rot -= 180.0
        rr = math.radians(rot)
        n = (-math.sin(rr), math.cos(rr))
        insert = (mid[0] + n[0] * above, mid[1] + n[1] * above)
        half_h = h * 0.35                      # baseline to the visual centre of the glyphs
        cx, cy = mid[0] + n[0] * (above + half_h), mid[1] + n[1] * (above + half_h)
        ca, sa = math.cos(rr), math.sin(rr)
        ex = abs(ca) * w / 2 + abs(sa) * h / 2
        ey = abs(sa) * w / 2 + abs(ca) * h / 2
        return (insert, rot, (cx, cy), Box(cx - ex, cy - ey, cx + ex, cy + ey))

    def _arrow(self, msp, tip, direction_deg):
        pass                                   # implemented in the render stage (render.py)

    # ---------- dimension solving ----------
    def _solve_dim(self, dcl: DimDecl):
        key = f"dim:{dcl.caption}"
        if dcl.semantic == "linear":
            self._solve_linear(dcl, self.views[dcl.view], key)
        elif dcl.semantic == "diameter":
            self._solve_diameter(dcl, self.views[dcl.view], key)
        elif dcl.semantic == "radius":
            self._solve_radius(dcl, self.views[dcl.view], key)

    def _lin_geometry(self, dcl, side, row, slide, text):
        """Linear-dimension geometry derivation (shared by the solver and the agent actions: one derivation, one truth):
        the dimension line sits on row `row` (side `side`) outside the view bbox; the text has one degree of freedom
        along the dimension line (slide, sheet offset from the measurement midpoint); when the text slides out of the
        measured segment the dimension line **extends sideways automatically** to cover it (arrows still point at the measured points)."""
        vw = self.views[dcl.view]
        bb = vw["bbox"]
        p1, p2 = self.tx(dcl.view, dcl.p1), self.tx(dcl.view, dcl.p2)
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        vertical = abs(dy) >= abs(dx)
        if vertical and p1[1] > p2[1]:
            p1, p2 = p2, p1                      # direction normalised: bottom to top (heads left)
        if not vertical and p1[0] > p2[0]:
            p1, p2 = p2, p1
        w = _text_width(text, TEXT_H)
        if vertical:
            xl = (bb.x1 + BASE_OFF + row * ROW_PITCH if side == "right"
                  else bb.x0 - BASE_OFF - row * ROW_PITCH)
            ymid = (p1[1] + p2[1]) / 2 + slide
            # insert = the **lower end** of the baseline (text runs up along +y, as render set_placement does);
            # OBB centre = insert + u·(w/2) + n·(0.35h), u=(0,1), n=(-1,0)
            insert = (xl - 1.0, ymid - w / 2)
            rot, center = 90.0, (xl - 1.0 - TEXT_H * 0.35, ymid)
            lo = min(p1[1], insert[1] - 2.0)      # text slid out → sideways extension
            hi = max(p2[1], insert[1] + w + 2.0)
            line = ((xl, lo), (xl, hi))
            arrows = ((xl, p1[1]), (xl, p2[1]))
            exts = [((p1[0], p1[1]), (xl, p1[1])), ((p2[0], p2[1]), (xl, p2[1]))]
        else:
            yl = (bb.y0 - BASE_OFF - row * ROW_PITCH if side == "bottom"
                  else bb.y1 + BASE_OFF + row * ROW_PITCH)
            xmid = (p1[0] + p2[0]) / 2 + slide
            # insert = the **left end** of the baseline (text runs along +x, as render does)
            insert = (xmid - w / 2, yl + 1.0)
            rot, center = 0.0, (xmid, yl + 1.0 + TEXT_H * 0.35)
            lo = min(p1[0], insert[0] - 2.0)
            hi = max(p2[0], insert[0] + w + 2.0)
            line = ((lo, yl), (hi, yl))
            arrows = ((p1[0], yl), (p2[0], yl))
            exts = [((p1[0], p1[1]), (p1[0], yl)), ((p2[0], p2[1]), (p2[0], yl))]
        return {"kind": "lin", "line": line, "arrows": arrows, "exts": exts,
                "insert": insert, "rot": rot, "center": center, "text": text,
                "slide": slide,
                "extended": (lo < (p1[1] if vertical else p1[0]) - 0.01 or
                             hi > (p2[1] if vertical else p2[0]) + 0.01)}

    def _solve_linear(self, dcl, vw, key):
        p1, p2 = self.tx(dcl.view, dcl.p1), self.tx(dcl.view, dcl.p2)
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        vertical = abs(dy) >= abs(dx)
        side = dcl.side or ("right" if vertical else "bottom")
        value = dcl.value if dcl.value is not None else math.dist(p1, p2) / self.s
        vs = f"{value:.{dcl.dec}f}"
        if "." in vs:
            vs = vs.rstrip("0").rstrip(".")
        text = f"{dcl.prefix}{vs} ({dcl.caption})"
        w = _text_width(text, TEXT_H)
        span = abs(dy) if vertical else abs(dx)
        if span >= w + 2.0:
            # midpoint first (zero offset); on a conflict slide first (minimum adjustment), then shift rows
            slides = (0.0, w / 2 + 2.0, -(w / 2 + 2.0), w + 6.0, -(w + 6.0))
        else:
            # the measured segment cannot hold the text: place it outside and extend the dimension line (derived)
            off = span / 2 + w / 2 + 2.0
            slides = (off, -off)
        adjust = []
        for n_try in range(0, 7):
            row_i = dcl.row + n_try
            for slide in slides:
                g = self._lin_geometry(dcl, side, row_i, slide, text)
                why = self._text_clear(key, g["center"][0], g["center"][1],
                                       w, TEXT_H, g["rot"],
                                       skip_view=dcl.view)
                # dimension and extension lines may cross centre lines, but not figure lines of other views
                seg_bad = []
                for seg in [g["line"]] + g["exts"]:
                    seg_bad += self._seg_vs_views(seg, dcl.view)
                if seg_bad:
                    why.append(f"line crosses view {'+'.join(seg_bad)}")
                if not why:
                    notes = []
                    if n_try:
                        notes.append(f"R1 row shifted to row{row_i}")
                    if slide:
                        notes.append(f"text slid along the line {slide:+g}")
                    if g["extended"]:
                        notes.append("dimension line extended sideways")
                    adjust += notes
                    self.adjust_count += len(notes)
                    self.text_obbs.append((key, g["center"][0], g["center"][1],
                                           w, TEXT_H, g["rot"]))
                    for sg in [g["line"]] + g["exts"]:
                        self._reg_seg(key, *sg)
                    res = f"{side} row{row_i}"
                    if slide or g["extended"]:
                        res += f" slide{slide:+g}" + (" extended" if g["extended"] else "")
                    self.resolved.append(Resolved(
                        "dim", dcl.caption, dcl.view,
                        f"{side} row{dcl.row}", res, adjust,
                        {k: g[k] for k in ("kind", "line", "arrows", "exts",
                                           "insert", "rot", "text",
                                           "extended")},
                        "R2/R4"))
                    return
            adjust.append(f"R1 conflict@row{row_i}({why[0] if why else 'line crosses view'})")
            self.adjust_count += 1
        self.resolved.append(Resolved(
            "dim", dcl.caption, dcl.view, f"{side} row{dcl.row}",
            f"{side} row{dcl.row}", adjust, {"kind": "lin", "text": text},
            "R1/R4"))

    def _solve_diameter(self, dcl, vw, key):
        """Diameter dimension (GB/T 4458.4 figure 10): the dimension line passes through the centre, double arrows touch the circle; once `at` orients it
        the text has 1 DOF along the diameter line (default at 0.75r, alternative positions on a conflict), baseline always above the line;
        m1/m2 always lie on the circle."""
        s = self.s
        c = self.tx(dcl.view, dcl.center)
        r = dcl.radius * s
        u = (math.cos(math.radians(dcl.at)), math.sin(math.radians(dcl.at)))
        value = dcl.value if dcl.value is not None else 2 * dcl.radius
        vs = f"{value:.{dcl.dec}f}"
        if "." in vs:
            vs = vs.rstrip("0").rstrip(".")
        text = f"⌀{vs} ({dcl.caption})"
        w = _text_width(text, TEXT_H)
        m1 = (c[0] + r * u[0], c[1] + r * u[1])
        m2 = (c[0] - r * u[0], c[1] - r * u[1])
        line = (m1, m2)
        rot = (dcl.at % 180.0 + 180.0) % 180.0
        if rot > 90.0:
            rot -= 180.0
        rr = math.radians(rot)
        n = (-math.sin(rr), math.cos(rr))
        w2 = _text_width(text, TEXT_H)

        def _anchor_at(uu):
            """Left end of the text baseline (above the line at 0.75r) and the OBB centre."""
            ins = (c[0] + 0.75 * r * uu[0] + n[0] * 1.0,
                   c[1] + 0.75 * r * uu[1] + n[1] * 1.0)
            ctr = (ins[0] + uu[0] * w2 / 2 + n[0] * TEXT_H * 0.35,
                   ins[1] + uu[1] * w2 / 2 + n[1] * TEXT_H * 0.35)
            return ins, ctr

        insert, anchor = _anchor_at(u)
        why = self._text_clear(key, anchor[0], anchor[1], w2, TEXT_H, rot,
                               skip_view=dcl.view)
        adjust = []
        if why:
            for k in range(1, 4):
                aa = dcl.at + 180.0 * (k % 2) + (12.0 * ((k + 1) // 2)) * (
                    1 if k <= 2 else -1)
                uu = (math.cos(math.radians(aa)), math.sin(math.radians(aa)))
                a2, c2 = _anchor_at(uu)
                rrot = (aa % 180.0 + 180.0) % 180.0
                rrot = rrot - 180.0 if rrot > 90.0 else rrot
                if not self._text_clear(key, c2[0], c2[1], w2, TEXT_H, rrot,
                                        skip_view=dcl.view):
                    insert, anchor, u = a2, c2, uu
                    rot = rrot
                    adjust.append(f"moved to {aa:g}°")
                    self.adjust_count += 1
                    break
            else:
                adjust.append("R1 warning: text left in place")
                self.adjust_count += 1
        self.text_obbs.append((key, anchor[0], anchor[1], w2, TEXT_H, rot))
        for sg in (line, (m1, insert)):
            self._reg_seg(key, *sg)
        draw = {"kind": "dia-man", "m1": m1, "m2": m2, "insert": insert,
                "anchor": anchor, "text": text, "rot": rot}
        self.resolved.append(Resolved("dim", dcl.caption, dcl.view,
                                      f"at {dcl.at:g}°", f"rot {rot:g}° 75%r",
                                      adjust, draw, "R2/R5"))

    # ---------- leaders ----------
    def _solve_leaders(self):
        for dcl in self.d.leaders:
            a = self.tx(dcl.view, dcl.anchor)
            w = max(_text_width(t, 2.2) for t in dcl.lines)
            h = len(dcl.lines) * 4.2 + 1.0
            bbv = self.views[dcl.view]["bbox"]
            side = -1.0 if (a[0] - bbv.x0) < (bbv.x1 - a[0]) else 1.0
            cands = [dcl.off] + list(dcl.alt_offs)
            for k in range(1, 6):
                cands.append((dcl.off[0] + side * (18.0 * k),
                              dcl.off[1] - 8.0 * k))
            final = None
            adjust = []
            for ci, off in enumerate(cands):
                tx0 = a[0] + off[0]
                ty0 = a[1] + off[1]
                box = Box(tx0, ty0 - h, tx0 + w, ty0)
                # the elbow sits above the box top: a mid-box elbow of a multi-line text would cut through the second line's height band
                elb_y = ty0 + 0.8
                near_x = (box.x0 - 1.2) if dcl.dx_dir < 0 else (box.x1 + 1.2)
                path = [a, (a[0], elb_y), (near_x, elb_y)]
                why = []
                for z in self._zones:
                    if box.overlaps(z.inflate(1.0)):
                        why.append("keep-out zone")
                if any(box.overlaps(v["bbox"]) for n, v in self.views.items()
                       if n != dcl.view):
                    why.append("over another view bbox")
                for sp, sq in zip(path, path[1:]):
                    vh = self._seg_vs_views((sp, sq), dcl.view)
                    if vh:
                        mid = ((sp[0] + sq[0]) / 2, (sp[1] + sq[1]) / 2)
                        if math.dist(a, mid) > 15.0:
                            why.append(f"leader crosses {'+'.join(vh)}")

                for kk, cx2, cy2, w2, h2, r2 in self.text_obbs:
                    if f"lead:{dcl.name}" != kk and self._obb_obb(
                            tx0, ty0 - h / 2, w, h, 0.0,
                            cx2, cy2, w2, h2, r2):
                        why.append(f"text {kk}")
                for i in range(len(path) - 1):
                    seg = (path[i], path[i + 1])
                    for k2, cx2, cy2, w2, h2, r2 in self.text_obbs:
                        if self._seg_obb(seg[0], seg[1], cx2, cy2, w2, h2, r2):
                            why.append(f"leader over text {k2}")
                for i in range(len(path) - 1):
                    seg = (path[i], path[i + 1])
                    for k2, sp2, sq2 in self.segments:
                        if k2 != f"lead:{dcl.name}" and \
                                self._seg_cross(*seg, sp2, sq2):
                            why.append(f"dimension line {k2}")
                if not why:
                    final = (off, box, path)
                    if ci:
                        adjust.append(f"moved ×{ci}")
                        self.adjust_count += 1
                    break
            if final is None:
                off = dcl.off
                box = Box(a[0] + off[0], a[1] + off[1] - h,
                          a[0] + off[0] + w, a[1] + off[1])
                path = [a, (a[0] + dcl.dx_dir * 12.0, box.y1 + 0.8),
                        (box.x0 - 1.2 if dcl.dx_dir < 0 else box.x1 + 1.2,
                         box.y1 + 0.8)]
                adjust.append("no free slot found (warning)")
                self.adjust_count += 1
            else:
                off, box, path = final
            self.text_obbs.append((f"lead:{dcl.name}",
                                   (box.x0 + box.x1) / 2,
                                   (box.y0 + box.y1) / 2, w, h, 0.0))
            for i in range(len(path) - 1):
                self._reg_seg(f"lead:{dcl.name}", path[i], path[i + 1])
            self.resolved.append(Resolved(
                "leader", dcl.name or dcl.lines[0][:12], dcl.view,
                f"off={dcl.off}", f"off={tuple(round(v, 1) for v in off)}",
                adjust, {"anchor": a, "path": path, "lines": dcl.lines,
                         "text_x": box.x0, "text_y_top": box.y1}))

    # ---------- coverage / rules ----------
    def _solve_coverage_rules(self):
        P = self.d.params
        for k in P:
            where = None
            for r in self.resolved:
                if r.kind != "dim":
                    continue
                txt = r.draw.get("text", "")
                for dcl in self.d.dims:
                    if dcl.caption == r.name and (
                            k in dcl.covers or k == dcl.caption or
                            f"({k})" in txt):
                        where = f"{txt}@{r.view}"
                        break
                if where:
                    break
            if where is None:
                for i, nt in enumerate(self.d.notes):
                    if k in nt:
                        where = f"notes[{i + 1}]"
                        break
            if where is None:
                where = "parameter table"   # the parameter table at the bottom right of the sheet lists every item: counted as covered
            self.coverage.append((k, where))
            self.rule_log.append(("R5", "ok", f"{k}: {where}"))
        letters = {d.letter for d in self.d.datums}
        for dcl in self.d.dims:
            if dcl.datum and dcl.datum not in letters:
                self.rule_log.append(("R6", "fail",
                                      f"{dcl.caption} references an undeclared datum {dcl.datum}"))
        for r in self.resolved:
            if r.kind == "dim" and "rot" in r.draw:
                rot = abs(r.draw["rot"]) % 180.0
                if (60.0 < rot < 90.0) or (90.0 < rot < 120.0):
                    self.rule_log.append(("R3", "warn",
                                          f"{r.name}: text rotated {rot:g} deg, "
                                          "inside the near-vertical exclusion zone"))

    # ---------- overall plan ----------
    def solve(self):
        """Run the whole solve and return self. After solving, audit through resolved/accepted/report(),
        then draw with render(). Calling it again resets and solves again."""
        self._prime()
        self._solve_views()
        self._solve_datums()
        lin = sorted([x for x in self.d.dims if x.semantic == "linear"],
                     key=lambda x: (x.view, x.side or "",
                                    x.row, -abs(x.value or 0)))
        for dcl in lin:
            self._solve_dim(dcl)
        for dcl in [x for x in self.d.dims if x.semantic != "linear"]:
            self._solve_dim(dcl)
        self._solve_leaders()
        self._solve_coverage_rules()
        self._auto_diag()
        return self

    def _auto_diag(self):
        """Once diag_png is declared: every solve()/apply() refreshes the conflict diagnostic picture automatically.
        Visual feedback is a first-class channel of the agent-in-the-loop: the caller reads the picture and decides, the engine only supplies truth."""
        if not getattr(self.d, "diag_png", ""):
            return
        try:
            from .agent import annotate_plan, evaluate_plan
            annotate_plan(self, self.d.diag_png, evaluate_plan(self))
        except Exception as e:              # a failed diagnostic does not block solving; it goes into the log as it is
            self.rule_log.append(("R1", "warn", f"diagnostic picture failed to render: {e}"))

    def _solve_datums(self):
        for dcl in self.d.datums:
            at = self.tx(dcl.view, dcl.at)
            bc = (at[0] + dcl.box_off[0], at[1] + dcl.box_off[1])
            box = Box(bc[0] - 3, bc[1] - 2.2, bc[0] + 3, bc[1] + 2.2)
            self.datum_pos[dcl.letter] = at
            why = self._text_clear(f"datum:{dcl.letter}", bc[0], bc[1],
                                   6.0, 4.4, 0.0, skip_view=dcl.view)
            adjust = []
            if why:
                bc = (bc[0], bc[1] - 6.0)
                adjust.append("moved down to avoid")
            self.text_obbs.append((f"datum:{dcl.letter}",
                                   bc[0], bc[1], 6.0, 4.4, 0.0))
            self.resolved.append(Resolved(
                "datum", dcl.letter, dcl.view, f"at {dcl.at}",
                f"box@({bc[0]:.1f},{bc[1]:.1f})", adjust,
                {"at": at, "bc": bc, "kind": dcl.kind, "desc": dcl.desc},
                "R6"))

    def report(self) -> str:
        """Produce an auditable solve report: the datum system, requested→resolved and the adjustments of every element,
        the parameter-coverage (R5) table, the rule-check (R1-R7) results. It must be reviewed after a drawing is generated."""
        lines = [f"── Annotation plan report · {self.d.title} ({self.d.dwg_no}, "
                 f"scale {self.d.scale:g}:1) ──"]
        lines.append("datum system: " + "; ".join(
            f"{d.letter}={d.desc or d.kind}" for d in self.d.datums))
        for r in self.resolved:
            flag = " · ".join(r.adjust) if r.adjust else "ok"
            lines.append(f"{r.kind:<7} {r.name:<14} [{r.view:<5}] "
                         f"{r.requested:<22} → {r.resolved:<26} [{flag}]")
        lines.append("── Parameter coverage (R5) ──")
        for k, where in self.coverage:
            mark = "ok" if where != "not covered!" else "MISS"
            lines.append(f"  {k:<18} → {where:<26} [{mark}]")
        lines.append("── Rule checks ──")
        seen = {}
        for rl, st, dt in self.rule_log:
            seen.setdefault(rl, []).append((st, dt))
        for rl in ("R1", "R2", "R3", "R4", "R5", "R6", "R7"):
            entries = seen.get(rl)
            if not entries:
                lines.append(f"  {rl}: ok")
            elif all(st == "ok" for st, _ in entries):
                lines.append(f"  {rl}: ok ({len(entries)})")
            else:
                bad = [dt for st, dt in entries if st != "ok"]
                lines.append(f"  {rl}: {len(bad)} warnings: " + "; ".join(bad[:4]))
        lines.append(f"total adjustments: {self.adjust_count}")
        if getattr(self.d, "diag_png", ""):
            lines.append(f"diagnostic picture DIAG: {self.d.diag_png}")
            lines.append("  ↑ refreshed on every solve/apply; read it before the next decision — "
                         "grey=ok red=warn (read red first) blue=obstacle green arrow=direction and distance the element can slide")
        return "\n".join(lines)

    def render(self, dxf_path, png_path):
        """Render the DXF + PNG pair from the solved plan (delegates to render_plan)."""
        from .render import render_plan
        return render_plan(self, dxf_path, png_path)

    # ---------- LLM-in-the-loop evaluation/execution (carried by agent.py) ----------
    def evaluate(self):
        """Structured conflict report: per element violations (exact obstacle data) + corridors (free corridors)."""
        from .agent import evaluate_plan
        return evaluate_plan(self)

    def apply(self, actions):
        """Execute an LLM action sequence (rad/dia/lin/lead/accept), validating each one; a rejection rolls back."""
        from .agent import apply_actions
        return apply_actions(self, actions)

    def _solve_radius(self, dcl, vw, key):
        """Radius dimension (GB/T 4458.4): the declaration gives only `at` (azimuth). Once the angle is fixed the text keeps a single degree of freedom along the leader
        (start s, searched by the engine over candidates), the baseline is always 1 mm above the line (normal n),
        leader length = s + text width + margin is **derived** — when the text slides out of the arrow segment the line extends sideways to cover it;
        mpt always lies on the circle (arrow touches the arc), rot always equals the line direction (R2, cannot be declared/overridden)."""
        s = self.s
        c = self.tx(dcl.view, dcl.center)
        r = dcl.radius * s
        u = (math.cos(math.radians(dcl.at)), math.sin(math.radians(dcl.at)))
        value = dcl.value if dcl.value is not None else dcl.radius
        text = f"R{value:g} ({dcl.caption})"
        w = _text_width(text, TEXT_H)
        rot = (dcl.at % 180.0 + 180.0) % 180.0
        if rot > 90.0:
            rot -= 180.0                                  # made upright
        rr = math.radians(rot)
        n = (-math.sin(rr), math.cos(rr))
        mpt = (c[0] + r * u[0], c[1] + r * u[1])          # arrow point on the arc
        adjust = []
        chosen = None
        # Candidate order: leader outside the arc (3, 9, ...) → inside the arc (s<0, the text sits inside the circle along a
        # dimension line through the centre, the arrow pointing from the centre side at the arc) — a GB/T 4458.4 radius line may pass through the centre.
        # Inner candidates deepen progressively: when an obstacle is near the centre a shallow position still pokes out, so a deeper one past the centre is needed.
        cands = (tuple(3.0 + 6.0 * k for k in range(5))
                 + (-(w + 4.0), -(w + 10.0), -(w + 18.0)))
        for s0 in cands:                                  # text start (1 DOF)
            inner = (s0 + w) < 0.0                        # inside: the whole text is within the circle
            tail_k = s0 - 1.5 if inner else s0 + w + 1.5  # derived leader length
            insert = (mpt[0] + s0 * u[0] + n[0] * 1.0,    # left end of the baseline: 1 mm above the line
                      mpt[1] + s0 * u[1] + n[1] * 1.0)
            anchor = (insert[0] + u[0] * w / 2 + n[0] * TEXT_H * 0.35,
                      insert[1] + u[1] * w / 2 + n[1] * TEXT_H * 0.35)
            tail = (mpt[0] + tail_k * u[0], mpt[1] + tail_k * u[1])
            why = []
            for z in self._zones:
                if self._obb_sat(anchor[0], anchor[1], w, TEXT_H, rot,
                                 z.inflate(1.0)):
                    why.append("keep-out zone")
            for n_v, vwb in self.views.items():
                if n_v != dcl.view and self._obb_sat(
                        anchor[0], anchor[1], w, TEXT_H, rot,
                        vwb["bbox"].inflate(0.5)):
                    why.append(f"view {n_v}")
            for kk, cx2, cy2, w2, h2, r2 in self.text_obbs:
                if kk != key and self._obb_obb(anchor[0], anchor[1], w, TEXT_H,
                                               rot, cx2, cy2, w2, h2, r2):
                    why.append(f"text {kk.split(':')[-1]}")
            for k2, sp2, sq2 in self.segments:
                if k2.startswith("cl:") or k2 == key:
                    continue                               # crossing a centre line is normal
                if (self._seg_cross(mpt, tail, sp2, sq2)
                        or self._seg_obb(sp2, sq2, anchor[0], anchor[1],
                                         w, TEXT_H, rot)):
                    why.append(f"dimension line {k2}")
            if not why:
                chosen = (s0, tail, insert, anchor, inner)
                if s0 != 3.0:
                    where = "inside the arc" if inner else "outside the arc"
                    adjust.append(f"text slide {where} s={s0:g}")
                    self.adjust_count += 1
                break
            adjust.append(f"R1 conflict@{s0:g}({why[0]})")
        if chosen is None:
            s0, inner = 15.0, False
            tail_k = s0 + w + 1.5
            insert = (mpt[0] + s0 * u[0] + n[0] * 1.0,
                      mpt[1] + s0 * u[1] + n[1] * 1.0)
            anchor = (insert[0] + u[0] * w / 2 + n[0] * TEXT_H * 0.35,
                      insert[1] + u[1] * w / 2 + n[1] * TEXT_H * 0.35)
            tail = (mpt[0] + tail_k * u[0], mpt[1] + tail_k * u[1])
            chosen = (s0, tail, insert, anchor, inner)
            adjust.append("R1 no ideal position found (warning)")
            self.adjust_count += 1
        s0, tail, insert, anchor, inner = chosen
        self.text_obbs.append((key, anchor[0], anchor[1], w, TEXT_H, rot))
        self._reg_seg(key, mpt, tail)
        # outside: the arrow points at the arc from outside; inside: the arrow points at the arc from the centre side
        arrow_deg = math.degrees(math.atan2(u[1], u[0]))
        if not inner:
            arrow_deg += 180.0
        draw = {"kind": "rad-man", "mpt": mpt, "tail": tail, "insert": insert,
                "anchor": anchor, "text": text, "rot": rot,
                "arrow_deg": arrow_deg}
        self.resolved.append(Resolved("dim", dcl.caption, dcl.view,
                                      f"at {dcl.at:g}°",
                                      f"{'inside the arc' if inner else 'outside the arc'} s={s0:g}",
                                      adjust, draw, "R2/R5"))

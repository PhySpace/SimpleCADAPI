"""dxf_engine.dims — placing dimensions, datum symbols and surface-texture symbols.

Each element kind has one geometry derivation (`lin_geometry`, `dia_geometry`, `rad_geometry`) that the solver and the
agent actions share: what is checked is what is drawn. A solver walks its candidates in order of preference and takes
the first that `collide.conflicts` finds clean; when none is clean it draws the least-conflicted one and says so
(never a silent drop, never an element left undrawn).

Text on a line: the text stands 1 mm above the line and reads left to right or bottom to top (GB/T 4458.4), whatever
way the line was declared. `text_on_line` derives the insert point from the box that was checked.
"""
from __future__ import annotations

import math

from . import collide, refs
from .bind import lin_points
from .geom2d import BASE_OFF, DIM_ASZ, ROW_PITCH, TEXT_H, _text_width, norm_rot

ROUGH_H1, ROUGH_H2, ROUGH_TXT = 5.0, 10.5, 2.5      # GB/T 131 symbol for 3.5 mm lettering


def _unit(at_deg):
    a = math.radians(at_deg)
    return (math.cos(a), math.sin(a))


def text_on_line(origin, u, s0, w):
    """A text of width w occupying [s0, s0 + w] along the direction u from origin, 1 mm above the line.
    Returns (insert = left end of the baseline in reading direction, anchor = centre of the text box, rot)."""
    rot = norm_rot(math.degrees(math.atan2(u[1], u[0])))
    rr = math.radians(rot)
    ru, n = (math.cos(rr), math.sin(rr)), (-math.sin(rr), math.cos(rr))
    mid = (origin[0] + (s0 + w / 2) * u[0], origin[1] + (s0 + w / 2) * u[1])
    anchor = (mid[0] + n[0] * (1.0 + TEXT_H * 0.35), mid[1] + n[1] * (1.0 + TEXT_H * 0.35))
    insert = (mid[0] - ru[0] * w / 2 + n[0] * 1.0, mid[1] - ru[1] * w / 2 + n[1] * 1.0)
    return insert, anchor, rot


def _commit(plan, key, anchor, w, h, rot, segs):
    plan.text_obbs.append((key, anchor[0], anchor[1], w, h, rot))
    for sp, sq in segs:
        plan._reg_seg(key, sp, sq)


def _note(plan, adjust, text):
    adjust.append(text)
    plan.adjust_count += 1


# ---------------------------------------------------------------------------
# linear
# ---------------------------------------------------------------------------

def lin_geometry(plan, dcl, side, row, slide, text):
    """Linear-dimension geometry derivation (shared by the solver and the agent actions: one derivation, one truth):
    the dimension line sits on row `row` (side `side`) outside the view bbox; the text has one degree of freedom
    along the dimension line (slide, sheet offset from the measurement midpoint); when the text slides out of the
    measured segment the dimension line **extends sideways automatically** to cover it (arrows still point at the measured points)."""
    bb = plan.views[dcl.view]["bbox"]
    m1, m2 = lin_points(dcl, side)
    p1, p2 = plan.tx(dcl.view, m1), plan.tx(dcl.view, m2)
    axis = getattr(dcl, "_axis", None)
    vertical = (axis == "y") if axis else abs(p2[1] - p1[1]) >= abs(p2[0] - p1[0])
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
            "slide": slide, "side": side, "row": row, "defs": (p1, p2),
            "extended": (lo < (p1[1] if vertical else p1[0]) - 0.01 or
                         hi > (p2[1] if vertical else p2[0]) + 0.01)}


def lin_draw(g):
    return {k: g[k] for k in ("kind", "line", "arrows", "exts", "insert", "rot", "text", "extended",
                              "side", "row", "slide", "defs", "center")}


def solve_linear(plan, dcl, key):
    from .planner import Resolved
    side, text = dcl.side, plan.dim_text(dcl)
    w = _text_width(text, TEXT_H)
    g0 = lin_geometry(plan, dcl, side, dcl.row, 0.0, text)
    span = math.dist(*g0["arrows"])
    if span >= w + 2.0:
        # midpoint first (zero offset); on a conflict slide first (minimum adjustment), then shift rows
        slides = (0.0, w / 2 + 2.0, -(w / 2 + 2.0), w + 6.0, -(w + 6.0))
    else:
        # the measured segment cannot hold the text: place it outside and extend the dimension line (derived)
        off = span / 2 + w / 2 + 2.0
        slides = (off, -off)
    adjust, best = [], None
    for n_try in range(0, 7):
        row_i = dcl.row + n_try
        first = None
        for slide in slides:
            g = lin_geometry(plan, dcl, side, row_i, slide, text)
            conf = collide.conflicts(plan, key, dcl.view, g["center"][0], g["center"][1], w, TEXT_H, g["rot"],
                                     [g["line"]] + g["exts"])
            first = first or conf
            if not conf:
                if n_try:
                    _note(plan, adjust, f"R1 row shifted to row{row_i}")
                if slide:
                    _note(plan, adjust, f"text slid along the line {slide:+g}")
                if g["extended"]:
                    _note(plan, adjust, "dimension line extended sideways")
                best = (0.0, g)
                break
            c = collide.cost(conf) + n_try
            if best is None or c < best[0]:
                best = (c, g)
        if best and best[0] == 0.0:
            break
        _note(plan, adjust, f"R1 conflict@row{row_i}({first[0]['type']})")
    c, g = best
    if c:
        _note(plan, adjust, "R1 no conflict-free position: the least-conflicted one is drawn (warning)")
    _commit(plan, key, g["center"], w, TEXT_H, g["rot"], [g["line"]] + g["exts"])
    res = f"{side} row{g['row']}"
    if g["slide"] or g["extended"]:
        res += f" slide{g['slide']:+g}" + (" extended" if g["extended"] else "")
    plan.resolved.append(Resolved("dim", dcl.caption, dcl.view, f"{side} row{dcl.row}", res, adjust,
                                  lin_draw(g), "R2/R4"))


# ---------------------------------------------------------------------------
# diameter
# ---------------------------------------------------------------------------

def dia_fits_inside(r, w):
    """Two arrows, the text and a little air on the diameter line."""
    return w + 2 * DIM_ASZ + 2.0 <= 2 * r


def dia_geometry(plan, dcl, at, mode, text):
    """Diameter dimension (GB/T 4458.4 figure 10): the dimension line passes through the centre along `at`, both
    arrows touch the circle (m1/m2 always lie on it). mode "inside": the text stands on the line inside the circle;
    "outside": the line runs on past the circle and carries the text there. On a circle too small for two arrows the
    arrows point at it from outside."""
    c = plan.tx(dcl.view, dcl.center)
    r = dcl.radius * plan.s
    u = _unit(at)
    w = _text_width(text, TEXT_H)
    m1 = (c[0] + r * u[0], c[1] + r * u[1])
    m2 = (c[0] - r * u[0], c[1] - r * u[1])
    if mode == "inside":
        s0 = (r - DIM_ASZ - w) / 2 if w + 2.0 <= r - DIM_ASZ else -w / 2
        end = m1
    else:
        s0 = r + 2.0
        end = (c[0] + (s0 + w + 1.5) * u[0], c[1] + (s0 + w + 1.5) * u[1])
    arrows_out = 2 * r < 2 * DIM_ASZ + 2.0
    start = (m2[0] - (DIM_ASZ + 2.0) * u[0], m2[1] - (DIM_ASZ + 2.0) * u[1]) if arrows_out else m2
    insert, anchor, rot = text_on_line(c, u, s0, w)
    return {"kind": "dia-man", "m1": m1, "m2": m2, "insert": insert, "anchor": anchor, "text": text, "rot": rot,
            "line": (start, end), "arrows_out": arrows_out, "mode": mode, "at": at % 360.0}


def dia_segs(g):
    return [g["line"]]


def dia_modes(plan, dcl, text):
    r = dcl.radius * plan.s
    return ("inside", "outside") if dia_fits_inside(r, _text_width(text, TEXT_H)) else ("outside",)


def solve_diameter(plan, dcl, key):
    from .planner import Resolved
    text = plan.dim_text(dcl)
    w = _text_width(text, TEXT_H)
    adjust, best = [], None
    for k, d_at in enumerate((0.0, 180.0, 30.0, -30.0, 210.0, 150.0, 60.0, -60.0, 90.0, 270.0)):
        for mode in dia_modes(plan, dcl, text):
            g = dia_geometry(plan, dcl, dcl.at + d_at, mode, text)
            conf = collide.conflicts(plan, key, dcl.view, g["anchor"][0], g["anchor"][1], w, TEXT_H, g["rot"],
                                     dia_segs(g))
            c = collide.cost(conf)
            if best is None or c < best[0]:
                best = (c, g, k)
            if not conf:
                break
        if best[0] == 0.0:
            break
    c, g, k = best
    if k:
        _note(plan, adjust, f"moved to {g['at']:g}°")
    if c:
        _note(plan, adjust, "R1 no conflict-free position: the least-conflicted one is drawn (warning)")
    _commit(plan, key, g["anchor"], w, TEXT_H, g["rot"], dia_segs(g))
    plan.resolved.append(Resolved("dim", dcl.caption, dcl.view, f"at {dcl.at:g}°",
                                  f"rot {g['rot']:g}° {g['mode']}", adjust, g, "R2/R5"))


# ---------------------------------------------------------------------------
# radius
# ---------------------------------------------------------------------------

def rad_geometry(plan, dcl, at, s0, text):
    """Radius dimension (GB/T 4458.4): once `at` (azimuth) is fixed the text keeps a single degree of freedom along the
    leader: it occupies [s0, s0 + w] measured from the arrow point outwards (s0 < 0: inside the arc, on a dimension line
    towards the centre). The leader length is derived to cover the text; mpt always lies on the circle (the arrow
    touches the arc); rot always equals the line direction (R2, cannot be declared or overridden)."""
    c = plan.tx(dcl.view, dcl.center)
    r = dcl.radius * plan.s
    u = _unit(at)
    w = _text_width(text, TEXT_H)
    mpt = (c[0] + r * u[0], c[1] + r * u[1])          # arrow point on the arc
    inner = (s0 + w) < 0.0                            # inside: the whole text is within the circle
    tail_k = s0 - 1.5 if inner else s0 + w + 1.5      # derived leader length
    insert, anchor, rot = text_on_line(mpt, u, s0, w)
    tail = (mpt[0] + tail_k * u[0], mpt[1] + tail_k * u[1])
    # outside: the arrow points at the arc from outside; inside: the arrow points at the arc from the centre side
    arrow_deg = math.degrees(math.atan2(u[1], u[0])) + (0.0 if inner else 180.0)
    return {"kind": "rad-man", "mpt": mpt, "tail": tail, "insert": insert, "anchor": anchor, "text": text,
            "rot": rot, "arrow_deg": arrow_deg, "inner": inner, "s": s0, "at": at % 360.0}


def rad_candidates(w):
    """Text start along the leader: outside the arc (3, 9, ...) → inside (the text sits within the circle on a dimension
    line through the centre). Inner candidates deepen progressively: when an obstacle is near the centre a shallow
    position still pokes out, so a deeper one past the centre is needed."""
    return tuple(3.0 + 6.0 * k for k in range(5)) + (-(w + 4.0), -(w + 10.0), -(w + 18.0))


def solve_radius(plan, dcl, key):
    from .planner import Resolved
    text = plan.dim_text(dcl)
    w = _text_width(text, TEXT_H)
    adjust, best = [], None
    for s0 in rad_candidates(w):
        g = rad_geometry(plan, dcl, dcl.at, s0, text)
        conf = collide.conflicts(plan, key, dcl.view, g["anchor"][0], g["anchor"][1], w, TEXT_H, g["rot"],
                                 [(g["mpt"], g["tail"])])
        c = collide.cost(conf)
        if best is None or c < best[0]:
            best = (c, g)
        if not conf:
            if s0 != 3.0:
                where = "inside the arc" if g["inner"] else "outside the arc"
                _note(plan, adjust, f"text slide {where} s={s0:g}")
            break
        adjust.append(f"R1 conflict@{s0:g}({conf[0]['type']})")
    c, g = best
    if c:
        _note(plan, adjust, "R1 no conflict-free position: the least-conflicted one is drawn (warning)")
    _commit(plan, key, g["anchor"], w, TEXT_H, g["rot"], [(g["mpt"], g["tail"])])
    plan.resolved.append(Resolved("dim", dcl.caption, dcl.view, f"at {dcl.at:g}°",
                                  f"{'inside the arc' if g['inner'] else 'outside the arc'} s={g['s']:g}",
                                  adjust, g, "R2/R5"))


# ---------------------------------------------------------------------------
# datum symbols
# ---------------------------------------------------------------------------

def solve_datums(plan):
    from .planner import Resolved
    for dcl in plan.d.datums:
        at = plan.tx(dcl.view, dcl.at)
        plan.datum_pos[dcl.letter] = at
        bx, by = dcl.box_off
        offs = [(bx, by), (-bx, by), (bx, -by), (-bx, -by), (0.0, -abs(by) - 5.0), (0.0, abs(by) + 5.0),
                (-abs(bx) - 5.0, 0.0), (abs(bx) + 5.0, 0.0)]
        offs += [(1.8 * ox, 1.8 * oy) for ox, oy in offs]
        key, best = f"datum:{dcl.letter}", None
        for k, (ox, oy) in enumerate(offs):
            bc = (at[0] + ox, at[1] + oy)
            conf = collide.conflicts(plan, key, dcl.view, bc[0], bc[1], 6.0, 4.4, 0.0, [(at, bc)])
            c = collide.cost(conf)
            if best is None or c < best[0]:
                best = (c, bc, k)
            if not conf:
                break
        c, bc, k = best
        adjust = []
        if k:
            _note(plan, adjust, "moved to avoid")
        if c:
            _note(plan, adjust, "R1 no conflict-free position: the least-conflicted one is drawn (warning)")
        _commit(plan, key, bc, 6.0, 4.4, 0.0, [(at, bc)])
        plan.resolved.append(Resolved("datum", dcl.letter, dcl.view, f"at {dcl.at}",
                                      f"box@({bc[0]:.1f},{bc[1]:.1f})", adjust,
                                      {"at": at, "bc": bc, "kind": dcl.kind, "desc": dcl.desc}, "R6"))


# ---------------------------------------------------------------------------
# surface texture
# ---------------------------------------------------------------------------

def rough_geometry(tip, nrm, text):
    """GB/T 131 symbol standing on a surface at `tip`, pointing away along the unit normal `nrm` (sheet coordinates).
    Returns the strokes, the text placement and the box the symbol occupies."""
    t = (nrm[1], -nrm[0])                                  # along the surface, to the right when the normal is up
    k = math.tan(math.radians(30.0))

    def pt(a, b):
        return (tip[0] + a * t[0] + b * nrm[0], tip[1] + a * t[1] + b * nrm[1])

    w = _text_width(text, ROUGH_TXT)
    top = pt(ROUGH_H2 * k, ROUGH_H2)
    strokes = [(pt(-ROUGH_H1 * k, ROUGH_H1), tip), (tip, top),
               (pt(-ROUGH_H1 * k, ROUGH_H1), pt(ROUGH_H1 * k, ROUGH_H1)),
               (top, pt(ROUGH_H2 * k + w + 2.0, ROUGH_H2))]
    rot = math.degrees(math.atan2(t[1], t[0]))
    a0, a1 = -ROUGH_H1 * k, ROUGH_H2 * k + w + 2.0
    return {"strokes": strokes, "insert": pt(ROUGH_H2 * k + 1.0, ROUGH_H2 - ROUGH_TXT - 1.0), "rot": rot,
            "text": text, "anchor": pt((a0 + a1) / 2, (ROUGH_H2 + 1.0) / 2), "w": a1 - a0, "h": ROUGH_H2 - 1.0}


def solve_roughs(plan):
    from .planner import Resolved
    for i, dcl in enumerate(plan.d.roughs):
        name = dcl.name or f"rough{i + 1}"
        key = f"rough:{name}"
        ref = refs.resolve_ref(dcl.on, plan.by_name[dcl.view])
        lb = plan.views[dcl.view]["lbox"]
        ctr = ((lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2)
        if ref.kind == "band":                     # a cylinder seen from the side: stand on its upper or left outline
            ref = max(refs.silhouettes(ref), key=lambda l: (l.pts[0][1] + l.pts[1][1], -(l.pts[0][0] + l.pts[1][0])))
        if ref.kind == "line":
            a, b = ref.pts
            d = math.dist(a, b)
            nx, ny = -(b[1] - a[1]) / d, (b[0] - a[0]) / d
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if (mid[0] - ctr[0]) * nx + (mid[1] - ctr[1]) * ny < 0:          # outwards: away from the view's middle
                nx, ny = -nx, -ny
            spots = [(a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])) for f in (0.5, 0.3, 0.7, 0.15, 0.85)]
        else:
            nx, ny, spots = 0.0, 1.0, [ref.pts[0]]
        best = None
        for k, sp in enumerate(spots):
            g = rough_geometry(plan.tx(dcl.view, sp), (nx, ny), dcl.text)
            conf = collide.conflicts(plan, key, dcl.view, g["anchor"][0], g["anchor"][1], g["w"], g["h"], g["rot"], [])
            c = collide.cost(conf)
            if best is None or c < best[0]:
                best = (c, g, k)
            if not conf:
                break
        c, g, k = best
        adjust = []
        if k:
            _note(plan, adjust, "slid along the surface")
        if c:
            _note(plan, adjust, "R1 no conflict-free position: the least-conflicted one is drawn (warning)")
        g["readable"] = -1e-6 <= g["rot"] <= 90.0 + 1e-6      # the text reads from below or from the right
        _commit(plan, key, g["anchor"], g["w"], g["h"], g["rot"], [])
        plan.resolved.append(Resolved("rough", name, dcl.view, f"on {ref.desc}", dcl.text, adjust, g, "GB/T 131"))

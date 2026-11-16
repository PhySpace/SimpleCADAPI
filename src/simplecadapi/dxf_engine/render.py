"""dxf_engine.render — the solved plan → DXF + PNG.

GB/T 4458.4 primitives:
  dimension / extension lines  thin solid
  outline                      thick solid (b=0.5)
  dashed / centre lines        thin dashed / thin chain
  arrow                        solid triangle (about 6b long)
  text                         parallel to the dimension line, heads up / left (rotation normalised)

A dimension is a native DXF DIMENSION entity (style "GB", measured points as definition points, the measurement in
group 42, DIMLFAC = 1/scale), so that a CAD program can select, edit and re-measure it. Its picture, the anonymous
block the entity points to, is drawn here from the geometry the solver checked: what was checked is what is seen.
After writing, the file is read back and every dimension is compared with the model (`verify_dxf`).
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

import ezdxf
from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Circle, GeomAbs_Line

from . import sheet as _sheet
from .bind import fmt_number, native_text, split_tol
from .collide import seg_clip_obb
from .geom2d import _cjk_font_name, DIM_ASZ, DIM_EXE, DIM_EXO, DIM_GAP, TEXT_H, TOL_GAP, TOL_H, _text_width
from .planner import SEC_TXT

DIMSTYLE = "GB"
_LAYERS = [
    ("01_THICK_SOLID", 7, "Continuous", 50),
    ("08_DASHED", 3, "DASHED_GB", 25),
    ("05_CENTER", 1, "CENTER_GB", 25),
    ("01_THIN_SOLID", 7, "Continuous", 25),
    ("HATCH", 8, "Continuous", 18),
    ("DIMENSION", 7, "Continuous", 25),
    ("TEXT", 7, "Continuous", 25),
]


def _arrow(msp, tip, direction_deg, layer="DIMENSION", length=3.0, width=1.15):
    a = math.radians(direction_deg)
    ux, uy = math.cos(a), math.sin(a)
    px, py = -uy, ux
    b1 = (tip[0] - ux * length + px * width / 2,
          tip[1] - uy * length + py * width / 2)
    b2 = (tip[0] - ux * length - px * width / 2,
          tip[1] - uy * length - py * width / 2)
    msp.add_solid([tip, b1, b2], dxfattribs={"layer": layer})


def _seg(msp, p, q, layer):
    msp.add_line(p, q, dxfattribs={"layer": layer})


def _poly(msp, pts, layer, closed=False):
    msp.add_lwpolyline(list(pts), format="xy",
                       dxfattribs={"layer": layer, "closed": closed})


def _draw_view_edges(msp, plan, view):
    from .hlr import arc_angles
    ox, oy, s = view["ox"], view["oy"], plan.s
    for ad, pts, visible in view["edges"]:
        if len(pts) < 2:
            continue
        layer = "01_THICK_SOLID" if visible else "08_DASHED"
        g = ad.GetType()
        if g == GeomAbs_Line:
            (x0, y0), (x1, y1) = pts[0], pts[-1]
            msp.add_line((x0 * s + ox, y0 * s + oy), (x1 * s + ox, y1 * s + oy),
                         dxfattribs={"layer": layer})
        elif g == GeomAbs_Circle:
            circ = ad.Circle()
            c = circ.Location()
            cx, cy, rr = c.X(), c.Y(), circ.Radius()
            if abs(circ.Axis().Direction().Z()) < 0.999:
                _poly(msp, [(p[0] * s + ox, p[1] * s + oy) for p in pts], layer)
            else:
                q0 = ad.Value(ad.FirstParameter())
                q1 = ad.Value(ad.LastParameter())
                closed = math.hypot(q0.X() - q1.X(), q0.Y() - q1.Y()) < 1e-6
                if closed:
                    msp.add_circle((cx * s + ox, cy * s + oy), rr * s,
                                   dxfattribs={"layer": layer})
                else:
                    a0, a1 = arc_angles(ad, (cx, cy),
                                        ad.FirstParameter(), ad.LastParameter())
                    msp.add_arc((cx * s + ox, cy * s + oy), rr * s, a0, a1,
                                dxfattribs={"layer": layer})
        else:
            _poly(msp, [(p[0] * s + ox, p[1] * s + oy) for p in pts], layer)


def _rot_text(msp, text, insert, rot, layer="TEXT", h=TEXT_H, style="CJK"):
    text = text.replace("⌀", "%%c")          # the DXF code for the diameter sign: every font and CAD program has it
    msp.add_text(text, dxfattribs={"layer": layer, "style": style,
                                   "height": h, "rotation": rot}
                 ).set_placement(insert)


def _dim_text(lay, text, insert, rot):
    """The dimension figure; a stacked tolerance "{+0.021|0}" is drawn as two small lines after the number."""
    main, up, lo, tail = split_tol(text)
    _rot_text(lay, main, insert, rot)
    if not (up or lo):
        return
    rr = math.radians(rot)
    ru, n = (math.cos(rr), math.sin(rr)), (-math.sin(rr), math.cos(rr))
    x = _text_width(main, TEXT_H) + TOL_GAP
    th = TEXT_H * TOL_H
    for part, dy in ((up, TEXT_H * 0.55), (lo, -TEXT_H * 0.15)):
        _rot_text(lay, part, (insert[0] + ru[0] * x + n[0] * dy, insert[1] + ru[1] * x + n[1] * dy), rot, h=th)
    if tail:
        x += max(_text_width(up, th), _text_width(lo, th))
        _rot_text(lay, tail, (insert[0] + ru[0] * x, insert[1] + ru[1] * x), rot)


def _draw_dim(lay, dr):
    """The picture of one dimension, from the solved geometry, into the layout or block `lay`."""
    if dr["kind"] == "lin":
        for sp, sq in dr["exts"]:
            d = math.dist(sp, sq)
            if d > 1e-9:                               # leave the outline (offset), run past the dimension line
                ux, uy = (sq[0] - sp[0]) / d, (sq[1] - sp[1]) / d
                _seg(lay, (sp[0] + ux * min(DIM_EXO, d), sp[1] + uy * min(DIM_EXO, d)),
                     (sq[0] + ux * DIM_EXE, sq[1] + uy * DIM_EXE), "DIMENSION")
        _seg(lay, dr["line"][0], dr["line"][1], "DIMENSION")
        a0, a1 = dr["arrows"]
        inward = math.dist(a0, a1) >= 2 * DIM_ASZ + 1.0       # room for two arrows between the extension lines
        for tip, ddeg in ((a0, dr["rot"] + 180.0), (a1, dr["rot"])):
            _arrow(lay, tip, ddeg if inward else ddeg + 180.0)
        if not inward:                                 # arrows outside, pointing in: the line carries them
            ux, uy = math.cos(math.radians(dr["rot"])), math.sin(math.radians(dr["rot"]))
            _seg(lay, (a0[0] - ux * (DIM_ASZ + 2.0), a0[1] - uy * (DIM_ASZ + 2.0)),
                 (a1[0] + ux * (DIM_ASZ + 2.0), a1[1] + uy * (DIM_ASZ + 2.0)), "DIMENSION")
    elif dr["kind"] == "dia-man":
        m1, m2 = dr["m1"], dr["m2"]
        _seg(lay, dr["line"][0], dr["line"][1], "DIMENSION")
        for tip, ref in ((m1, m2), (m2, m1)):
            ang = math.degrees(math.atan2(tip[1] - ref[1], tip[0] - ref[0]))
            _arrow(lay, tip, ang + 180.0 if dr["arrows_out"] else ang)
    elif dr["kind"] == "rad-man":
        _seg(lay, dr["mpt"], dr["tail"], "DIMENSION")
        _arrow(lay, dr["mpt"], dr["arrow_deg"])
    _dim_text(lay, dr["text"], dr["insert"], dr["rot"])


def _setup_dimstyle(doc, scale):
    st = doc.dimstyles.new(DIMSTYLE)
    st.dxf.dimtxt, st.dxf.dimasz, st.dxf.dimexo, st.dxf.dimexe, st.dxf.dimgap = TEXT_H, DIM_ASZ, DIM_EXO, DIM_EXE, DIM_GAP
    st.dxf.dimtad, st.dxf.dimtih, st.dxf.dimtoh = 1, 0, 0          # text above the line, aligned with it
    st.dxf.dimdec, st.dxf.dimzin, st.dxf.dimdsep = 2, 8, ord(".")
    st.dxf.dimlfac = 1.0 / scale                                   # sheet millimetres → model millimetres
    st.dxf.dimtxsty = "CJK"
    st.dxf.dimtfac = TOL_H


def _add_dimension(doc, msp, plan, dcl, r):
    """One native DIMENSION whose picture is the solved geometry. Returns the entity."""
    dr = r.draw
    blk = doc.blocks.new_anonymous_block(type_char="D")
    _draw_dim(blk, dr)
    override = {}
    if dcl.tol is not None:
        override = {"dimtol": 1, "dimtp": float(dcl.tol[0]), "dimtm": -float(dcl.tol[1]), "dimtdec": 3}
    attribs = {"layer": "DIMENSION"}
    if dr["kind"] == "lin":
        ov = msp.add_linear_dim(base=dr["arrows"][0], p1=dr["defs"][0], p2=dr["defs"][1],
                                angle=90.0 if abs(dr["rot"]) == 90.0 else 0.0, text=native_text(dcl, False),
                                dimstyle=DIMSTYLE, override=override, dxfattribs=attribs)
        mid = dr["center"]
    elif dr["kind"] == "dia-man":
        c, rr = plan.tx(dcl.view, dcl.center), dcl.radius * plan.s
        ov = msp.add_diameter_dim(center=c, radius=rr, angle=dr["at"], text=native_text(dcl, True),
                                  dimstyle=DIMSTYLE, override=override, dxfattribs=attribs)
        mid = dr["anchor"]
    else:
        c, rr = plan.tx(dcl.view, dcl.center), dcl.radius * plan.s
        ov = msp.add_radius_dim(center=c, radius=rr, angle=dr["at"], text=native_text(dcl, True),
                                dimstyle=DIMSTYLE, override=override, dxfattribs=attribs)
        mid = dr["anchor"]
    ov.commit()
    dim = ov.dimension
    dim.dxf.geometry = blk.name
    dim.dxf.text_midpoint = mid
    dim.dxf.actual_measurement = float(dcl._measured)
    return dim


def _render_leader(msp, r):
    dr = r.draw
    path, lines = dr["path"], dr["lines"]
    for i in range(len(path) - 1):
        _seg(msp, path[i], path[i + 1], "DIMENSION")
    dv = (path[1][0] - path[0][0], path[1][1] - path[0][1])
    ln = math.hypot(*dv) or 1.0
    tip = (path[0][0] + dv[0] / ln * 2.2, path[0][1] + dv[1] / ln * 2.2)
    _arrow(msp, tip, math.degrees(math.atan2(-dv[1], -dv[0])))
    ty = dr["text_y_top"] - 2.4
    for line in lines:
        msp.add_text(line, dxfattribs={"layer": "TEXT", "style": "CJK",
                                       "height": 2.2}).set_placement(
                                           (dr["text_x"], ty))
        ty -= 4.2


def _render_datum(msp, r):
    dr = r.draw
    at, bc, letter = dr["at"], dr["bc"], r.name
    dx, dy = bc[0] - at[0], bc[1] - at[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    px, py = -uy, ux
    base = (at[0] + ux * 2.6, at[1] + uy * 2.6)
    p1 = (base[0] + px * 1.5, base[1] + py * 1.5)
    p2 = (base[0] - px * 1.5, base[1] - py * 1.5)
    msp.add_lwpolyline([at, p1, p2], close=True, dxfattribs={"layer": "DIMENSION"})
    msp.add_lwpolyline([(bc[0] - 3, bc[1] - 2.2), (bc[0] + 3, bc[1] - 2.2),
                        (bc[0] + 3, bc[1] + 2.2), (bc[0] - 3, bc[1] + 2.2)],
                       close=True, dxfattribs={"layer": "DIMENSION"})
    join = ((bc[0], bc[1] - 2.2 if uy > 0 else bc[1] + 2.2) if abs(uy) > abs(ux)
            else ((bc[0] - 3) if ux > 0 else (bc[0] + 3), bc[1]))
    _seg(msp, base, join, "DIMENSION")
    msp.add_text(letter, dxfattribs={"layer": "TEXT", "height": 3.0}
                 ).set_placement((bc[0] - 1.1, bc[1] - 1.4))


def _render_rough(msp, g):
    for a, b in g["strokes"]:
        _seg(msp, a, b, "DIMENSION")
    _rot_text(msp, g["text"], g["insert"], g["rot"], h=2.5)


def _render_centres(msp, plan):
    """Centre lines, interrupted where a text stands on them (GB/T 4458.4: no line passes through a figure)."""
    for _view, p, q in plan.center_segs:
        cuts = []
        for _k, cx, cy, w, h, rot in plan.text_obbs:
            iv = seg_clip_obb(p, q, cx, cy, w, h, rot, pad=0.8)
            if iv:
                cuts.append(iv)
        t = 0.0
        for a, b in sorted(cuts) + [(1.0, 1.0)]:
            if a - t > 1e-3:
                _seg(msp, (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t),
                     (p[0] + (q[0] - p[0]) * a, p[1] + (q[1] - p[1]) * a), "05_CENTER")
            t = max(t, b)
    for cd in plan.d.centers:
        if not cd.arc:
            continue
        cx, cy, r, a0, a1 = cd.arc
        c0 = plan.tx(cd.view, (cx, cy))
        sweep = (a1 - a0) % 360.0              # DXF semantics: a0→a1 counter-clockwise
        msp.add_arc(c0, r * plan.s, a0, a0 + sweep, dxfattribs={"layer": "05_CENTER"})


def _render_sections(msp, plan):
    for name, vw in plan.views.items():
        if vw["hatch"]:
            hatch = msp.add_hatch(dxfattribs={"layer": "HATCH"})
            hatch.set_pattern_fill("ANSI31", scale=1.0)
            hatch.dxf.hatch_style = 0                       # fill by parity: holes in the cut face stay empty
            for loop in vw["hatch"]:
                hatch.paths.add_polyline_path([plan.tx(name, p) for p in loop], is_closed=True)
    for m in plan.section_marks:
        msp.add_text(m["title"], dxfattribs={"layer": "TEXT", "style": "CJK", "height": SEC_TXT}
                     ).set_placement(m["title_at"])
        for tr in m["traces"]:
            p, q, look = tr["p"], tr["q"], tr["look"]
            ln = math.dist(p, q)
            ux, uy = (q[0] - p[0]) / ln, (q[1] - p[1]) / ln
            for end, sgn in ((p, 1.0), (q, -1.0)):
                msp.add_lwpolyline([end, (end[0] + sgn * ux * 5.0, end[1] + sgn * uy * 5.0)],
                                   dxfattribs={"layer": "01_THICK_SOLID", "const_width": 0.7})
                tip = (end[0] + look[0] * 7.0, end[1] + look[1] * 7.0)
                _seg(msp, end, tip, "DIMENSION")
                _arrow(msp, tip, math.degrees(math.atan2(look[1], look[0])))
            for lc in tr["letters"]:
                msp.add_text(m["label"], dxfattribs={"layer": "TEXT", "style": "CJK", "height": SEC_TXT}
                             ).set_placement((lc[0] - SEC_TXT * 0.31, lc[1] - SEC_TXT / 2))


def _render_general_rough(msp, plan):
    if not plan.d.general_rough:
        return
    from .dims import rough_geometry
    tb = plan.fmt.title
    g = rough_geometry((tb[2] - 45.0, tb[3] + 5.0), (0.0, 1.0), plan.d.general_rough)
    _render_rough(msp, g)
    msp.add_text("(  )", dxfattribs={"layer": "TEXT", "style": "CJK", "height": 5.0}
                 ).set_placement((g["strokes"][3][1][0] + 2.0, tb[3] + 7.0))


def verify_dxf(plan, dxf_path, handles):
    """Read the written file back and compare every DIMENSION with the model: the measurement a CAD program derives
    from the definition points, and the number in the picture. Returns the issues (empty: file and model agree)."""
    from .checks import Issue
    doc = ezdxf.readfile(dxf_path)
    out = []
    for dcl in plan.dims:
        key = f"dim:{dcl.caption}"
        ent = doc.entitydb.get(handles.get(dcl.caption, ""))
        if ent is None or ent.dxftype() != "DIMENSION":
            out.append(Issue("DIM_MISSING_IN_FILE", "error", key, "the dimension is not in the written DXF",
                             "This is an engine fault: report it with the declaration.", dcl.view))
            continue
        lfac = doc.dimstyles.get(ent.dxf.dimstyle).dxf.dimlfac
        measured = abs(ent.get_measurement()) * lfac
        if abs(measured - dcl._measured) > 1e-4:
            out.append(Issue(
                "DIM_RENDER_MISMATCH", "error", key,
                f"a CAD program will measure {measured:.4g} from the definition points in the file; the model "
                f"measures {dcl._measured:.4g}", "This is an engine fault: report it with the declaration.", dcl.view,
                {"file": measured, "model": dcl._measured}))
        block = doc.blocks.get(ent.dxf.geometry)
        shown = [e.dxf.text for e in block if e.dxftype() == "TEXT"] if block is not None else []
        want = fmt_number(dcl._measured, dcl.dec)
        nums = re.findall(r"\d+(?:\.\d+)?", shown[0].split("×", 1)[-1].replace("%%c", "")) if shown else []
        if not nums or nums[0] != want:
            out.append(Issue(
                "DIM_RENDER_MISMATCH", "error", key,
                f"the picture of the dimension shows {shown[0] if shown else 'no text'!r}; the model measures {want}",
                "This is an engine fault: report it with the declaration.", dcl.view))
    return out


def render_plan(plan, dxf_path, png_path):
    """Render the solved SheetPlan as a GB-layer DXF + PNG pair, then read the DXF back and verify its dimensions.

    The DXF goes through ezdxf (GB layers 01_THICK_SOLID/08_DASHED/05_CENTER/DIMENSION/TEXT, native DIMENSION
    entities in style "GB"); the PNG is produced from the DXF through PyMuPdf for multimodal cross-checking.
    Returns {"dxf", "png", "entities", "dimensions", "issues"}; the issues also enter `plan.issues()` and `report()`.
    """
    t0 = time.time()
    dxf_path, png_path = Path(dxf_path), Path(png_path)   # a str path is as good as a Path
    import matplotlib
    matplotlib.use("Agg")

    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$LWDISPLAY"] = 1
    doc.styles.add("CJK", font=_cjk_font_name())
    doc.linetypes.add("DASHED_GB", [3.0, 2.0, -1.0], description="thin dashed GB 2/1")
    doc.linetypes.add("CENTER_GB", [18.0, 12.0, -1.5, 0.0, -1.5],
                      description="thin chain GB 12/1.5")
    for lname, color, lt, lw in _LAYERS:
        doc.layers.add(lname, color=color, linetype=lt, lineweight=lw)
    _setup_dimstyle(doc, plan.s)
    msp = doc.modelspace()

    for name, vw in plan.views.items():
        _draw_view_edges(msp, plan, vw)
    _render_sections(msp, plan)
    _render_centres(msp, plan)

    by_caption = {d.caption: d for d in plan.dims}
    handles = {}
    for r in plan.resolved:
        if r.kind == "dim" and r.draw.get("text"):
            handles[r.name] = _add_dimension(doc, msp, plan, by_caption[r.name], r).dxf.handle
    for r in plan.resolved:
        if r.kind == "leader":
            _render_leader(msp, r)
        elif r.kind == "datum":
            _render_datum(msp, r)
        elif r.kind == "rough":
            _render_rough(msp, r.draw)

    _sheet.draw_frame(msp, plan)
    _sheet.draw_notes(msp, plan)
    _render_general_rough(msp, plan)

    doc.saveas(dxf_path)
    plan.render_issues = verify_dxf(plan, dxf_path, handles)
    chk = ezdxf.readfile(dxf_path)
    cnt = len(list(chk.modelspace()))
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, pymupdf
    context = RenderContext(chk)
    backend = pymupdf.PyMuPdfBackend()
    cfg = config.Configuration(
        background_policy=config.BackgroundPolicy.WHITE,
        color_policy=config.ColorPolicy.BLACK)
    Frontend(context, backend, config=cfg).draw_layout(chk.modelspace())
    page = layout.Page(plan.fmt.w, plan.fmt.h, layout.Units.mm, margins=layout.Margins.all(2))
    png_path.write_bytes(backend.get_pixmap_bytes(page, fmt="png", dpi=220))
    print(f"    rendered {dxf_path.name} ({cnt} entities, {len(handles)} dimensions read back: "
          f"{'all agree with the model' if not plan.render_issues else f'{len(plan.render_issues)} MISMATCH'}) + "
          f"{png_path.name} ({time.time() - t0:.1f}s)")
    return {"dxf": str(dxf_path), "png": str(png_path), "entities": cnt, "dimensions": len(handles),
            "issues": [i.as_dict() for i in plan.render_issues]}

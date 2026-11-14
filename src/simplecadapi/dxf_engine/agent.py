"""dxf_engine.agent — the LLM-in-the-loop evaluation/execution interface.

Division of roles (evaluator + prompter, the LLM decides):
  engine (deterministic)  exact conflict data / free-corridor measures / action validation and landing (a rejection rolls back)
  LLM (decision)          picks points / trade-offs on the evaluation data and submits actions through apply; the engine re-checks everything
Geometric truth never leaves the code: the LLM never supplies an arithmetic result beyond bare vertices; semantic constraints such as mpt/arrows
are re-derived by the engine from (at,out,rot) — an arrow always lands on the real circle.
The evaluation policy matches every solver: text/dimension lines do not check the own view's figure lines (an annotation may overlap its own view).
"""
from __future__ import annotations

import math

from . import dims as _dims
from .collide import conflicts as _conflicts
from .collide import corridors as _corridors
from .collide import proper_cross as _proper_cross
from .geom2d import BASE_OFF, ROW_PITCH, TEXT_H, Box, _text_width, norm_rot


def _r(v, nd=1):
    return round(float(v), nd)


def _element_geom(r):
    """Resolved → (key, view, cx, cy, w, h, rot, segs): the box and the lines that were placed, exactly as drawn;
    None when the geometry is incomplete."""
    dr = r.draw
    if r.kind == "dim":
        w = _text_width(dr.get("text", ""), TEXT_H)
        if dr.get("kind") == "lin" and "center" in dr:
            c = dr["center"]
            return (f"dim:{r.name}", r.view, c[0], c[1], w, TEXT_H, dr["rot"],
                    [tuple(dr["line"])] + [tuple(s) for s in dr["exts"]])
        if dr.get("kind") == "dia-man":
            a = dr["anchor"]
            return (f"dim:{r.name}", r.view, a[0], a[1], w, TEXT_H, dr["rot"], _dims.dia_segs(dr))
        if dr.get("kind") == "rad-man":
            a = dr["anchor"]
            return (f"dim:{r.name}", r.view, a[0], a[1], w, TEXT_H, dr["rot"],
                    [(tuple(dr["mpt"]), tuple(dr["tail"]))])
        return None
    if r.kind == "leader" and r.name:
        x0, y1 = dr["text_x"], dr["text_y_top"]
        w = max(_text_width(t, 2.2) for t in dr["lines"])
        h = len(dr["lines"]) * 4.2 + 1.0
        p = dr["path"]
        return (f"lead:{r.name}", r.view, x0 + w / 2, y1 - h / 2, w, h, 0.0,
                [(tuple(p[i]), tuple(p[i + 1])) for i in range(len(p) - 1)])
    if r.kind == "datum":
        bc = dr["bc"]
        return (f"datum:{r.name}", r.view, bc[0], bc[1], 6.0, 4.4, 0.0, [(tuple(dr["at"]), tuple(bc))])
    if r.kind == "rough":
        a = dr["anchor"]
        return (f"rough:{r.name}", r.view, a[0], a[1], dr["w"], dr["h"], dr["rot"], [])
    return None


def evaluate_plan(plan):
    """Every placed element with its conflicts, tested by `collide.conflicts` (the test the solver used)."""
    accepted = getattr(plan, "accepted", {})
    elements = []
    for r in plan.resolved:
        if r.kind == "view":                      # a view is not an annotation element: not evaluated
            continue
        g = _element_geom(r)
        key = g[0] if g else f"{r.kind}:{r.name}"
        entry = {"id": key, "kind": r.kind, "view": r.view}
        if g is None:
            entry["status"] = "unsolved"
            elements.append(entry)
            continue
        _k, view, cx, cy, w, h, rot, segs = g
        conf = _conflicts(plan, key, view, cx, cy, w, h, rot, segs)
        rules = sorted({c["rule"] for c in conf})
        if r.kind == "dim" and ((60.0 < rot % 180.0 < 90.0) or (90.0 < rot % 180.0 < 120.0)):
            rules.append("R3")                    # exactly vertical 90° is legal (GB figure 17)
        entry.update(text=r.draw.get("text")
                     or (r.draw.get("lines") and " / ".join(r.draw["lines"])),
                     anchor=[_r(cx), _r(cy)], w=_r(w), h=_r(h), rot=_r(rot))
        if key in accepted:
            entry.update(status="accepted",
                         reason=accepted.get(key) if isinstance(accepted, dict)
                         else None)
        elif conf:
            entry.update(status="warn", rules=rules, violations=conf,
                         corridors=_corridors(plan, key, view, cx, cy, w, h, rot))
        else:
            entry["status"] = "ok"
            if "R3" in rules:
                entry["rules"] = ["R3"]
        elements.append(entry)
    n_warn = sum(1 for e in elements if e["status"] == "warn")
    return {"sheet": plan.d.title, "dwg_no": plan.d.dwg_no,
            "n_elements": len(elements), "n_warn": n_warn, "elements": elements}


def _find_dim(plan, caption):
    for d in plan.dims:
        if d.caption == caption:
            return d
    raise KeyError(f"dim {caption}")


def _find_resolved(plan, key):
    for r in plan.resolved:
        g = _element_geom(r)
        if g and g[0] == key:
            return r
    raise KeyError(key)


def _unregister(plan, key):
    old_ob = [t for t in plan.text_obbs if t[0] == key]
    old_sg = [t for t in plan.segments if t[0] == key]
    plan.text_obbs = [t for t in plan.text_obbs if t[0] != key]
    plan.segments = [t for t in plan.segments if t[0] != key]
    return old_ob, old_sg


def _restore(plan, old):
    plan.text_obbs += old[0]
    plan.segments += old[1]


def _commit(plan, key, cx, cy, w, h, rot, segs):
    plan.text_obbs.append((key, cx, cy, w, h, rot))
    for sp, sq in segs:
        plan.segments.append((key, sp, sq))


def _reject(plan, act, key, view, conf, cx, cy, w, h, rot):
    return {"op": act["op"], "element": key, "ok": False, "violations": conf,
            "corridors": _corridors(plan, key, view, cx, cy, w, h, rot)}


_norm_rot = norm_rot


def _place(plan, act, key, dcl, g, segs, desc):
    """Validate one derived geometry against everything else on the sheet; land it, or reject and roll back."""
    r = _find_resolved(plan, key)
    w = _text_width(g["text"], TEXT_H)
    cx, cy = g["center"] if g["kind"] == "lin" else g["anchor"]
    old = _unregister(plan, key)
    conf = _conflicts(plan, key, dcl.view, cx, cy, w, TEXT_H, g["rot"], segs)
    if conf and not act.get("force"):
        _restore(plan, old)
        return None, _reject(plan, act, key, dcl.view, conf, cx, cy, w, TEXT_H, g["rot"])
    r.draw.clear()
    r.draw.update(g)
    _commit(plan, key, cx, cy, w, TEXT_H, g["rot"], segs)
    _log(plan, key, desc)
    return g, {"op": act["op"], "element": key, "ok": True, "anchor": [_r(cx), _r(cy)], "rot": _r(g["rot"])}


def _apply_rad(plan, act):
    """Radius: the action only arbitrates `at` (azimuth, optional slide hint s; s<0 means the inside of the arc — the text sits inside the circle along a
    dimension line through the centre, the arrow pointing at the arc from the centre side). Baseline always above the line, leader length derived;
    rot always equals the line direction (R2 cannot be overridden), mpt is always c+r·u — the arrow is always on the circle."""
    dcl = _find_dim(plan, act["name"])
    key = f"dim:{dcl.caption}"
    dr = _find_resolved(plan, key).draw
    at = act.get("at", dr.get("at", dcl.at))
    w = _text_width(dr["text"], TEXT_H)
    cands = [float(act["s"])] if "s" in act else list(_dims.rad_candidates(w))
    res = None
    for s0 in cands:
        g = _dims.rad_geometry(plan, dcl, at, s0, dr["text"])
        where = "inside the arc" if g["inner"] else "outside the arc"
        done, res = _place(plan, act, key, dcl, g, [(g["mpt"], g["tail"])], f"at={at:g}° {where} s={s0:g}")
        if done:
            return res
    return res


def _apply_dia(plan, act):
    """Diameter: `at` (dimension-line azimuth) and optionally mode ("inside" | "outside"). The dimension line passes
    through the centre, the arrows touch the circle, rot always equals the line direction (R2)."""
    dcl = _find_dim(plan, act["name"])
    key = f"dim:{dcl.caption}"
    dr = _find_resolved(plan, key).draw
    at = act.get("at", dr.get("at", dcl.at))
    modes = [act["mode"]] if "mode" in act else list(_dims.dia_modes(plan, dcl, dr["text"]))
    res = None
    for mode in modes:
        if mode not in ("inside", "outside"):
            raise KeyError(f"dia mode {mode!r} (inside | outside)")
        g = _dims.dia_geometry(plan, dcl, at, mode, dr["text"])
        done, res = _place(plan, act, key, dcl, g, _dims.dia_segs(g), f"at={at:g}° {mode}")
        if done:
            return res
    return res


def _apply_lin(plan, act):
    """Linear: side/row structural slot + slide along the line (1 DOF). Geometry is derived with the solver through
    lin_geometry (when the text slides out of the measured segment the dimension line extends sideways automatically); there is no free text position."""
    dcl = _find_dim(plan, act["name"])
    key = f"dim:{dcl.caption}"
    dr = _find_resolved(plan, key).draw
    side = act.get("side", dr.get("side", dcl.side))
    row = act.get("row", dr.get("row", dcl.row))
    slide = float(act.get("slide", 0.0))
    g = _dims.lin_draw(_dims.lin_geometry(plan, dcl, side, row, slide, dr["text"]))
    _done, res = _place(plan, act, key, dcl, g, [g["line"]] + g["exts"],
                        f"{side} row{row} slide{slide:+g}" + (" line extended" if g["extended"] else ""))
    return res


def _apply_lead(plan, act):
    """Leader: off=[dx,dy] offset of the text box from the anchor (sheet mm). The path is re-derived from the box."""
    dcl = next((d for d in plan.d.leaders
                if (d.name or d.lines[0][:12]) == act["name"]), None)
    if dcl is None:
        raise KeyError(f"leader {act['name']}")
    key = f"lead:{dcl.name}"
    dr = _find_resolved(plan, key).draw
    a = plan.tx(dcl.view, dcl.anchor)
    w = max(_text_width(t, 2.2) for t in dcl.lines)
    h = len(dcl.lines) * 4.2 + 1.0
    off = act.get("off", [dr["text_x"] - a[0], dr["text_y_top"] - a[1]])
    tx0, ty0 = a[0] + off[0], a[1] + off[1]
    box = Box(tx0, ty0 - h, tx0 + w, ty0)
    # the elbow sits above the box top: a mid-box elbow of a multi-line text would cut through the second line's height band
    elb_y = ty0 + 0.8
    near_x = (box.x0 - 1.2) if dcl.dx_dir < 0 else (box.x1 + 1.2)
    path = [a, (a[0], elb_y), (near_x, elb_y)]
    segs = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
    old = _unregister(plan, key)
    conf = _conflicts(plan, key, dcl.view, tx0 + w / 2, ty0 - h / 2, w, h, 0.0, segs)
    if conf and not act.get("force"):
        _restore(plan, old)
        return _reject(plan, act, key, dcl.view, conf, tx0 + w / 2, ty0 - h / 2, w, h, 0.0)
    dr.update(anchor=a, path=path, text_x=tx0, text_y_top=ty0)
    _commit(plan, key, tx0 + w / 2, ty0 - h / 2, w, h, 0.0, segs)
    _log(plan, key, f"off=({off[0]:g},{off[1]:g})")
    return {"op": "lead", "element": key, "ok": True,
            "anchor": [_r(tx0 + w / 2), _r(ty0 - h / 2)]}


def _apply_accept(plan, act):
    """Accept the existing conflicts of an element and record the reason — an explicit trade-off, not a silent pass."""
    if not hasattr(plan, "accepted"):
        plan.accepted = {}
    plan.accepted[act["name"]] = act.get("reason", "")
    plan.rule_log.append(("R1", "accepted",
                          f"{act['name']}: {act.get('reason', '')}"))
    return {"op": "accept", "element": act["name"], "ok": True}


def _log(plan, key, desc):
    r = _find_resolved(plan, key)
    r.resolved = f"agent {desc}"
    r.adjust.append(f"agent: {desc}")
    plan.adjust_count += 1


def _cjk_font_path():
    """Full path of a CJK font for matplotlib (the same candidate order as render._cjk_font_name)."""
    import glob
    import os

    want = ("pingfang", "songti", "stheiti", "hiragino", "simsun", "simhei",
            "msyh", "arial unicode")
    pats = ["/System/Library/Fonts/PingFang*", "/System/Library/Fonts/Supplemental/*",
            "/System/Library/Fonts/*", "/Library/Fonts/*.ttf",
            "C:/Windows/Fonts/sim*.tt?", "C:/Windows/Fonts/msyh*"]
    for pat in pats:
        for f in sorted(glob.glob(pat)):
            low = os.path.basename(f).lower()
            if any(w in low for w in want) and low.endswith((".ttf", ".ttc", ".otf")):
                return f
    return None


def annotate_plan(plan, png_path, ev=None, crop_warn=True):
    """Conflict visualisation: elements are marked by OBB and obstacles overlaid (the drawing version of browser-use DOM marking).

    Badge [N] matches the id of elements[N] in the evaluate() output, aligning picture and text for the LLM:
    grey edge=ok / red edge and fill=warn / orange=accepted; blue=obstacle (bbox dashed frame, dimension line solid);
    black dotted line=view bbox, thin grey line=view figure lines. Uniform sheet coordinates (mm).
    crop_warn=True also saves a local enlargement `<stem>__<id>.png` for every warn element
    (field of view = element OBB ∪ obstacle extent, expanded)."""
    from pathlib import Path

    ev = ev or evaluate_plan(plan)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Rectangle

    from .planner import SheetPlan

    fp = _cjk_font_path()
    if fp:
        from matplotlib import font_manager
        font_manager.fontManager.addfont(fp)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
    plt.rcParams["axes.unicode_minus"] = False

    png_path = Path(png_path)
    fig, ax = plt.subplots(figsize=(16.5, 11.7), dpi=150)

    def draw():
        for n, vw in plan.views.items():
            for (x1, y1), (x2, y2) in vw["pairs"]:
                ax.plot([x1, x2], [y1, y2], color="#999999", lw=0.5, zorder=1)
            bb = vw["bbox"]
            ax.add_patch(Rectangle((bb.x0, bb.y0), bb.x1 - bb.x0, bb.y1 - bb.y0,
                                   fill=False, ls=":", ec="#444444", lw=0.6,
                                   zorder=1))
        style = {"ok": ("#bbbbbb", None), "unsolved": ("#8888ff", None),
                 "warn": ("#dd0022", "#ff000018"),
                 "accepted": ("#ee8800", "#ff990018")}
        dirs = {"+x": (1, 0), "-x": (-1, 0), "+y": (0, 1), "-y": (0, -1)}
        for i, e in enumerate(ev["elements"]):
            if e.get("anchor") is None:
                continue
            cx, cy, w, h, rot = *e["anchor"], e["w"], e["h"], e["rot"]
            ec, fc = style.get(e["status"], style["ok"])
            ax.add_patch(Polygon(SheetPlan._obb_corners(cx, cy, w, h, rot),
                                 closed=True, fill=fc is not None,
                                 facecolor=fc or "none", edgecolor=ec, lw=1.4,
                                 zorder=3))
            ax.text(cx, cy + h / 2 + 1.5, f"[{i}] {e['id']}", color=ec,
                    fontsize=6, ha="center", zorder=4)
            if e["status"] == "accepted" and e.get("reason"):
                ax.text(cx, cy - h / 2 - 1.5, "✓ " + e["reason"][:44],
                        color="#ee8800", fontsize=5.2, ha="center", va="top",
                        zorder=4)
            for v in e.get("violations", []):
                if "bbox" in v:
                    x0, y0, x1, y1 = v["bbox"]
                    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0,
                                           fill=False, ls="--", ec="#0066ff",
                                           lw=1.0, zorder=2))
                elif "seg" in v:
                    (sx0, sy0), (sx1, sy1) = v["seg"]
                    ax.plot([sx0, sx1], [sy0, sy1], color="#0066ff", lw=1.6,
                            zorder=2)
            for lbl, d in (e.get("corridors") or {}).items():
                if d <= 0:
                    continue                                  # no degree of freedom: not drawn
                dx, dy = dirs[lbl]
                ax.annotate("", xy=(cx + dx * d, cy + dy * d), xytext=(cx, cy),
                            arrowprops=dict(arrowstyle="->", color="#009944",
                                            lw=0.9), zorder=2)
                ax.text(cx + dx * d * 0.55, cy + dy * d * 0.55,
                        f"{lbl}{d:g}", color="#009944", fontsize=5.5,
                        ha="center", zorder=4)

    draw()
    ax.set_aspect("equal")
    ax.autoscale()
    ax.set_title(f"{plan.d.title} · conflict marking: red=warn orange=accepted blue=obstacle "
                 f"black dotted line=view bbox")
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(png_path)

    if crop_warn:
        dirs = {"+x": (1, 0), "-x": (-1, 0), "+y": (0, 1), "-y": (0, -1)}
        for e in ev["elements"]:
            if e["status"] != "warn":
                continue
            cx, cy = e["anchor"]
            xs, ys = [cx], [cy]
            for v in e.get("violations", []):
                if "bbox" in v:
                    xs += [v["bbox"][0], v["bbox"][2]]
                    ys += [v["bbox"][1], v["bbox"][3]]
                elif "seg" in v:
                    xs += [p[0] for p in v["seg"]]
                    ys += [p[1] for p in v["seg"]]
            for lbl, d in (e.get("corridors") or {}).items():
                if d > 0:                                 # corridor arrows enter the field of view
                    dx, dy = dirs[lbl]
                    dd = min(d, 25.0)
                    xs.append(cx + dx * dd)
                    ys.append(cy + dy * dd)
            m = max(15.0, (max(xs) - min(xs)) * 0.35, (max(ys) - min(ys)) * 0.35)
            ax.set_xlim(min(xs) - m, max(xs) + m)
            ax.set_ylim(min(ys) - m, max(ys) + m)
            safe = e["id"].replace("/", "_").replace(":", "_")
            fig.savefig(png_path.with_name(f"{png_path.stem}__{safe}.png"))
    plt.close(fig)
    return ev


_OPS = {"rad": _apply_rad, "dia": _apply_dia, "lin": _apply_lin,
        "lead": _apply_lead, "accept": _apply_accept}


def apply_actions(plan, actions):
    results = []
    for act in actions:
        fn = _OPS.get(act.get("op"))
        if fn is None:
            results.append({"op": act.get("op"), "ok": False,
                            "error": f"unknown op {act.get('op')!r}"})
            continue
        try:
            results.append(fn(plan, act))
        except KeyError as e:
            results.append({"op": act.get("op"), "ok": False, "error": str(e)})
    out = {"results": results, "eval": evaluate_plan(plan)}
    # agent-in-the-loop: every apply refreshes the diagnostic picture; the returned text asks the caller to read the picture first
    if getattr(plan.d, "diag_png", ""):
        try:
            annotate_plan(plan, plan.d.diag_png, out["eval"])
            out["diag"] = plan.d.diag_png
            out["instruction"] = ("diagnostic picture refreshed; read it before submitting the next actions: "
                                  "grey=ok red=warn (read red first) blue=obstacle "
                                  "green arrow=direction and distance the element can slide")
        except Exception as e:                # a failed diagnostic does not block the action result
            out["diag_error"] = str(e)
    return out

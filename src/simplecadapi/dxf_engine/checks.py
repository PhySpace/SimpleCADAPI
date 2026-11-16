"""dxf_engine.checks — what is wrong, or unverified, on a solved sheet.

One list of `Issue`s is the truth for the text report, for `SheetPlan.issues()` and for the diagnostic picture: the
placement issues come from the same evaluation (`agent.evaluate_plan` → `collide.conflicts`) the picture is drawn from.

Every issue says what, where, by how much, and what to do about it. Kinds of checks:

  placement     clashes of texts, lines, figure lines, zones and the frame (R1); near-vertical text (R3)
  truth         a declared value that the geometry does not measure; typed points that lie on no figure line
  completeness  holes and shafts without a diameter; overall sizes without a dimension; parameters only in the table;
                duplicated measurements (R7); undeclared datums (R6)
  sheet         views outside the frame or over one another; a sheet that a larger standard scale would fill
  output        what the written DXF says when read back (render.verify_dxf)

NOT_CHECKED lists what no check covers, so that "no issues" is never read as "a correct drawing".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Circle

from . import sheet as _sheet
from . import views as _views
from .bind import DIA, fmt_number
from .refs import dot

SEVERITIES = ("error", "warning", "info")
TOL = 0.02                 # mm, model units: two measurements this close are the same

NOT_CHECKED = (
    "whether the dimensions fully define the part (only holes/shafts, overall sizes and declared parameters are traced)",
    "tolerance values, fits and surface-texture values against a standard or the function of the part",
    "threads, welds and geometrical tolerances (no symbols for them yet)",
    "how another CAD program plots the file (fonts, line weights): open the DXF there before release",
)

_PLACEMENT = {
    "text": ("TEXT_OVER_TEXT", "stands on"),
    "figure line": ("TEXT_OVER_FIGURE", "stands on figure lines of"),
    "dimension line": ("LINES_CLASH", "clashes with a line of"),
    "dimension line over another": ("DIM_LINES_OVERLAP", "lies on top of a line of"),
    "keep-out zone": ("IN_KEEPOUT_ZONE", "is inside the title block or notes area"),
    "outside frame": ("OUTSIDE_FRAME", "is outside the sheet frame"),
    "view bbox": ("OVER_OTHER_VIEW", "is over"),
    "dimension line crosses another view's figure line": ("LINE_THROUGH_VIEW", "runs through the figure of"),
}
_RULE_OF = {"TEXT_OVER_TEXT": "R1", "TEXT_OVER_FIGURE": "R1", "LINES_CLASH": "R1", "DIM_LINES_OVERLAP": "R1",
            "IN_KEEPOUT_ZONE": "R1", "OUTSIDE_FRAME": "R1", "OVER_OTHER_VIEW": "R1", "LINE_THROUGH_VIEW": "R1",
            "PLACEMENT_FAILED": "R1", "DIM_TEXT_NEAR_VERTICAL": "R3", "PARAM_ONLY_IN_TABLE": "R5",
            "DATUM_UNDECLARED": "R6", "DUPLICATE_DIMENSION": "R7"}


@dataclass
class Issue:
    """One finding. severity: error (the sheet is wrong) | warning (it reads badly or something is missing) | info."""
    code: str
    severity: str
    element: str
    message: str
    hint: str = ""
    view: str = ""
    data: dict = field(default_factory=dict)

    @property
    def rule(self):
        return _RULE_OF.get(self.code, "")

    def as_dict(self):
        return {"code": self.code, "severity": self.severity, "element": self.element, "view": self.view,
                "message": self.message, "hint": self.hint, "data": self.data}


def _move_hint(e):
    """What to change for a clashing element, from its kind and the free distances around it."""
    free = {k: v for k, v in (e.get("corridors") or {}).items() if v >= 2.0}
    room = ("free to move: " + ", ".join(f"{k} {v:g} mm" for k, v in free.items()) + ". ") if free else \
        "no free room within 60 mm in any direction. "
    name = e["id"].split(":", 1)[1]
    how = {"dim": f"Re-declare side/row/at, or apply an action on {name!r}: lin (side, row, slide), "
                  "dia (at, mode), rad (at, s)",
           "leader": f"Apply {{'op': 'lead', 'name': {name!r}, 'off': [dx, dy]}} or declare another off",
           "datum": "Declare another box_off for the datum",
           "rough": "Reference a longer or freer surface line"}.get(e["kind"], "Move the element")
    return room + how + "; or accept it with a reason ({'op': 'accept', 'name': id, 'reason': ...})."


def _placement(plan, ev):
    out, seen = [], set()
    for e in ev["elements"]:
        if e["status"] == "unsolved":
            out.append(Issue("PLACEMENT_FAILED", "error", e["id"], "the element has no geometry and is not drawn",
                             "Check its declaration (view name, references).", e["view"]))
            continue
        if e["status"] == "accepted":
            out.append(Issue("ACCEPTED", "info", e["id"], f"conflicts accepted: {e.get('reason') or 'no reason given'}",
                             view=e["view"]))
            continue
        if "R3" in (e.get("rules") or []):
            out.append(Issue("DIM_TEXT_NEAR_VERTICAL", "warning", e["id"],
                             f"the text is rotated {abs(e['rot']):g}°, inside the 30° zone next to vertical where "
                             "dimension figures are hard to read (GB/T 4458.4 figure 17)",
                             "Choose another `at`, or put the figure on a horizontal leader.", e["view"],
                             {"rot": e["rot"]}))
        if e["status"] != "warn":
            continue
        groups = {}
        for v in e["violations"]:
            groups.setdefault(v["type"], []).append(v["id"])
        for vtype, ids in groups.items():
            code, verb = _PLACEMENT.get(vtype, ("PLACEMENT_CONFLICT", "clashes with"))
            ids = sorted(set(ids))
            pair = (code, frozenset([e["id"], *ids]))
            if code in ("TEXT_OVER_TEXT", "LINES_CLASH", "DIM_LINES_OVERLAP") and pair in seen:
                continue                              # A over B was reported; B over A is the same finding
            seen.add(pair)
            others = "" if code in ("IN_KEEPOUT_ZONE", "OUTSIDE_FRAME") else " " + ", ".join(ids)
            out.append(Issue(code, "warning", e["id"],
                             f"{e.get('text') or e['id']!r} at ({e['anchor'][0]:g}, {e['anchor'][1]:g}) {verb}{others}",
                             _move_hint(e), e["view"],
                             {"anchor": e["anchor"], "w": e["w"], "h": e["h"], "rot": e["rot"], "with": ids,
                              "corridors": e.get("corridors", {})}))
    return out


def _pt_seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _view_circles(vw):
    out = []
    for ad, _pts, _vis in vw["edges"]:
        if ad.GetType() == GeomAbs_Circle:
            c = ad.Circle()
            out.append(((c.Location().X(), c.Location().Y()), c.Radius()))
    return out


def _nearest_on_figure(vw, p):
    best = (float("inf"), None)
    for _ad, pts, _vis in vw["edges"]:
        for a, b in zip(pts, pts[1:]):
            d = _pt_seg_dist(p, a, b)
            if d < best[0]:
                best = (d, a if math.dist(p, a) <= math.dist(p, b) else b)
    for c, _r in _view_circles(vw):
        d = math.dist(p, c)
        if d < best[0]:
            best = (d, c)
    return best


def _truth(plan):
    out = []
    for n in plan.value_notes:
        out.append(Issue(
            "DIM_VALUE_MISMATCH", "error", n["element"],
            f"declared value {fmt_number(n['declared'], 3)}, but the geometry measures {fmt_number(n['measured'], 3)} "
            f"(the sheet shows the measured {fmt_number(n['measured'])})",
            "One of the two is wrong: correct the model, reference the geometry you mean, or correct `value`.",
            n["view"], {"declared": n["declared"], "measured": n["measured"]}))
    for dcl in plan.dims:
        if dcl._bound:
            continue
        vw, key = plan.views[dcl.view], f"dim:{dcl.caption}"
        if dcl.semantic == "linear":
            for label, p in (("p1", dcl.p1), ("p2", dcl.p2)):
                d, near = _nearest_on_figure(vw, p)
                if d > TOL:
                    out.append(Issue(
                        "DIM_NOT_ATTACHED", "warning", key,
                        f"{label}=({p[0]:g}, {p[1]:g}) lies on no figure line of view {dcl.view!r}; the nearest "
                        f"figure point is ({near[0]:g}, {near[1]:g}), {d:.3g} mm away",
                        "Measure model geometry instead of typed coordinates: between=(ref, ref), extent='x'|'y'.",
                        dcl.view, {"point": list(p), "nearest": list(near), "distance": d}))
        elif not any(math.dist(c, dcl.center) <= TOL and abs(r - dcl.radius) <= TOL for c, r in _view_circles(vw)):
            out.append(Issue(
                "DIM_NOT_ATTACHED", "warning", key,
                f"no circle with centre ({dcl.center[0]:g}, {dcl.center[1]:g}) and radius {dcl.radius:g} is drawn "
                f"in view {dcl.view!r}",
                "Reference the model instead of typed values: of=<circular edge, cylinder face or selector>.",
                dcl.view, {"center": list(dcl.center), "radius": dcl.radius}))
    return out


def _measure_dir(plan, dcl):
    """The 3D direction a linear dimension measures along, sign-normalised."""
    fr = plan.views[dcl.view]["frame"]
    v = fr[0] if dcl._axis == "x" else fr[1]
    return _norm_dir(v)


def _norm_dir(v):
    for c in v:
        if abs(c) > 1e-9:
            s = 1.0 if c > 0 else -1.0
            return tuple(round(s * x, 6) + 0.0 for x in v)
    return tuple(v)


def _completeness(plan):
    out = []
    letters = {d.letter for d in plan.d.datums}
    for dcl in plan.dims:
        if dcl.datum and dcl.datum not in letters:
            out.append(Issue("DATUM_UNDECLARED", "error", f"dim:{dcl.caption}",
                             f"references datum {dcl.datum!r}, which is not declared",
                             f"Declare DatumDecl({dcl.datum!r}, ...) or reference one of {sorted(letters)}.", dcl.view))
    # R7: the same measurement twice in one view
    seen = {}
    for dcl in plan.dims:
        if dcl.semantic == "linear":
            a, b = (p[0 if dcl._axis == "x" else 1] for p in (dcl.p1, dcl.p2))
            sig = (dcl.view, "lin", dcl._axis, round(min(a, b), 3), round(max(a, b), 3))
        else:
            sig = (dcl.view, dcl.semantic, round(dcl.center[0], 3), round(dcl.center[1], 3), round(dcl.radius, 3))
        if sig in seen:
            out.append(Issue("DUPLICATE_DIMENSION", "warning", f"dim:{dcl.caption}",
                             f"measures the same as dim:{seen[sig]} in view {dcl.view!r}",
                             "Keep one; a size is dimensioned once (GB/T 4458.4).", dcl.view))
        else:
            seen[sig] = dcl.caption
    # holes and shafts without a diameter (or radius) on the sheet
    dia = [d._measured for d in plan.dims if getattr(d, "_sym", "") == DIA]
    rad = [d._measured for d in plan.dims if d.semantic == "radius"]
    shapes, groups = {}, {}
    for v in plan.d.views:
        shapes.setdefault(id(v.shape), v.shape)
    for shp in shapes.values():
        for loc, axis, r, _t0, _t1 in _views.cylinders(shp):
            ax = _norm_dir(axis)
            foot = tuple(round(loc[i] - dot(loc, ax) * ax[i], 3) + 0.0 for i in range(3))
            groups.setdefault(round(r, 4), set()).add((ax, foot))
    for r, axes in sorted(groups.items()):
        if any(abs(v - 2 * r) <= TOL for v in dia) or any(abs(v - r) <= TOL for v in rad):
            continue
        out.append(Issue(
            "UNDIMENSIONED_CYLINDER", "warning", "sheet",
            f"the model has {len(axes)} hole(s)/shaft(s) of ⌀{fmt_number(2 * r)} and no diameter dimension shows that size",
            f"Add DimDecl('size', view, 'diameter', name, of=<a cylinder face or circular edge of it>"
            f"{', count=%d' % len(axes) if len(axes) > 1 else ''}).",
            data={"diameter": 2 * r, "count": len(axes)}))
    # overall sizes
    lin = [(_measure_dir(plan, d), d._measured) for d in plan.dims if d.semantic == "linear"]
    done = set()
    for name, vw in plan.views.items():
        lb = vw["lbox"]
        for axis, size, vec in (("x", lb[2] - lb[0], vw["frame"][0]), ("y", lb[3] - lb[1], vw["frame"][1])):
            direction = _norm_dir(vec)
            if direction in done:
                continue
            done.add(direction)
            if any(dd == direction and abs(val - size) <= TOL for dd, val in lin):
                continue
            if any(abs(v - size) <= TOL for v in dia):
                continue                              # a round part: its diameter is its overall size
            out.append(Issue(
                "OVERALL_SIZE_MISSING", "warning", "sheet",
                f"the overall size {fmt_number(size)} along {direction} carries no dimension",
                f"Add DimDecl('overall', {name!r}, 'linear', name, extent={axis!r}).",
                name, {"size": size, "direction": list(direction)}))
    for k, where in plan.coverage:
        if where == "parameter table":
            out.append(Issue("PARAM_ONLY_IN_TABLE", "info", f"param:{k}",
                             f"parameter {k} is on no figure dimension and in no note; it appears in the parameter table only",
                             f"If {k} is a size of the part, dimension it and name it in `covers` (or as the caption)."))
    return out


def _sheet_checks(plan):
    out = []
    fr = plan.fmt.frame
    names = list(plan.views)
    for i, n in enumerate(names):
        bb = plan.views[n]["bbox"]
        if bb.x0 < fr[0] or bb.y0 < fr[1] or bb.x1 > fr[2] or bb.y1 > fr[3]:
            out.append(Issue("VIEW_OUTSIDE_FRAME", "error", f"view:{n}",
                             f"view {n!r} ({bb.x0:.0f},{bb.y0:.0f})–({bb.x1:.0f},{bb.y1:.0f}) leaves the frame "
                             f"({fr[0]:g},{fr[1]:g})–({fr[2]:g},{fr[3]:g})",
                             "Use scale=None (fit automatically), a smaller scale, a larger sheet, or anchor=None.", n))
        for z in plan._zones:
            if bb.overlaps(z):
                out.append(Issue("VIEW_OVER_TITLE_BLOCK", "error", f"view:{n}",
                                 f"view {n!r} lies over the title block or the notes area",
                                 "Use anchor=None (the views are centred in the free area) or a smaller scale.", n))
                break
        for m in names[i + 1:]:
            if bb.overlaps(plan.views[m]["bbox"]):
                out.append(Issue("VIEWS_OVERLAP", "error", f"view:{n}", f"views {n!r} and {m!r} overlap",
                                 "Increase the align gap of one of them.", n))
    lay = {n: (plan.views[n]["lbox"], plan.by_name[n].align) for n in names}
    best = _sheet.choose_scale(lay, plan.d.front, plan.fmt)
    if best > plan.s * 1.001:
        out.append(Issue("SHEET_UNDERUSED", "info", "sheet",
                         f"the views would fit at {_sheet.scale_text(best)}; the sheet is drawn at "
                         f"{_sheet.scale_text(plan.s)}",
                         "Use scale=None to take the largest standard scale that fits, or a smaller sheet."))
    if not any(abs(plan.s - s) < 1e-9 for s in _sheet.STD_SCALES):
        out.append(Issue("SCALE_NOT_STANDARD", "warning", "sheet",
                         f"scale {_sheet.scale_text(plan.s)} is not in GB/T 14690 (first series)",
                         "Use one of " + ", ".join(_sheet.scale_text(s) for s in _sheet.STD_SCALES[:8]) + "."))
    for r in plan.resolved:
        if r.kind == "rough" and not r.draw.get("readable", True):
            out.append(Issue("ROUGHNESS_UNREADABLE", "warning", f"rough:{r.name}",
                             "the symbol stands under or to the right of its surface, where its text would read upside "
                             "down (GB/T 131 reads from below or from the right)",
                             "Reference the same surface in a view that shows it from above or from the left.", r.view))
    return out


def collect_issues(plan):
    """All issues of a solved plan, errors first."""
    from .agent import evaluate_plan
    out = _placement(plan, evaluate_plan(plan))
    out += _truth(plan)
    out += _completeness(plan)
    out += _sheet_checks(plan)
    out += list(plan.render_issues)
    for rule, st, detail in plan.rule_log:
        if st == "warn":
            out.append(Issue("ENGINE_NOTE", "info", "sheet", detail))
    out.sort(key=lambda i: SEVERITIES.index(i.severity))
    return out


def format_issues(issues):
    """The issue section of the text report."""
    n = {s: sum(1 for i in issues if i.severity == s) for s in SEVERITIES}
    lines = [f"── Issues: {n['error']} error(s), {n['warning']} warning(s), {n['info']} note(s) ──"]
    mark = {"error": "[E]", "warning": "[W]", "info": "[i]"}
    for i in issues:
        lines.append(f"  {mark[i.severity]} {i.code} {i.element}: {i.message}")
        if i.hint:
            lines.append(f"        → {i.hint}")
    lines.append("── Rule checks ──")
    for rule in ("R1", "R2", "R3", "R4", "R5", "R6", "R7"):
        hits = [i for i in issues if i.rule == rule and i.severity != "info"]
        lines.append(f"  {rule}: ok" if not hits else f"  {rule}: {len(hits)} issue(s): " +
                     ", ".join(sorted({i.code for i in hits})))
    lines.append("── Not checked (no issue here does not mean it is right) ──")
    lines += [f"  · {t}" for t in NOT_CHECKED]
    return lines

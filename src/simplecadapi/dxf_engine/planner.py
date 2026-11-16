"""dxf_engine.planner — the dimensioning-plan solver.

Dimensioning principles (GB/T 4458.4-2003 / GB/T 16675.1 / GB/T 14691):
  R1 safe area      text (OBB) / leaders / dimension lines do not clash with figure lines, other annotations or keep-out zones (minimum adjustment)
  R2 text direction text runs parallel to the dimension line; heads up (horizontal) / left (vertical); never upside down
  R3 30° exclusion  an inclined dimension line within ±30° of vertical gives a warning (figure 17; exactly vertical 90° is legal)
  R4 row slots      same-side dimension rows are ROW_PITCH apart, declared rows first, collisions shift on; small dimensions inside, large outside
  R5 parameter cover every model parameter is carried by a figure dimension (covers/caption) or enters the technical requirements / parameter table
  R6 datum reference position dimensions must declare a datum; datum letters must be declared
  R7 no duplicates the same measurement is not repeated

Where things are: `views` (what a view shows), `sheet` (format, scale, arrangement), `bind` (declared → measured
dimension), `dims` / `leaders` (placement), `collide` (the one conflict test), `checks` (the issues of a solved plan),
`agent` (evaluation and actions for an LLM in the loop), `render` (DXF + PNG).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import dims as _dims
from . import sheet as _sheet
from . import views as _views
from .bind import bind_dim, dim_text
from .geom2d import (BASE_OFF, DIM_ASZ, DIM_EXE, DIM_EXO, DIM_GAP, DIM_TXT, ROW_PITCH, TEXT_H, Box, Geom2D,
                     _text_width)
from .leaders import solve_leaders
from .model import (CenterDecl, DatumDecl, DimDecl, LeaderDecl, SheetDecl,
                    ViewDecl)

SEC_TXT = 5.0             # height of section letters


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


class SheetPlan(Geom2D):
    """The dimensioning-plan solver: SheetDecl → solve() → resolved/issues()/report() → render().

    Solving: views (projection, scale, arrangement, centre lines, section marks) → linear dimensions
    (per view and side, small inside, large outside) → diameter/radius dimensions → datum symbols → surface texture → leaders →
    parameter coverage. What a dimension measures is taken from the model (`bind`); every conflict follows "minimum
    adjustment": candidate positions are tried in order and recorded in Resolved.adjust; when nothing fits, the
    least-conflicted position is drawn and reported, never silently dropped.
    """

    def __init__(self, decl: SheetDecl):
        self.d = decl
        self.fmt = _sheet.sheet_format(decl.sheet, decl.notes_zone, len(decl.notes), len(decl.params))
        self.by_name = {v.name: v for v in decl.views}
        self.s = decl.scale
        self._reset()

    def _reset(self):
        self.s = self.d.scale
        self.scale_how = "declared"
        self.views: dict[str, dict] = {}
        self.resolved: list[Resolved] = []
        self.text_obbs: list[tuple[str, float, float, float, float, float]] = []
        self.segments: list[tuple[str, tuple, tuple]] = []
        self.datum_pos: dict[str, tuple] = {}
        self.adjust_count = 0
        self.rule_log: list[tuple[str, str, str]] = []
        self.coverage: list[tuple[str, str]] = []
        self.dims: list[DimDecl] = []                 # the effective (measured) dimensions, see bind.bind_dim
        self.value_notes: list[dict] = []             # declared value ≠ measured value
        self.center_segs: list[tuple[str, tuple, tuple]] = []      # (view, p, q) on the sheet
        self.section_marks: list[dict] = []
        self.accepted: dict[str, str] = {}
        self.render_issues: list = []
        self._zones: list[Box] = []

    # ---------- geometry primitives ----------
    def tx(self, view, p):
        """View-local model coordinates → sheet coordinates (including the drawing scale)."""
        vw = self.views[view]
        return (vw["ox"] + p[0] * self.s, vw["oy"] + p[1] * self.s)

    def _prime(self):
        self._zones = [Box(*self.fmt.notes), Box(*self.fmt.title)]

    def _text_clear(self, key, cx, cy, w, h, rot, skip_view=None) -> list[str]:
        """Why a text box cannot stand here (empty: it can). skip_view is the element's own view."""
        from .collide import conflicts
        return [f"{c['type']} {c['id']}" for c in conflicts(self, key, skip_view, cx, cy, w, h, rot, [])]

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
        d = self.d
        if d.front not in self.by_name:
            raise ValueError(f"front={d.front!r} is not one of the declared views {sorted(self.by_name)}")
        order = [d.front] + [v.name for v in d.views if v.name != d.front]
        built = {name: _views.build_view(self.by_name[name]) for name in order}
        lay = {name: (built[name]["lbox"], self.by_name[name].align) for name in order}
        if self.s is None:
            self.s = _sheet.choose_scale(lay, d.front, self.fmt)
            self.scale_how = "chosen to fit the sheet"
        anchor = self.by_name[d.front].anchor or d.anchor
        anchor_how = "declared anchor"
        if anchor is None:
            anchor = _sheet.centre_anchor(lay, d.front, self.s, self.fmt)
            anchor_how = "centred in the free area"
        pos, how, _box = _sheet.arrange(lay, d.front, self.s)
        s = self.s
        for name in order:
            b = built[name]
            ox, oy = anchor[0] + pos[name][0], anchor[1] + pos[name][1]
            lb = b["lbox"]
            pairs = []
            for _ad, pts, _vis in b["edges"]:
                sh = [(p[0] * s + ox, p[1] * s + oy) for p in pts]
                pairs.extend(zip(sh, sh[1:]))
            self.views[name] = {"ox": ox, "oy": oy,
                                "bbox": Box(ox + lb[0] * s, oy + lb[1] * s, ox + lb[2] * s, oy + lb[3] * s),
                                "edges": b["edges"], "pairs": pairs, "lbox": lb, "hatch": b["hatch"],
                                "frame": b["frame"],
                                "how": anchor_how if name == d.front else how[name]}
            self.resolved.append(Resolved(
                "view", name, name, f"anchor={self.by_name[name].anchor}", f"({ox:.1f},{oy:.1f})",
                [], {"how": self.views[name]["how"]}))
        self._solve_centres()
        self._solve_sections()

    def _solve_centres(self):
        for cd in self.d.centers:
            if not cd.arc:
                self.center_segs.append((cd.view, self.tx(cd.view, cd.p1), self.tx(cd.view, cd.p2)))
        if not self.d.auto_centers:
            return
        cache = {}
        for name, vw in self.views.items():
            shape = self.by_name[name].shape
            if id(shape) not in cache:
                cache[id(shape)] = _views.cylinders(shape)
            for a, b in _views.centre_marks(cache[id(shape)], vw["frame"], 3.0 / self.s):
                seg = (name, self.tx(name, a), self.tx(name, b))
                if not any(self._same_seg(seg, old) for old in self.center_segs):
                    self.center_segs.append(seg)

    @staticmethod
    def _same_seg(s1, s2):
        from .collide import collinear_overlap
        return s1[0] == s2[0] and collinear_overlap((s1[1], s1[2]), (s2[1], s2[2]), min_len=0.5)

    def _solve_sections(self):
        """Section titles ("A-A" above the view) and cutting-plane symbols in the views that show where the cut is."""
        for v in self.d.views:
            if v.section is None:
                continue
            label = v.label or "A"
            bb = self.views[v.name]["bbox"]
            title = f"{label}-{label}"
            tw = _text_width(title, SEC_TXT)
            tc = ((bb.x0 + bb.x1) / 2, bb.y1 + 4.0 + SEC_TXT / 2)
            self.text_obbs.append((f"sec:{label}", tc[0], tc[1], tw, SEC_TXT, 0.0))
            mark = {"label": label, "view": v.name, "title": title, "title_at": (tc[0] - tw / 2, bb.y1 + 4.0),
                    "traces": []}
            parents = [v.mark_in] if v.mark_in else [n for n in self.views if n != v.name]
            for pn in parents:
                if pn not in self.views:
                    raise ValueError(f"view {v.name!r}: mark_in={pn!r} is not a declared view")
                pv = self.views[pn]
                tr = _views.cutting_trace(v, pv["frame"], pv["lbox"], 6.0 / self.s)
                if tr is None:
                    if v.mark_in:
                        raise ValueError(f"view {v.name!r}: the view {pn!r} does not see its cutting plane edge-on, "
                                         "so it cannot show where the cut is")
                    continue
                p, q, look = self.tx(pn, tr[0]), self.tx(pn, tr[1]), tr[2]
                letters = []
                for end, sgn in ((p, -1.0), (q, 1.0)):
                    ux, uy = (q[0] - p[0]), (q[1] - p[1])
                    ln = math.hypot(ux, uy)
                    ux, uy = ux / ln, uy / ln
                    lc = (end[0] + sgn * ux * 4.0 + look[0] * 5.0, end[1] + sgn * uy * 4.0 + look[1] * 5.0)
                    letters.append(lc)
                    self.text_obbs.append((f"sec:{label}", lc[0], lc[1], SEC_TXT, SEC_TXT, 0.0))
                for end, sgn in ((p, 1.0), (q, -1.0)):           # the strokes and arrows are obstacles too
                    self._reg_seg(f"sec:{label}", end, (end[0] + sgn * ux * 5.0, end[1] + sgn * uy * 5.0))
                    self._reg_seg(f"sec:{label}", end, (end[0] + look[0] * 7.0, end[1] + look[1] * 7.0))
                mark["traces"].append({"view": pn, "p": p, "q": q, "look": look, "letters": letters})
                if not v.mark_in:
                    break
            self.section_marks.append(mark)

    # ---------- dimension solving ----------
    def dim_text(self, dcl):
        """The text of an effective dimension: built from the measurement."""
        return dim_text(dcl, dcl._measured, dcl._sym, self.d.show_captions)

    def _bind_dims(self):
        seen = set()
        for dcl in self.d.dims:
            if dcl.view not in self.views:
                raise ValueError(f"dimension {dcl.caption}: view {dcl.view!r} is not declared "
                                 f"(views: {sorted(self.views)})")
            if dcl.caption in seen:
                raise ValueError(f"two dimensions are named {dcl.caption!r}: a caption names one dimension "
                                 "(actions and reports refer to it)")
            seen.add(dcl.caption)
            eff, note = bind_dim(dcl, self.by_name[dcl.view], self.views[dcl.view]["lbox"])
            self.dims.append(eff)
            if note:
                self.value_notes.append(note)

    def _solve_dim(self, dcl: DimDecl):
        key = f"dim:{dcl.caption}"
        if dcl.semantic == "linear":
            _dims.solve_linear(self, dcl, key)
        elif dcl.semantic == "diameter":
            _dims.solve_diameter(self, dcl, key)
        elif dcl.semantic == "radius":
            _dims.solve_radius(self, dcl, key)

    def _lin_geometry(self, dcl, side, row, slide, text):
        return _dims.lin_geometry(self, dcl, side, row, slide, text)

    # ---------- coverage ----------
    def _solve_coverage(self):
        for k in self.d.params:
            where = None
            for dcl in self.dims:
                if k == dcl.caption or k in dcl.covers:
                    where = f"{self.dim_text(dcl)}@{dcl.view}"
                    break
            if where is None:
                for i, nt in enumerate(self.d.notes):
                    if k in nt:
                        where = f"notes[{i + 1}]"
                        break
            if where is None:
                where = "parameter table"   # the parameter table lists every item: on the sheet, but not on a figure
            self.coverage.append((k, where))

    # ---------- overall plan ----------
    def solve(self):
        """Run the whole solve and return self. After solving, audit through resolved/issues()/report(),
        then draw with render(). Calling it again resets and solves again."""
        self._reset()
        self._prime()
        self._solve_views()
        self._bind_dims()
        lin = sorted([x for x in self.dims if x.semantic == "linear"],
                     key=lambda x: (x.view, x.side, x.row, x._measured))
        for dcl in lin:
            self._solve_dim(dcl)
        for dcl in [x for x in self.dims if x.semantic != "linear"]:
            self._solve_dim(dcl)
        _dims.solve_datums(self)                      # after the dimensions: a datum box has more places to go
        _dims.solve_roughs(self)
        solve_leaders(self)
        self._solve_coverage()
        self._auto_diag()
        return self

    def _auto_diag(self):
        """Once diag_png is declared: every solve()/apply() refreshes the conflict diagnostic picture automatically."""
        if not getattr(self.d, "diag_png", ""):
            return
        try:
            from .agent import annotate_plan, evaluate_plan
            annotate_plan(self, self.d.diag_png, evaluate_plan(self))
        except Exception as e:              # a failed diagnostic does not block solving; it goes into the log as it is
            self.rule_log.append(("R1", "warn", f"diagnostic picture failed to render: {e}"))

    def issues(self):
        """Everything that is wrong or unverified on the solved sheet, as `checks.Issue` items (see checks.py)."""
        from .checks import collect_issues
        return collect_issues(self)

    def report(self) -> str:
        """Produce an auditable solve report: the sheet, requested→resolved and the adjustments of every element,
        the parameter-coverage (R5) table, and the issues (the same ones `issues()` returns and the diagnostic picture
        shows). It must be reviewed after a drawing is generated."""
        from .checks import format_issues
        lines = [f"── Annotation plan report · {self.d.title} ({self.d.dwg_no}, {self.fmt.name}, "
                 f"scale {_sheet.scale_text(self.s)}, {self.scale_how}) ──"]
        lines.append("datum system: " + ("; ".join(
            f"{d.letter}={d.desc or d.kind}" for d in self.d.datums) or "none declared"))
        for r in self.resolved:
            flag = " · ".join(r.adjust) if r.adjust else "ok"
            lines.append(f"{r.kind:<7} {r.name:<14} [{r.view:<5}] "
                         f"{r.requested:<22} → {r.resolved:<26} [{flag}]")
        if self.coverage:
            lines.append("── Parameter coverage (R5) ──")
            for k, where in self.coverage:
                lines.append(f"  {k:<18} → {where}")
        lines += format_issues(self.issues())
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

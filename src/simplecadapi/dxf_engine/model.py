"""dxf_engine.model — the dimensioning declaration model.

Dimensioning layers (GB/T 4458.4, GB/T 16675.1):
  datum system   DatumDecl    — primary/secondary datums, the starting point of position dimensions
  size semantics DimDecl.kind — size / position (must reference a datum) / overall
  geometry       DimDecl.semantic — linear / diameter / radius
  parameter trace covers      — which model parameters this dimension carries (parameter-coverage tracing R5)

What a dimension measures comes from the model, not from typed coordinates: `of` (the circle or cylinder of a
diameter/radius), `between` (the two references of a linear dimension) and `extent` (the overall size of the view) take
geometry references, see `refs.py`. The typed forms (`p1`/`p2`, `center`/`radius`) remain for geometry the model does
not have (a theoretical point); they are checked against the figure lines (DIM_NOT_ATTACHED).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ViewDecl:
    """An HLR projected view. n = viewing direction, xd = screen-right direction in the projection plane; align defines the layout constraint.

    shape is the solid itself (so that selector references resolve against it) or its OCCT shape (`part.wrapped`).
    section=(x, y, z) makes it a section view: the part is cut by the plane through that point square to n, the half
    towards the viewer is removed and the cut faces are hatched; `label` names it ("A" → title "A-A") and `mark_in`
    names the view that shows where the cut is (cutting-plane symbol)."""
    name: str
    shape: object
    n: tuple
    xd: tuple
    align: dict = field(default_factory=dict)   # {"to","side","gap"} side: below|right
    anchor: tuple | None = None
    section: tuple | None = None
    label: str = ""
    mark_in: str | None = None


@dataclass
class DimDecl:
    """One dimension declaration. A position dimension (kind=position) must reference a declared datum in `datum`.

    Say what is measured with exactly one of: `of` (diameter/radius: a circular edge, a cylinder face, or a selector of
    one), `between` (linear: two references), `extent` (linear: "x" or "y", the overall size of the view), or the typed
    forms `p1`/`p2` and `center`/`radius`. The number on the sheet is always the one measured from that geometry;
    `value`, when given, is what you expect it to be and a difference is reported (DIM_VALUE_MISMATCH)."""
    kind: str                     # size | position | overall
    view: str
    semantic: str                 # linear | diameter | radius
    caption: str                  # the element's name (and the model parameter it carries); shown on the sheet only with SheetDecl.show_captions
    value: float | None = None           # expected value; the drawn number is measured
    of: object = None                    # diameter/radius: reference to the circle / cylinder
    between: tuple | None = None         # linear: (reference, reference)
    axis: str | None = None              # linear: "x" horizontal / "y" vertical measurement (default: derived)
    extent: str | None = None            # linear: "x" | "y" overall size of the part in this view
    tol: tuple | None = None             # (upper, lower) deviations, e.g. (0.021, 0.0)
    fit: str = ""                        # tolerance class after the number, e.g. "H7"
    count: int = 0                       # "N×" before the number (N equal features)
    p1: tuple | None = None              # linear measured point (view-local model coordinates)
    p2: tuple | None = None
    center: tuple | None = None          # dia/rad centre
    radius: float | None = None
    at: float | None = None              # dia/rad azimuth (default: the middle of an arc, 45° on a full circle)
    datum: str | None = None             # datum letter referenced by position/size
    side: str | None = None              # bottom/right/left/top
    row: int = 0                  # desired row (same-side row pitch, collisions shift on)
    out: float = 8.0              # dia/rad text overhang
    dec: int | None = None        # decimals; None = as many as the value has, up to 2
    prefix: str = ""
    covers: list = field(default_factory=list)   # model parameter names carried
    name: str = ""

    def __post_init__(self):
        who = self.caption or self.name
        if self.semantic not in ("linear", "diameter", "radius"):
            raise ValueError(f"dimension {who}: semantic is linear, diameter or radius, got {self.semantic!r}")
        if self.semantic == "linear":
            given = [n for n, v in (("between", self.between), ("extent", self.extent),
                                    ("p1/p2", self.p1 if self.p2 is not None else None)) if v is not None]
            if len(given) != 1:
                raise ValueError(
                    f"linear dimension {who}: say what is measured with exactly one of between=(ref, ref), "
                    f"extent='x'|'y', or p1/p2; got {given or 'none'}")
            if self.between is not None and len(self.between) != 2:
                raise ValueError(f"linear dimension {who}: between takes two references")
            if self.extent not in (None, "x", "y"):
                raise ValueError(f"linear dimension {who}: extent is 'x' or 'y', got {self.extent!r}")
        else:
            typed = self.center is not None and self.radius is not None
            if (self.of is not None) == typed:
                raise ValueError(
                    f"{self.semantic} dimension {who}: say what is measured with exactly one of of=<circular edge, "
                    "cylinder face or selector> or center/radius")
        if self.tol is not None and len(self.tol) != 2:
            raise ValueError(f"dimension {who}: tol is (upper, lower)")
        if self.semantic == "linear" and self.kind == "position" and not self.datum:
            raise ValueError(f"The position dimension {self.caption or self.name} does not reference a declared datum")
        if self.covers and self.caption not in self.covers:
            self.covers = [self.caption] + list(self.covers)


@dataclass
class DatumDecl:
    """Datum symbol declaration (the GB datum system): primary datum A, secondary datums B/C…"""
    letter: str                   # A (primary) B C...
    kind: str                     # axis | plane
    view: str
    at: tuple                     # view-local model coordinates
    box_off: tuple = (9.0, 6.0)
    desc: str = ""


@dataclass
class CenterDecl:
    """Centre-line declaration: p1/p2 straight centre line, or arc=(cx,cy,r,a0,a1) arc centre line."""
    view: str
    p1: tuple | None = None
    p2: tuple | None = None
    arc: tuple = None             # (cx, cy, r, a0, a1) view-local model coordinates


@dataclass
class LeaderDecl:
    """Leader declaration: a polyline from anchor to the note text."""
    view: str
    anchor: tuple
    lines: list
    off: tuple = (30.0, -18.0)
    alt_offs: list = field(default_factory=list)
    dx_dir: float = 1.0
    name: str = ""


@dataclass
class RoughDecl:
    """Surface-texture symbol (GB/T 131, material removal required) standing on a surface line of a view.

    `on` is a reference to the surface as the view shows it (a plane face seen edge-on, a straight edge) or a view-local
    point; `text` is what stands above the symbol ("Ra 3.2")."""
    view: str
    on: object
    text: str = "Ra 3.2"
    name: str = ""


@dataclass
class SheetDecl:
    """The complete declaration of one sheet: sheet information + views + datums + dimensions + centre lines + leaders + parameter table.

    The caller declares only "what to express" and no sheet coordinate; the layout and the annotation positions are
    solved by SheetPlan.solve(). front/anchor anchors the main view, the other views align to it through
    ViewDecl.align (first-angle projection, length-aligned / height-aligned).
    """
    title: str
    dwg_no: str
    scale: float | None           # drawing scale (0.5 = 1:2); None = the largest standard scale that fits the sheet
    front: str
    anchor: tuple | None          # sheet position of the front view's origin; None = the views are centred in the free area
    views: list
    datums: list = field(default_factory=list)
    dims: list = field(default_factory=list)
    centers: list = field(default_factory=list)
    leaders: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    material: str = ""
    designer: str = ""
    revision: str = "1.0"
    sheet: str = "A3"             # A4 | A3 | A2 | A1 | A0, landscape
    roughs: list = field(default_factory=list)
    general_rough: str = ""       # surface texture of all other surfaces, shown above the title block ("Ra 6.3")
    show_captions: bool = False   # append "(caption)" to every dimension text: a review aid, not a production drawing
    auto_centers: bool = True     # centre lines of holes and shafts are drawn from the model's cylinders
    notes_zone: tuple | None = None   # x0,y0,x1,y1 (ordered); None = left of the title block
    diag_png: str = ""    # once declared, solve()/apply() refresh the conflict diagnostic picture (agent-in-the-loop)

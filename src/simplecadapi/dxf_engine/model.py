"""dxf_engine.model — the dimensioning declaration model.

Dimensioning layers (GB/T 4458.4, GB/T 16675.1):
  datum system   DatumDecl    — primary/secondary datums, the starting point of position dimensions
  size semantics DimDecl.kind — size / position (must reference a datum) / overall
  geometry       DimDecl.semantic — linear / diameter / radius
  parameter trace covers      — which model parameters this dimension carries (parameter-coverage tracing R5)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ViewDecl:
    """An HLR projected view. n = viewing direction, xd = screen-right direction in the projection plane; align defines the layout constraint."""
    name: str
    shape: object
    n: tuple
    xd: tuple
    align: dict = field(default_factory=dict)   # {"to","side","gap"} side: below|right
    anchor: tuple | None = None


@dataclass
class DimDecl:
    """One dimension declaration. A position dimension (kind=position) must reference a declared datum in `datum`."""
    kind: str                     # size | position | overall
    view: str
    semantic: str                 # linear | diameter | radius
    caption: str                  # parameter name (enters the text as "value (caption)")
    value: float | None = None
    p1: tuple | None = None              # linear measured point (view-local model coordinates)
    p2: tuple | None = None
    center: tuple | None = None          # dia/rad centre
    radius: float | None = None
    at: float | None = None              # dia/rad azimuth
    datum: str | None = None             # datum letter referenced by position/size
    side: str | None = None              # bottom/right/left/top
    row: int = 0                  # desired row (same-side row pitch, collisions shift on)
    out: float = 8.0              # dia/rad text overhang
    dec: int = 0
    prefix: str = ""
    covers: list = field(default_factory=list)   # model parameter names carried
    name: str = ""

    def __post_init__(self):
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
class SheetDecl:
    """The complete declaration of one sheet: sheet information + views + datums + dimensions + centre lines + leaders + parameter table.

    The caller declares only "what to express" and no sheet coordinate; the layout and the annotation positions are
    solved by SheetPlan.solve(). front/anchor anchors the main view, the other views align to it through
    ViewDecl.align (first-angle projection, length-aligned / height-aligned).
    """
    title: str
    dwg_no: str
    scale: float
    front: str
    anchor: tuple
    views: list
    datums: list = field(default_factory=list)
    dims: list = field(default_factory=list)
    centers: list = field(default_factory=list)
    leaders: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    material: str = "PLA-CF / PAHT"
    notes_zone: tuple = (25.0, 5.0, 232.0, 90.0)   # x0,y0,x1,y1 (ordered)
    diag_png: str = ""    # once declared, solve()/apply() refresh the conflict diagnostic picture (agent-in-the-loop)

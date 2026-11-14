"""dxf_engine.views — what a view shows: projected edges, the cut faces of a section, the axes of holes and shafts.

Everything is in view-local model coordinates (before the drawing scale); the planner places and scales it.

  build_view      HLR edges (of the cut solid, for a section view), the view's local bounding box, the hatch loops
  cylinders       the model's holes and shafts (cylinder faces spanning at least half a turn; a fillet is not one)
  centre_marks    the centre lines a view owes to those cylinders (GB/T 4457.4: thin chain lines, 2–5 mm overhang)
"""
from __future__ import annotations

import math

from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Cut
from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeBox
from simplecadapi._cpp.occt.BRepTools import BRepTools_WireExplorer
from simplecadapi._cpp.occt.GCPnts import GCPnts_QuasiUniformDeflection
from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from simplecadapi._cpp.occt.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_WIRE
from simplecadapi._cpp.occt.TopExp import TopExp_Explorer
from simplecadapi._cpp.occt.TopoDS import TopoDS
from simplecadapi._cpp.occt.gp import gp_Ax2, gp_Dir, gp_Pnt

from .hlr import discretize_edge, hlr_project
from .refs import PAR, _boundary_points, _xyz, dot, project, raw_shape, view_frame

BIG = 1.0e4               # half-size of the block that removes the near half of a section


def _faces(shape):
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        yield TopoDS.Face_s(exp.Current())
        exp.Next()


def _cut_near_half(shape, point, frame):
    """The part with everything between the viewer and the cutting plane removed."""
    xd, yd, n = frame
    corner = tuple(point[i] - BIG * xd[i] - BIG * yd[i] for i in range(3))
    block = BRepPrimAPI_MakeBox(gp_Ax2(gp_Pnt(*corner), gp_Dir(*n), gp_Dir(*xd)), 2 * BIG, 2 * BIG, BIG).Shape()
    cut = BRepAlgoAPI_Cut(shape, block)
    if not cut.IsDone():
        raise ValueError("section view: the cut failed in the kernel (BRepAlgoAPI_Cut)")
    return cut.Shape()


def _wire_loop(wire, frame, deflection=0.05):
    """A wire as one closed list of view-local points, in wire order."""
    loop, we = [], BRepTools_WireExplorer(wire)
    while we.More():
        edge = we.Current()
        ad = BRepAdaptor_Curve(edge)
        disc = GCPnts_QuasiUniformDeflection(ad, deflection, ad.FirstParameter(), ad.LastParameter())
        if disc.IsDone() and disc.NbPoints() >= 2:
            pts = [project(_xyz(disc.Value(i)), frame) for i in range(1, disc.NbPoints() + 1)]
        else:
            pts = [project(_xyz(ad.Value(t)), frame) for t in (ad.FirstParameter(), ad.LastParameter())]
        if we.Orientation() == TopAbs_REVERSED:
            pts.reverse()
        for p in pts:
            if not loop or math.dist(p, loop[-1]) > 1e-6:
                loop.append(p)
        we.Next()
    if len(loop) > 1 and math.dist(loop[0], loop[-1]) < 1e-6:
        loop.pop()
    return loop


def _section_loops(cut_shape, point, frame):
    """Boundary loops of the faces lying in the cutting plane (outer and inner loops alike: the hatch fills by parity)."""
    n, loops = frame[2], []
    for face in _faces(cut_shape):
        sf = BRepAdaptor_Surface(face)
        if sf.GetType() != GeomAbs_Plane:
            continue
        pln = sf.Plane()
        if abs(dot(_xyz(pln.Axis().Direction()), n)) < 1.0 - PAR:
            continue
        loc = _xyz(pln.Location())
        if abs(dot(tuple(loc[i] - point[i] for i in range(3)), n)) > 1e-6:
            continue
        exp = TopExp_Explorer(face, TopAbs_WIRE)
        while exp.More():
            loop = _wire_loop(TopoDS.Wire_s(exp.Current()), frame)
            if len(loop) >= 3:
                loops.append(loop)
            exp.Next()
    return loops


def build_view(v):
    """ViewDecl → {"edges": [(adaptor, points, visible)], "lbox": (x0, y0, x1, y1), "hatch": [loops], "frame": ...}."""
    frame = view_frame(v.n, v.xd)
    shape, hatch = raw_shape(v.shape), []
    if v.section is not None:
        if len(v.section) != 3:
            raise ValueError(f"view {v.name!r}: section is a model point (x, y, z) on the cutting plane")
        shape = _cut_near_half(shape, tuple(float(c) for c in v.section), frame)
        hatch = _section_loops(shape, v.section, frame)
        if not hatch:
            raise ValueError(
                f"view {v.name!r}: the cutting plane through {tuple(v.section)} square to n={tuple(v.n)} does not pass "
                "through the part. Move the section point into the material")
    vis, hid = hlr_project(shape, v.n, v.xd)
    if v.section is not None:
        hid = []                              # GB/T 17452: a section view does not show what lies behind as dashed lines
    edges, xs, ys = [], [], []
    for e, visible in [(e, True) for e in vis] + [(e, False) for e in hid]:
        ad, pts = discretize_edge(e)
        if len(pts) >= 2:
            edges.append((ad, pts, visible))
            xs += [p[0] for p in pts]
            ys += [p[1] for p in pts]
    if not xs:
        raise ValueError(f"view {v.name!r}: the projection has no edges (is the shape empty?)")
    return {"edges": edges, "lbox": (min(xs), min(ys), max(xs), max(ys)), "hatch": hatch, "frame": frame}


def cylinders(shape):
    """Holes and shafts of the model: [(axis point, axis direction, radius, t_min, t_max)], one per cylinder face that
    spans at least half a turn (a hole is usually two half faces; a fillet spans a quarter and is left out)."""
    out = []
    for face in _faces(raw_shape(shape)):
        sf = BRepAdaptor_Surface(face)
        if sf.GetType() != GeomAbs_Cylinder:
            continue
        if sf.LastUParameter() - sf.FirstUParameter() < math.pi - 1e-3:
            continue
        cyl = sf.Cylinder()
        loc, axis = _xyz(cyl.Axis().Location()), _xyz(cyl.Axis().Direction())
        ts = [dot(tuple(p[i] - loc[i] for i in range(3)), axis) for p in _boundary_points(face)]
        out.append((loc, axis, cyl.Radius(), min(ts), max(ts)))
    return out


def centre_marks(cyls, frame, overhang):
    """Centre lines of a view, as view-local segments: a cross on every cylinder seen along its axis, one line along
    every cylinder seen from the side. Coincident marks (the two halves of a hole, coaxial steps) are merged."""
    n = frame[2]
    crosses, lines = {}, {}
    for loc, axis, r, t0, t1 in cyls:
        along = dot(axis, n)
        if abs(along) > 1.0 - PAR:
            c = project(loc, frame)
            key = (round(c[0], 3), round(c[1], 3))
            crosses[key] = max(crosses.get(key, 0.0), r)
        elif abs(along) < PAR:
            a = project(tuple(loc[i] + t0 * axis[i] for i in range(3)), frame)
            b = project(tuple(loc[i] + t1 * axis[i] for i in range(3)), frame)
            if math.dist(a, b) < 1e-6:
                continue
            if (a[0], a[1]) > (b[0], b[1]):
                a, b = b, a
            d = math.dist(a, b)
            ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
            off = round(-a[0] * uy + a[1] * ux, 3)                 # signed distance of the line from the origin
            key = (round(ux, 4), round(uy, 4), off)
            ta, tb = a[0] * ux + a[1] * uy, b[0] * ux + b[1] * uy
            lo, hi = lines.get(key, (ta, tb))
            lines[key] = (min(lo, ta), max(hi, tb))
    segs = []
    for (cx, cy), r in sorted(crosses.items()):
        e = r + overhang
        segs.append(((cx - e, cy), (cx + e, cy)))
        segs.append(((cx, cy - e), (cx, cy + e)))
    for (ux, uy, off), (lo, hi) in sorted(lines.items()):
        ox, oy = -off * uy, off * ux
        segs.append(((ox + (lo - overhang) * ux, oy + (lo - overhang) * uy),
                     (ox + (hi + overhang) * ux, oy + (hi + overhang) * uy)))
    return segs


def cutting_trace(section_view, parent_frame, parent_lbox, overhang):
    """Where the parent view sees the cutting plane of `section_view`: (p, q, viewing direction in the parent view),
    or None when the parent view does not see the plane edge-on."""
    sn = view_frame(section_view.n, section_view.xd)[2]
    if abs(dot(sn, parent_frame[2])) > PAR:
        return None
    nx, ny = dot(sn, parent_frame[0]), dot(sn, parent_frame[1])      # the plane's normal, in the parent view
    px, py = project(section_view.section, parent_frame)
    ux, uy = -ny, nx                                                 # along the trace
    x0, y0, x1, y1 = parent_lbox
    ts = [(cx - px) * ux + (cy - py) * uy for cx in (x0, x1) for cy in (y0, y1)]
    lo, hi = min(ts) - overhang, max(ts) + overhang
    # the viewer of the section stands on the +n side and looks towards -n
    return ((px + lo * ux, py + lo * uy), (px + hi * ux, py + hi * uy), (-nx, -ny))

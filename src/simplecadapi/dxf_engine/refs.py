"""dxf_engine.refs — geometry references: what a dimension measures, taken from the model.

A dimension that is declared with typed coordinates is only as right as the typing, and it stays where it was typed when
the model changes. A reference names model geometry instead (a vertex, an edge, a face, a selector that resolves to one
of them, or a 3D point); this module turns it into what the view shows of it, in view-local model coordinates:

  point    a vertex, a 3D point, a curve that the view sees end-on
  line     a straight edge; a plane face seen edge-on
  circle   a circular edge or a cylinder face whose axis is the viewing direction
  band     a cylinder face seen from the side: its axis segment and its radius (the two silhouette lines)

The projection is the one `hlr.hlr_project` uses: x = p · xd, y = p · (n × xd).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from simplecadapi._cpp.occt.BRep import BRep_Tool
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from simplecadapi._cpp.occt.GeomAbs import (GeomAbs_Circle, GeomAbs_Cylinder, GeomAbs_Line,
                                             GeomAbs_Plane)
from simplecadapi._cpp.occt.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from simplecadapi._cpp.occt.TopExp import TopExp_Explorer
from simplecadapi._cpp.occt.TopoDS import TopoDS

PAR = 1e-6          # |a · b| above 1 - PAR: parallel; below PAR: perpendicular


class RefError(ValueError):
    """A geometry reference that cannot be used the way the declaration uses it. The message says what the reference is,
    what the view shows of it, and what to reference instead."""


@dataclass(frozen=True)
class Ref2D:
    """What a view shows of one piece of model geometry (view-local model coordinates, before the drawing scale)."""
    kind: str                 # point | line | circle | band
    pts: tuple                # point/circle: (p,)   line/band: (a, b)
    radius: float | None = None
    desc: str = ""
    mid: float | None = None  # circle: direction (degrees) from the centre to the middle of an arc; None on a full circle


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def unit(v):
    n = math.sqrt(dot(v, v))
    if n < 1e-12:
        raise RefError(f"direction {v} has no length")
    return (v[0] / n, v[1] / n, v[2] / n)


def view_frame(n, xd):
    """(xd, yd, n) as unit vectors: screen right, screen up, towards the viewer."""
    n, xd = unit(n), unit(xd)
    if abs(dot(n, xd)) > 1e-6:
        raise RefError(f"view direction n={n} and screen-right xd={xd} must be perpendicular")
    return xd, cross(n, xd), n


def project(p, frame):
    """A 3D point → view-local (x, y)."""
    return (dot(p, frame[0]), dot(p, frame[1]))


def raw_shape(obj):
    """The OCCT shape of an SDK entity (`.wrapped`) or the shape itself."""
    return getattr(obj, "wrapped", obj)


def _xyz(p):
    return (p.X(), p.Y(), p.Z())


def _fmt(p):
    return "(" + ", ".join(f"{v:g}" for v in (round(c, 3) + 0.0 for c in p)) + ")"


def _vertices(shape):
    out, exp = [], TopExp_Explorer(shape, TopAbs_VERTEX)
    while exp.More():
        out.append(_xyz(BRep_Tool.Pnt_s(TopoDS.Vertex_s(exp.Current()))))
        exp.Next()
    return out


def _boundary_points(face, n=12):
    """Points on the boundary of a face: its vertices and samples of every edge (a disc has one vertex only)."""
    out, exp = list(_vertices(face)), TopExp_Explorer(face, TopAbs_EDGE)
    while exp.More():
        ad = BRepAdaptor_Curve(TopoDS.Edge_s(exp.Current()))
        t0, t1 = ad.FirstParameter(), ad.LastParameter()
        out += [_xyz(ad.Value(t0 + (t1 - t0) * i / n)) for i in range(n + 1)]
        exp.Next()
    return out


def _entity(ref, view):
    """Reference → one OCCT vertex/edge/face. A selector is resolved against the solid the view shows."""
    if hasattr(ref, "resolve"):
        handle = view.shape
        if not hasattr(handle, "wrapped"):
            raise RefError(
                f"view {view.name!r}: a selector reference needs the solid itself as ViewDecl.shape "
                "(pass `shape=part`, not `shape=part.wrapped`), so that the selector can be resolved against it")
        found = ref.resolve(handle)
        if len(found) != 1:
            raise RefError(
                f"view {view.name!r}: the selector resolves to {len(found)} entities, a reference needs exactly 1. "
                "Narrow it with one more predicate (position, size, tag), or pass the entity you mean")
        return found[0].wrapped
    return raw_shape(ref)


def resolve_ref(ref, view):
    """One reference → `Ref2D` in the view `view` (a ViewDecl)."""
    frame = view_frame(view.n, view.xd)
    if isinstance(ref, (tuple, list)):
        if len(ref) == 3:
            return Ref2D("point", (project(ref, frame),), desc=f"point {_fmt(ref)}")
        if len(ref) == 2:
            return Ref2D("point", ((float(ref[0]), float(ref[1])),), desc=f"view point {_fmt(ref)}")
        raise RefError(f"a point reference has 3 model coordinates (or 2 view-local ones), got {ref!r}")
    shape = _entity(ref, view)
    kind = shape.ShapeType()
    if kind == TopAbs_VERTEX:
        p = _xyz(BRep_Tool.Pnt_s(TopoDS.Vertex_s(shape)))
        return Ref2D("point", (project(p, frame),), desc=f"vertex {_fmt(p)}")
    if kind == TopAbs_EDGE:
        return _edge_ref(TopoDS.Edge_s(shape), frame)
    if kind == TopAbs_FACE:
        return _face_ref(TopoDS.Face_s(shape), frame, view.name)
    raise RefError("a reference is a vertex, an edge, a face, a selector of one of them, or a point; "
                   f"got {type(ref).__name__}")


def _edge_ref(edge, frame):
    ad = BRepAdaptor_Curve(edge)
    a, b = _xyz(ad.Value(ad.FirstParameter())), _xyz(ad.Value(ad.LastParameter()))
    gt = ad.GetType()
    if gt == GeomAbs_Line:
        pa, pb = project(a, frame), project(b, frame)
        if math.dist(pa, pb) < 1e-6:
            return Ref2D("point", (pa,), desc=f"edge LINE seen end-on at {_fmt(a)}")
        return Ref2D("line", (pa, pb), desc=f"edge LINE {_fmt(a)}–{_fmt(b)}")
    if gt == GeomAbs_Circle:
        circ = ad.Circle()
        c, r = _xyz(circ.Location()), circ.Radius()
        axis = _xyz(circ.Axis().Direction())
        if abs(dot(axis, frame[2])) > 1.0 - PAR:
            c2, mid = project(c, frame), None
            if math.dist(a, b) > 1e-6:
                m = project(_xyz(ad.Value(0.5 * (ad.FirstParameter() + ad.LastParameter()))), frame)
                mid = math.degrees(math.atan2(m[1] - c2[1], m[0] - c2[0]))
            return Ref2D("circle", (c2,), r, f"edge CIRCLE r={r:g} centre {_fmt(c)}", mid)
        return Ref2D("point", (project(c, frame),), desc=f"centre {_fmt(c)} of edge CIRCLE r={r:g} (seen obliquely)")
    mid = _xyz(ad.Value(0.5 * (ad.FirstParameter() + ad.LastParameter())))
    return Ref2D("point", (project(mid, frame),), desc=f"midpoint {_fmt(mid)} of a free-form edge")


def _face_ref(face, frame, view_name):
    sf = BRepAdaptor_Surface(face)
    gt = sf.GetType()
    verts = _vertices(face)
    if gt == GeomAbs_Plane:
        nrm = _xyz(sf.Plane().Axis().Direction())
        if abs(dot(nrm, frame[2])) > PAR:
            raise RefError(
                f"view {view_name!r}: the referenced plane face (normal {_fmt(nrm)}) is not seen edge-on, so it has no "
                "single position in this view. Reference it in a view whose direction lies in the face, or reference "
                "one of its edges")
        pts = [project(p, frame) for p in _boundary_points(face)]
        a, b = _extremes(pts)
        if math.dist(a, b) < 1e-9:
            return Ref2D("point", (a,), desc=f"plane face (normal {_fmt(nrm)}) seen as a point")
        return Ref2D("line", (a, b), desc=f"plane face (normal {_fmt(nrm)}) seen edge-on")
    if gt == GeomAbs_Cylinder:
        cyl = sf.Cylinder()
        r = cyl.Radius()
        loc, axis = _xyz(cyl.Axis().Location()), _xyz(cyl.Axis().Direction())
        along = dot(axis, frame[2])
        if abs(along) > 1.0 - PAR:
            c2, mid = project(loc, frame), None
            if sf.LastUParameter() - sf.FirstUParameter() < math.pi - 1e-3 and verts:     # a fillet, not a hole
                mx = sum(project(p, frame)[0] for p in verts) / len(verts) - c2[0]
                my = sum(project(p, frame)[1] for p in verts) / len(verts) - c2[1]
                if math.hypot(mx, my) > 1e-6:
                    mid = math.degrees(math.atan2(my, mx))
            return Ref2D("circle", (c2,), r, f"cylinder face r={r:g} axis through {_fmt(loc)}", mid)
        if abs(along) > PAR:
            raise RefError(
                f"view {view_name!r}: the referenced cylinder (axis {_fmt(axis)}) is seen obliquely; dimension it in a "
                "view along its axis or square to it")
        ts = [dot((p[0] - loc[0], p[1] - loc[1], p[2] - loc[2]), axis) for p in _boundary_points(face)]
        ends = [tuple(loc[i] + t * axis[i] for i in range(3)) for t in (min(ts), max(ts))]
        return Ref2D("band", (project(ends[0], frame), project(ends[1], frame)), r,
                     f"cylinder face r={r:g} seen from the side")
    raise RefError(f"view {view_name!r}: only plane and cylinder faces can be referenced; reference an edge or a "
                   "vertex of this face instead")


def _extremes(pts):
    """The two points of a collinear set that are farthest apart."""
    best = (pts[0], pts[0], -1.0)
    for i, p in enumerate(pts):
        for q in pts[i + 1:]:
            d = math.dist(p, q)
            if d > best[2]:
                best = (p, q, d)
    return best[0], best[1]


# ---------------------------------------------------------------------------
# linear measurement between two references
# ---------------------------------------------------------------------------

def _rep(ref):
    """A representative point of a reference (to choose the measuring direction)."""
    if ref.kind in ("point", "circle"):
        return ref.pts[0]
    a, b = ref.pts
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _dirn(ref):
    a, b = ref.pts
    d = math.dist(a, b)
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def measuring_axis(ra, rb, axis=None):
    """"x" (a horizontal dimension) or "y" (a vertical one). Declared, else square to a line reference, else the
    direction in which the two references are farther apart."""
    if axis in ("x", "y"):
        return axis
    if axis is not None:
        raise RefError(f"axis is 'x' (horizontal measurement) or 'y' (vertical), got {axis!r}")
    for r in (ra, rb):
        if r.kind in ("line", "band"):
            dx, dy = _dirn(r)
            if abs(dx) < 1e-6:
                return "x"
            if abs(dy) < 1e-6:
                return "y"
    pa, pb = _rep(ra), _rep(rb)
    return "x" if abs(pb[0] - pa[0]) >= abs(pb[1] - pa[1]) else "y"


def position(ref, axis):
    """Where the reference is along the measuring axis."""
    i = 0 if axis == "x" else 1
    if ref.kind in ("point", "circle"):
        return ref.pts[0][i]
    a, b = ref.pts
    if abs(a[i] - b[i]) > 1e-6:
        raise RefError(
            f"{ref.desc} runs from {_fmt(a)} to {_fmt(b)} in the view: it is not square to the "
            f"{'horizontal' if axis == 'x' else 'vertical'} measuring direction, so it has no single {axis} position. "
            "Use the other axis, or reference a vertex")
    return a[i]


def anchor(ref, axis, toward):
    """The point an extension line starts from: on a line reference, the end nearest the dimension line
    (`toward` is +1 or -1 along the other axis)."""
    if ref.kind in ("point", "circle"):
        return ref.pts[0]
    j = 1 if axis == "x" else 0
    a, b = ref.pts
    return a if toward * a[j] >= toward * b[j] else b


def silhouettes(band):
    """The two outline lines of a cylinder seen from the side, as line references."""
    a, b = band.pts
    dx, dy = _dirn(band)
    px, py, r = -dy * band.radius, dx * band.radius, band.radius
    return (Ref2D("line", ((a[0] + px, a[1] + py), (b[0] + px, b[1] + py)), desc=f"outline of {band.desc}"),
            Ref2D("line", ((a[0] - px, a[1] - py), (b[0] - px, b[1] - py)), desc=f"outline of {band.desc}"))

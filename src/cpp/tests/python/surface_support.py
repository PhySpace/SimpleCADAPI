"""Shared pieces of the surface parity tests.

REF_PRELUDE runs inside the reference interpreter; `measure` is its native twin.  Both
produce the same dictionary, so a golden file compares like with like.
"""

from __future__ import annotations

import simplecadapi._cpp as scad
from simplecadapi._cpp import _native

T = _native._surface_testing

REF_PRELUDE = '''
import math
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakePolygon
from simplecadapi._cpp.occt.GC import GC_MakeArcOfCircle
from simplecadapi._cpp.occt.GeomAPI import GeomAPI_Interpolate
from simplecadapi._cpp.occt.TColgp import TColgp_HArray1OfPnt
from simplecadapi._cpp.occt.gp import gp_Pnt
from simplecadapi.kernel.ocp_properties import bounding_box


def measure(shape):
    bb = bounding_box(shape.wrapped)
    out = {"kind": type(shape).__name__,
           "bbox": [bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax],
           "valid": bool(BRepCheck_Analyzer(shape.wrapped).IsValid())}
    if hasattr(shape, "get_area"):
        out["area"] = shape.get_area()
    if hasattr(shape, "get_volume"):
        out["volume"] = shape.get_volume()
    if type(shape).__name__ in ("Shell", "Solid"):
        out["faces"] = len(shape._iter_faces())
        out["edges"] = len(shape._iter_edges())
    if type(shape).__name__ == "Face":
        out["wires"] = len(shape._iter_wires())
    return out


def error_detail(call):
    try:
        call()
    except Exception as e:
        return str(e).splitlines()[-1]
    return None


def line(a, b):
    return scad.make_line_redge(a, b)


def arc(a, b, c):
    return scad.make_three_point_arc_redge(a, b, c)


def spline(points):
    return scad.make_interpolated_spline_redge(points=points, tolerance=1e-5)


def wire(edges):
    return scad.make_wire_from_edges_rwire(edges)


def rectangle(width, height, center=(0, 0, 0)):
    return scad.make_rectangle_rwire(width, height, center=center)


def circle(center, radius):
    return scad.make_circle_rwire(center, radius)
'''


def measure(shape):
    out = {"kind": type(shape).__name__, "bbox": list(T.bbox(shape)), "valid": bool(T.is_valid(shape))}
    if hasattr(shape, "get_area"):
        out["area"] = shape.get_area()
    if hasattr(shape, "get_volume"):
        out["volume"] = shape.get_volume()
    if out["kind"] in ("Shell", "Solid"):
        out["faces"] = len(shape.faces())
        out["edges"] = len(shape.edges())
    if out["kind"] == "Face":
        out["wires"] = len(shape.wires())
    return out


def error_detail(call):
    try:
        call()
    except Exception as e:
        return str(e).splitlines()[-1]
    return None


line = T.line
arc = T.arc
spline = T.spline
wire = T.wire
point = T.point


def rectangle(width, height, center=(0, 0, 0)):
    return T.rectangle(width, height, center)


def circle(center, radius):
    return T.circle(center, radius)


def close_to(got, expected, rel=1e-4, abs_=1e-6):
    """Recursive approximate equality; bbox corners are compared with an absolute floor."""
    from ref import close

    return close(got, expected, rel, abs_)

"""OCP-native topology traversal helpers."""

from __future__ import annotations

from typing import List

from simplecadapi._cpp.occt.BRep import BRep_Tool
from simplecadapi._cpp.occt.BRepTools import BRepTools
from simplecadapi._cpp.occt.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX, TopAbs_WIRE
from simplecadapi._cpp.occt.TopExp import TopExp_Explorer
from simplecadapi._cpp.occt.TopoDS import TopoDS, TopoDS_Edge, TopoDS_Face, TopoDS_Shape, TopoDS_Vertex, TopoDS_Wire


def vertices_of(shape: TopoDS_Shape) -> List[TopoDS_Vertex]:
    out: List[TopoDS_Vertex] = []
    explorer = TopExp_Explorer(shape, TopAbs_VERTEX)
    while explorer.More():
        out.append(TopoDS.Vertex_s(explorer.Current()))
        explorer.Next()
    return out


def edges_of(shape: TopoDS_Shape) -> List[TopoDS_Edge]:
    out: List[TopoDS_Edge] = []
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        out.append(TopoDS.Edge_s(explorer.Current()))
        explorer.Next()
    return out


def wires_of(shape: TopoDS_Shape) -> List[TopoDS_Wire]:
    out: List[TopoDS_Wire] = []
    explorer = TopExp_Explorer(shape, TopAbs_WIRE)
    while explorer.More():
        out.append(TopoDS.Wire_s(explorer.Current()))
        explorer.Next()
    return out


def faces_of(shape: TopoDS_Shape) -> List[TopoDS_Face]:
    out: List[TopoDS_Face] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        out.append(TopoDS.Face_s(explorer.Current()))
        explorer.Next()
    return out


def vertex_point(vertex: TopoDS_Vertex) -> tuple[float, float, float]:
    p = BRep_Tool.Pnt_s(vertex)
    return (float(p.X()), float(p.Y()), float(p.Z()))


def is_wire_closed(wire: TopoDS_Wire) -> bool:
    return bool(BRep_Tool.IsClosed_s(wire))


def outer_wire_of(face: TopoDS_Face) -> TopoDS_Wire:
    return BRepTools.OuterWire_s(face)


def inner_wires_of(face: TopoDS_Face) -> List[TopoDS_Wire]:
    outer = outer_wire_of(face)
    out: List[TopoDS_Wire] = []
    for wire in wires_of(face):
        if not wire.IsSame(outer):
            out.append(wire)
    return out

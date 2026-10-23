// Topology traversal on raw OCCT shapes (no semantic state).
//
// The orderings here are the ones the Python SDK exposes, because users and
// tests pick sub-shapes by index: TopExp_Explorer order, outer wire first.
#pragma once

#include <vector>

#include <TopAbs_ShapeEnum.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>

#include "scad/core/vec.hpp"

namespace scad::kernel {

// Every occurrence of `type` below `shape`, in TopExp_Explorer order.  A
// sub-shape that is shared (an edge used by two faces) appears once per use.
std::vector<TopoDS_Shape> explore(const TopoDS_Shape& shape, TopAbs_ShapeEnum type);

std::vector<TopoDS_Vertex> vertices_of(const TopoDS_Shape& shape);
std::vector<TopoDS_Edge> edges_of(const TopoDS_Shape& shape);
std::vector<TopoDS_Wire> wires_of(const TopoDS_Shape& shape);
std::vector<TopoDS_Face> faces_of(const TopoDS_Shape& shape);
std::vector<TopoDS_Solid> solids_of(const TopoDS_Shape& shape);

Vec3 vertex_point(const TopoDS_Vertex& vertex);
bool is_wire_closed(const TopoDS_Wire& wire);
TopoDS_Wire outer_wire_of(const TopoDS_Face& face);
// Every wire of the face except the outer one, in explorer order.
std::vector<TopoDS_Wire> inner_wires_of(const TopoDS_Face& face);

// True when the shell has no free boundary edge.
bool shell_is_closed(const TopoDS_Shape& shell);

}  // namespace scad::kernel

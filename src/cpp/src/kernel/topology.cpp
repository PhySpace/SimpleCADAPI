#include "scad/kernel/topology.hpp"

#include <BRepTools.hxx>
#include <BRep_Tool.hxx>
#include <TopoDS_Shell.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/convert.hpp"

namespace scad::kernel {

std::vector<TopoDS_Shape> explore(const TopoDS_Shape& shape, TopAbs_ShapeEnum type) {
  std::vector<TopoDS_Shape> out;
  if (shape.IsNull())
    return out;
  for (TopExp_Explorer ex(shape, type); ex.More(); ex.Next())
    out.push_back(ex.Current());
  return out;
}

namespace {
template <class T, class Cast>
std::vector<T> explore_as(const TopoDS_Shape& shape, TopAbs_ShapeEnum type, Cast cast) {
  std::vector<T> out;
  if (shape.IsNull())
    return out;
  for (TopExp_Explorer ex(shape, type); ex.More(); ex.Next())
    out.push_back(cast(ex.Current()));
  return out;
}
}  // namespace

std::vector<TopoDS_Vertex> vertices_of(const TopoDS_Shape& s) {
  return explore_as<TopoDS_Vertex>(s, TopAbs_VERTEX, [](const TopoDS_Shape& x) { return TopoDS::Vertex(x); });
}
std::vector<TopoDS_Edge> edges_of(const TopoDS_Shape& s) {
  return explore_as<TopoDS_Edge>(s, TopAbs_EDGE, [](const TopoDS_Shape& x) { return TopoDS::Edge(x); });
}
std::vector<TopoDS_Wire> wires_of(const TopoDS_Shape& s) {
  return explore_as<TopoDS_Wire>(s, TopAbs_WIRE, [](const TopoDS_Shape& x) { return TopoDS::Wire(x); });
}
std::vector<TopoDS_Face> faces_of(const TopoDS_Shape& s) {
  return explore_as<TopoDS_Face>(s, TopAbs_FACE, [](const TopoDS_Shape& x) { return TopoDS::Face(x); });
}
std::vector<TopoDS_Solid> solids_of(const TopoDS_Shape& s) {
  auto out = explore_as<TopoDS_Solid>(s, TopAbs_SOLID, [](const TopoDS_Shape& x) { return TopoDS::Solid(x); });
  if (out.empty() && !s.IsNull() && s.ShapeType() == TopAbs_SOLID)
    out.push_back(TopoDS::Solid(s));
  return out;
}

Vec3 vertex_point(const TopoDS_Vertex& vertex) {
  return from_pnt(BRep_Tool::Pnt(vertex));
}

bool is_wire_closed(const TopoDS_Wire& wire) {
  return BRep_Tool::IsClosed(wire);
}

TopoDS_Wire outer_wire_of(const TopoDS_Face& face) {
  return BRepTools::OuterWire(face);
}

std::vector<TopoDS_Wire> inner_wires_of(const TopoDS_Face& face) {
  const TopoDS_Wire outer = outer_wire_of(face);
  std::vector<TopoDS_Wire> out;
  for (const TopoDS_Wire& wire : wires_of(face)) {
    if (!wire.IsSame(outer))
      out.push_back(wire);
  }
  return out;
}

bool shell_is_closed(const TopoDS_Shape& shell) {
  return BRep_Tool::IsClosed(TopoDS::Shell(shell));
}

}  // namespace scad::kernel

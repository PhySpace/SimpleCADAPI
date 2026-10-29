// Raw OpenCASCADE builders the surface tests feed the operators with.
#pragma once

#include <cmath>
#include <vector>

#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <gp_Circ.hxx>

#include "scad/surface/types.hpp"
#include "scad/topo/shape.hpp"

namespace surface_test {

using scad::Edge;
using scad::Face;
using scad::Solid;
using scad::Vec3;
using scad::Vertex;
using scad::Wire;

inline Edge line(Vec3 a, Vec3 b) {
  return Edge(BRepBuilderAPI_MakeEdge(gp_Pnt(a.x, a.y, a.z), gp_Pnt(b.x, b.y, b.z)).Edge());
}

inline Edge arc(Vec3 a, Vec3 b, Vec3 c) {
  return Edge(BRepBuilderAPI_MakeEdge(
                  GC_MakeArcOfCircle(gp_Pnt(a.x, a.y, a.z), gp_Pnt(b.x, b.y, b.z), gp_Pnt(c.x, c.y, c.z)).Value())
                  .Edge());
}

inline Wire wire_of(const std::vector<Edge>& edges) {
  BRepBuilderAPI_MakeWire builder;
  for (const Edge& e : edges)
    builder.Add(TopoDS::Edge(e.wrapped()));
  return Wire(builder.Wire());
}

inline Wire polygon(const std::vector<Vec3>& points, bool closed = true) {
  BRepBuilderAPI_MakePolygon builder;
  for (const Vec3& p : points)
    builder.Add(gp_Pnt(p.x, p.y, p.z));
  if (closed)
    builder.Close();
  return Wire(builder.Wire());
}

// A rectangle in a plane z = `z`, centred on (cx, cy).
inline Wire rectangle(double width, double height, double cx = 0, double cy = 0, double z = 0) {
  return polygon({{cx - width / 2, cy - height / 2, z},
                  {cx + width / 2, cy - height / 2, z},
                  {cx + width / 2, cy + height / 2, z},
                  {cx - width / 2, cy + height / 2, z}});
}

inline Wire circle(double radius, double z = 0) {
  return Wire(
      BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)), radius)).Edge())
          .Wire());
}

inline Vertex point(double x, double y, double z) {
  return Vertex(BRepBuilderAPI_MakeVertex(gp_Pnt(x, y, z)).Vertex());
}

inline Solid box(double x, double y, double z) {
  return Solid(BRepPrimAPI_MakeBox(x, y, z).Solid());
}

inline scad::PointGrid unit_square_grid(double z11 = 0.0) {
  return {{{0, 0, 0}, {0, 1, 0}}, {{1, 0, 0}, {1, 1, z11}}};
}

// A 6 x 6 planar bezier carrier centred on the origin.
inline scad::PointGrid carrier_grid() {
  return {{{-3, -3, 0}, {-3, 3, 0}}, {{3, -3, 0}, {3, 3, 0}}};
}

}  // namespace surface_test

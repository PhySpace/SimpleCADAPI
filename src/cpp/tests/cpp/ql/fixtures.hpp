// Raw-OCCT shapes for the QL tests: the real operators live in other areas.
#pragma once

#include <BRepAlgoAPI_Cut.hxx>
#include <BRep_Builder.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Ax2.hxx>

#include <algorithm>
#include <string>
#include <vector>

#include "scad/core/vec.hpp"
#include "scad/topo/shape.hpp"

namespace ql_test {

inline scad::Solid box(double dx, double dy, double dz, scad::Vec3 origin = {}) {
  return scad::Solid(BRepPrimAPI_MakeBox(gp_Pnt(origin.x, origin.y, origin.z), dx, dy, dz).Solid());
}

// Axis +Z, base centre at `base`.
inline scad::Solid cylinder(double radius, double height, scad::Vec3 base = {}) {
  const gp_Ax2 axis(gp_Pnt(base.x, base.y, base.z), gp_Dir(0, 0, 1));
  return scad::Solid(BRepPrimAPI_MakeCylinder(axis, radius, height).Solid());
}

inline scad::Solid cut(const scad::Solid& body, const scad::Solid& tool) {
  BRepAlgoAPI_Cut op(body.wrapped(), tool.wrapped());
  TopExp_Explorer solids(op.Shape(), TopAbs_SOLID);
  return scad::Solid(TopoDS::Solid(solids.Current()));
}

// A 20 mm tall rod of radius 10 with a groove (radius 9) cut around its middle: the rod's side is
// two cylindrical bands of one surface.
inline scad::Solid split_band_solid() {
  const scad::Solid rod = cylinder(10, 20);
  const scad::Solid ring = cylinder(12, 6, {0, 0, 7});
  const scad::Solid inner = cylinder(9, 10, {0, 0, 5});
  return cut(rod, cut(ring, inner));
}

template <class T>
std::vector<std::string> ids(const std::vector<T>& shapes) {
  std::vector<std::string> out;
  for (const auto& s : shapes) out.push_back(s.topo_id());
  return out;
}

inline scad::Compound compound_of(const std::vector<scad::Solid>& solids) {
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);
  for (const scad::Solid& solid : solids) builder.Add(compound, solid.wrapped());
  return scad::Compound(compound);
}

}  // namespace ql_test

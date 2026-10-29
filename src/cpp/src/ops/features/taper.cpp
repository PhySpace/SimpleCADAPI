// extrude_taper_rsolid (operators/features.py).
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepOffsetAPI_MakeOffset.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepTools.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <LocOpe_DPrism.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>

#include <cmath>

#include "internal.hpp"
#include "scad/kernel/booleans.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ops/features/extrusion.hpp"

namespace scad {

namespace {

// The loft of `wire` to its planar offset moved by `move`: one tapered layer.
// occt_guard: the caller extrude_taper_rsolid runs this inside occt_guard.
TopoDS_Shape tapered_layer(const TopoDS_Wire& wire, double offset, const gp_Trsf& move) {
  BRepOffsetAPI_MakeOffset offsetter(wire, GeomAbs_Intersection, false);
  offsetter.Perform(offset);
  if (!offsetter.IsDone())
    throw ValueError("taper collapses a profile loop");
  const std::vector<TopoDS_Wire> found = kernel::wires_of(offsetter.Shape());
  if (found.size() != 1)
    throw ValueError("taper changes loop connectivity");
  const TopoDS_Shape moved = BRepBuilderAPI_Transform(found.front(), move, true).Shape();

  BRepOffsetAPI_ThruSections loft(true, false);
  loft.AddWire(wire);
  loft.AddWire(TopoDS::Wire(moved));
  loft.Build();
  if (!loft.IsDone())
    throw ValueError("kernel could not build tapered sections");
  return loft.Shape();
}

}  // namespace

Solid extrude_taper_rsolid(const Face& profile, const Scalar3& vector, const Scalar& taper, bool flip_inner) {
  const Vec3 values = finite_vector(vector, "vector");
  const double angle = evaluate_finite(taper);
  if (!std::isfinite(angle) || std::abs(angle) >= 90)
    throw ValueError("taper must be finite and between -90 and 90 degrees");
  const Vec3 displacement = features_detail::place_vector(values);
  const double length = displacement.norm();
  if (length <= 1e-12)
    throw ValueError("extrusion vector must be nonzero");

  const TopoDS_Face face = TopoDS::Face(profile.wrapped());
  if (occt_guard([&] { return BRepAdaptor_Surface(face, true).GetType(); }) != GeomAbs_Plane) {
    throw ValueError("taper extrusion requires a planar profile");
  }
  const Vec3 normal = profile.normal_at();

  const TopoDS_Shape shape = occt_guard([&]() -> TopoDS_Shape {
    const TopoDS_Wire outer = BRepTools::OuterWire(face);
    std::vector<TopoDS_Wire> wires{outer};
    for (const TopoDS_Wire& wire : kernel::wires_of(face)) {
      if (!wire.IsSame(outer))
        wires.push_back(wire);
    }
    const gp_Vec move_vector = kernel::to_vec(displacement);
    const double radians = angle * kPi / 180.0;
    if (angle == 0)
      return BRepPrimAPI_MakePrism(face, move_vector).Shape();
    if ((displacement / length - normal).norm() < 1e-8 && normal.z > 0 && wires.size() == 1 && angle > 0) {
      return LocOpe_DPrism(face, length / std::cos(radians), radians).Shape();
    }

    // Offset in the profile plane, then translate the final section.
    gp_Trsf move;
    move.SetTranslation(move_vector);
    TopoDS_Shape result;
    for (std::size_t i = 0; i < wires.size(); ++i) {
      // Inner wires wind opposite to the outer boundary: normalize their winding so that
      // flip_inner controls geometry rather than kernel wire orientation.
      const TopoDS_Wire wire = i == 0 ? wires[i] : TopoDS::Wire(wires[i].Reversed());
      const double offset = -length * std::tan(radians) * (i > 0 && flip_inner ? -1 : 1);
      const TopoDS_Shape layer = tapered_layer(wire, offset, move);
      if (i == 0) {
        result = layer;
        continue;
      }
      BRepAlgoAPI_Cut cut(result, layer);
      cut.Build();
      if (!cut.IsDone())
        throw ValueError("kernel could not subtract tapered inner loop");
      result = cut.Shape();
    }
    return result;
  });

  FeatureRecord rec("make_extrude_taper_rsolid");
  rec.point("vector", vector);
  rec.scalar("taper", taper);
  rec.param("flip_inner", Value(flip_inner)).input(profile, "profile");
  return finish_solid(profile, shape, std::move(rec).take());
}

}  // namespace scad

// sweep_multisection_rsolid (operators/features.py).
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepTools.hxx>
#include <gp_Dir.hxx>

#include "internal.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/ops/features/sweeps.hpp"

namespace scad {

Solid sweep_multisection_rsolid(const std::vector<Shape>& profiles, const Wire& path, bool is_frenet,
                                const std::optional<Binormal>& binormal) {
  if (profiles.size() < 2) throw ValueError("multi-section sweep requires at least two sections");

  FeatureRecord rec("make_sweep_multisection_rsolid");
  const TopoDS_Shape built = occt_guard([&]() -> TopoDS_Shape {
    BRepOffsetAPI_MakePipeShell builder(TopoDS::Wire(path.wrapped()));
    bool rotate = false;
    std::optional<Wire> spine;
    std::optional<Scalar3> direction;
    if (binormal) {
      if (const Wire* wire = std::get_if<Wire>(&*binormal)) spine = *wire;
      else direction = std::get<Scalar3>(*binormal);
    }
    if (spine) {
      builder.SetMode(TopoDS::Wire(spine->wrapped()), true);
    } else if (direction) {
      const Vec3 values = finite_vector(*direction, "binormal");
      const Vec3 placed = features_detail::place_vector(values);
      if (placed.norm() < 1e-12) throw ValueError("binormal direction must be nonzero");
      builder.SetMode(kernel::to_dir(placed, "binormal"));
      rotate = true;
    } else {
      builder.SetMode(static_cast<Standard_Boolean>(is_frenet));
    }
    for (const Shape& section : profiles) {
      if (section.kind() != Kind::Face && section.kind() != Kind::Wire) throw TypeError("sections must be Face or Wire");
      const TopoDS_Shape wire = section.kind() == Kind::Face ? TopoDS_Shape(BRepTools::OuterWire(TopoDS::Face(section.wrapped())))
                                                             : section.wrapped();
      builder.Add(wire, false, rotate);
    }
    builder.Build();
    if (!builder.IsDone() || !builder.MakeSolid()) throw ValueError("kernel could not make a solid multi-section sweep");

    rec.param("profile_count", Value(static_cast<std::int64_t>(profiles.size()))).param("is_frenet", Value(is_frenet));
    rec.param("binormal", Value());
    if (spine) {
      rec.param("binormal_is_wire", Value(true));
    } else if (direction) {
      rec.point("binormal", *direction);
    }
    return builder.Shape();
  });

  rec.inputs(profiles, "profile").input(path, "path");
  if (binormal) {
    if (const Wire* wire = std::get_if<Wire>(&*binormal)) rec.input(*wire, "binormal");
  }
  return finish_solid(profiles.front(), built, std::move(rec).take());
}

}  // namespace scad

#include "scad/kernel/features.hpp"

#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopoDS.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/curves.hpp"
#include "scad/kernel/transforms.hpp"

namespace scad::kernel {

TopoDS_Face make_face_from_wire(const TopoDS_Wire& wire) {
  return occt_guard([&] {
    BRepBuilderAPI_MakeFace builder(wire, /*OnlyPlane=*/true);
    if (!builder.IsDone())
      throw ValueError("OCP face builder failed");
    return builder.Face();
  });
}

TopoDS_Face make_face_from_wires(const TopoDS_Wire& outer_wire, const std::vector<TopoDS_Wire>& inner_wires) {
  return occt_guard([&] {
    BRepBuilderAPI_MakeFace builder(outer_wire, /*OnlyPlane=*/true);
    if (!builder.IsDone())
      throw ValueError("OCP face builder failed for outer wire");
    for (const TopoDS_Wire& inner : inner_wires) {
      builder.Add(TopoDS::Wire(inner.Reversed()));
      if (!builder.IsDone())
        throw ValueError("OCP face builder failed while adding inner wire");
    }
    return builder.Face();
  });
}

TopoDS_Shape make_loft_solid(const std::vector<TopoDS_Shape>& sections, bool ruled) {
  // ThruSections crashes the process on a single section instead of failing.
  if (sections.size() < 2)
    throw ValueError("loft requires at least two sections");
  return occt_guard([&] {
    BRepOffsetAPI_ThruSections builder(/*isSolid=*/true, ruled);
    builder.CheckCompatibility(true);
    for (const TopoDS_Shape& section : sections) {
      if (section.IsNull())
        throw TypeError("loft sections must contain only vertices or wires");
      switch (section.ShapeType()) {
        case TopAbs_VERTEX:
          builder.AddVertex(TopoDS::Vertex(section));
          break;
        case TopAbs_WIRE:
          builder.AddWire(TopoDS::Wire(section));
          break;
        default:
          throw TypeError("loft sections must contain only vertices or wires");
      }
    }
    builder.Build();
    if (!builder.IsDone())
      throw ValueError("OCP loft builder failed");
    return builder.Shape();
  });
}

TopoDS_Shape make_sweep_solid(const TopoDS_Wire& profile_wire, const TopoDS_Wire& path_wire, bool is_frenet) {
  return occt_guard([&] {
    BRepOffsetAPI_MakePipeShell builder(path_wire);
    builder.SetMode(is_frenet);
    builder.Add(profile_wire, /*WithContact=*/false, /*WithCorrection=*/false);
    builder.Build();
    if (!builder.IsDone())
      throw ValueError("OCP sweep builder failed");
    if (!builder.MakeSolid())
      throw ValueError("OCP sweep solid conversion failed");
    return builder.Shape();
  });
}

TopoDS_Shape make_helical_sweep_solid(const TopoDS_Wire& profile_wire, double pitch, double height, double radius,
                                      const Vec3& center, const Vec3& direction,
                                      const std::optional<Vec3>& x_direction) {
  const TopoDS_Wire helix = make_helix_wire(pitch, height, radius, center, direction, x_direction);
  const Vec3 radial = x_direction ? *x_direction : Vec3{1.0, 0.0, 0.0};
  const TopoDS_Shape moved = translate_shape(profile_wire, radial * radius);
  return make_sweep_solid(TopoDS::Wire(moved), helix, /*is_frenet=*/true);
}

}  // namespace scad::kernel

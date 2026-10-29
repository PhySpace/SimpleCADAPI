// tracked_extrude / tracked_revolve: a face swept into a solid.  Edges of the
// profile become side faces ("Generated"); the swept shape's first and last
// positions are the caps.
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <gp_Ax1.hxx>
#include <gp_Vec.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/cast.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/semantic/tracking.hpp"
#include "tracking_detail.hpp"

namespace scad {

namespace {

// History of the profile's edges into the swept `result`, then the cap roles
// from `sweep.FirstShape/LastShape(profile)`.
template <class Sweep>
TrackedResult track_swept_profile(Sweep& sweep, const Face& profile, const Solid& result, std::string_view side_role,
                                  std::string_view start_role, std::string_view end_role) {
  tracking::DeltaBuilder delta;
  kernel::SubShapeIndex in_result(result.wrapped());

  tracking::BuilderHistory history(sweep);
  tracking::QuerySpec spec;
  spec.origin_role = "profile";
  spec.kind = Kind::Edge;
  spec.result = &in_result;
  spec.generated_role = side_role;
  spec.project_source_tags = true;
  tracking::query_sub_shape_history(history, profile.wrapped(), TopAbs_EDGE, spec, delta.witnesses);
  tracking::add_roles_from_history(delta.roles, delta.witnesses, "Generated");

  tracking::add_operation_role(delta.roles, in_result, sweep.FirstShape(profile.wrapped()), start_role, "FirstShape",
                               "profile");
  tracking::add_operation_role(delta.roles, in_result, sweep.LastShape(profile.wrapped()), end_role, "LastShape",
                               "profile");
  return tracking::to_result(result, std::move(delta));
}

}  // namespace

TrackedResult tracked_extrude(const Face& profile, const Vec3& direction, double distance) {
  const double norm = direction.norm();
  if (norm <= 1e-15)
    throw ValueError("Extrude direction cannot be zero-length");
  const Vec3 offset = direction / norm * distance;

  return occt_guard([&] {
    BRepPrimAPI_MakePrism prism(profile.wrapped(), gp_Vec(offset.x, offset.y, offset.z));
    prism.Build();
    if (!prism.IsDone())
      throw ValueError("Extrude failed: OCC build did not complete");
    const Solid result(kernel::as_solid(prism.Shape()));
    return track_swept_profile(prism, profile, result, "extrusion.side", "extrusion.start", "extrusion.end");
  });
}

TrackedResult tracked_revolve(const Face& profile, const Vec3& axis, const Vec3& origin, double angle_degrees) {
  return occt_guard([&] {
    const gp_Ax1 revolution_axis(kernel::to_pnt(origin), kernel::to_dir(axis, "revolve axis"));
    BRepPrimAPI_MakeRevol revolve(profile.wrapped(), revolution_axis, angle_degrees * kPi / 180.0,
                                  /*Copy=*/true);
    revolve.Build();
    if (!revolve.IsDone())
      throw ValueError("Revolve failed: OCC build did not complete");
    const Solid result(kernel::as_solid(revolve.Shape()));
    return track_swept_profile(revolve, profile, result, "revolution.side", "revolution.start", "revolution.end");
  });
}

}  // namespace scad

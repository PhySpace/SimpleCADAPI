// tracked_box / tracked_cylinder / tracked_cone: the primitive's own faces and
// edges, named by the kernel that built them.
#include "scad/core/error.hpp"
#include "scad/kernel/builders.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/semantic/tracking.hpp"
#include "tracking_detail.hpp"

namespace scad {

namespace {

TrackedResult from_primitive(const kernel::PrimitiveBuild& built) {
  return occt_guard([&] {
    tracking::DeltaBuilder delta;
    const Solid solid(built.solid);
    kernel::SubShapeIndex result(built.solid);
    for (const kernel::PrimitiveRoleWitness& witness : built.roles) {
      tracking::add_operation_role(delta.roles, result, witness.shape, witness.role, witness.evidence_method);
    }
    return tracking::to_result(solid, std::move(delta));
  });
}

}  // namespace

TrackedResult tracked_box(const Vec3& corner, double width, double height, double depth,
                          const std::optional<kernel::Axes3>& axes) {
  return from_primitive(kernel::build_box_primitive(corner, width, height, depth, axes));
}

TrackedResult tracked_cylinder(const Vec3& origin, const Vec3& axis, double radius, double height) {
  return from_primitive(kernel::build_cylinder_primitive(origin, axis, radius, height));
}

TrackedResult tracked_cone(const Vec3& origin, const Vec3& axis, double bottom_radius, double top_radius,
                           double height) {
  return from_primitive(kernel::build_cone_primitive(origin, axis, bottom_radius, top_radius, height));
}

}  // namespace scad

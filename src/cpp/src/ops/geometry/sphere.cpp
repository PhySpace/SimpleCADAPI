#include "internal.hpp"
#include "scad/kernel/builders.hpp"
#include "scad/ops/geometry/primitives.hpp"

namespace scad {

using namespace geometry_detail;

Solid make_sphere_rsolid(const Scalar& radius, const Scalar3& center) {
  static constexpr const char* kOp = "make_sphere_rsolid";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a sphere solid.",
      {"The radius is not a positive finite scalar.", "The center is not a valid finite 3D point.",
       "The kernel rejected the sphere definition."},
      {"Use a radius greater than zero.", "Pass center as a finite 3D tuple.",
       "If the center is expression-driven, inspect the evaluated coordinates."}};
  return guarded(kSpec, [&] {
    const double r = evaluate_scalar(radius, "radius");
    if (r <= 0)
      throw ValueError("The radius must be greater than zero");
    const Vec3 local_center = evaluate_point(center, "center");

    Solid solid(kernel::make_sphere_solid(current_cs().transform_point(local_center), r));
    solid.auto_tag_faces("sphere");
    solid.apply_tag("geom.primitive.sphere", false);
    solid.add_tag("sphere");
    solid.set_metadata(
        "geo", Value(Value::Object{
                   {"type", Value("sphere")},
                   {"radius", Value(r)},
                   {"center", Value::tuple({Value(local_center.x), Value(local_center.y), Value(local_center.z)})}}));
    return finalize_primitive_with(std::move(solid), kOp, [&] {
      return OpParams(kOp, primitive_labels("solid")).scalar("radius", radius).point("center", center).take();
    });
  });
}

}  // namespace scad

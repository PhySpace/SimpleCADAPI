// make_cylinder_rsolid and make_cone_rsolid: primitives that rise along an axis.
#include <string>

#include "internal.hpp"
#include "scad/ops/geometry/primitives.hpp"
#include "scad/semantic/tracking.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

Value vector_value(const Vec3& v) {
  return Value::tuple({Value(v.x), Value(v.y), Value(v.z)});
}

// "<family>.start" ... "<family>.seam": the six role tags both primitives share.
OutputTags output_tags(const std::string& family, const AxialSolidTags& tags) {
  return {.tag_prefix = tags.tag_prefix,
          .result_tag = tags.result_tag,
          .roles = {{family + ".start", tags.start_face_tag},
                    {family + ".end", tags.end_face_tag},
                    {family + ".side", tags.side_face_tag},
                    {family + ".start_boundary", tags.start_edge_tag},
                    {family + ".end_boundary", tags.end_edge_tag},
                    {family + ".seam", tags.seam_edge_tag}}};
}

FeatureRoles feature_roles(const std::string& family, bool has_end_face) {
  return {
      .start = family + ".start",
      .end = has_end_face ? family + ".end" : std::string(),
      .side = family + ".side",
      .edges = {{family + ".start_boundary", "start"}, {family + ".end_boundary", "end"}, {family + ".seam", "seam"}}};
}

// The pose of an axial primitive in world coordinates, plus the local values the "geo"
// metadata keeps.
struct AxialPose {
  Vec3 center_local, axis_local;
  Vec3 center, axis;
};

AxialPose axial_pose(const Scalar3& bottom_face_center, const Scalar3& axis) {
  const CoordinateSystem& cs = current_cs();
  AxialPose pose;
  pose.center_local = evaluate_point(bottom_face_center, "bottom_face_center");
  pose.axis_local = evaluate_point(axis, "axis");
  pose.center = cs.transform_point(pose.center_local);
  pose.axis = cs.transform_vector(pose.axis_local);
  return pose;
}

}  // namespace

Solid make_cylinder_rsolid(const Scalar& radius, const Scalar& height, const Scalar3& bottom_face_center,
                           const Scalar3& axis, const AxialSolidTags& tags) {
  static constexpr const char* kOp = "make_cylinder_rsolid";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a cylinder solid.",
      {"Radius or height is not a positive finite scalar.",
       "The bottom face center or axis is not a valid finite 3D vector.",
       "The axis is degenerate or rejected by the kernel."},
      {"Use radius and height values greater than zero.", "Pass a valid bottom_face_center and a non-zero axis vector.",
       "If the axis is computed dynamically, inspect its evaluated numeric value."}};
  return guarded(kSpec, [&] {
    OutputTags output = output_tags("cylinder", tags);
    plan_output_tags(kOp, output);

    const double r = evaluate_scalar(radius, "radius");
    const double h = evaluate_scalar(height, "height");
    if (r <= 0 || h <= 0)
      throw ValueError("The radius and height must be greater than zero");
    const AxialPose pose = axial_pose(bottom_face_center, axis);
    TrackedResult tracked = tracked_cylinder(pose.center, pose.axis, r, h);

    Solid solid(tracked.shape);
    solid.auto_tag_faces("cylinder");
    solid.apply_tag("geom.primitive.cylinder", false);
    solid.add_tag("cylinder");
    solid.set_metadata("geo", Value(Value::Object{{"type", Value("cylinder")},
                                                  {"radius", Value(r)},
                                                  {"height", Value(h)},
                                                  {"bottom_face_center", vector_value(pose.center_local)},
                                                  {"axis", vector_value(pose.axis_local)}}));

    FinalizeSpec spec{.record = record_for(kOp,
                                           [&] {
                                             return OpParams(kOp)
                                                 .scalar("radius", radius)
                                                 .scalar("height", height)
                                                 .point("bottom_face_center", bottom_face_center)
                                                 .point("axis", axis)
                                                 .take();
                                           }),
                      .tags = std::move(output),
                      .roles = feature_roles("cylinder", true)};
    return finalize_tracked_solid(std::move(tracked), std::move(spec));
  });
}

Solid make_cone_rsolid(const Scalar& bottom_radius, const Scalar& height, const Scalar& top_radius,
                       const Scalar3& bottom_face_center, const Scalar3& axis, const AxialSolidTags& tags) {
  static constexpr const char* kOp = "make_cone_rsolid";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a cone or truncated cone solid.",
      {"Bottom radius or height is not a positive finite scalar.",
       "The bottom face center or axis is not a valid finite 3D vector.",
       "The kernel rejected the cone dimensions or orientation."},
      {"Use a positive bottom radius and a positive height.", "Pass a valid center point and non-zero axis vector.",
       "If top_radius is used, make sure it is a finite scalar."}};
  return guarded(kSpec, [&] {
    OutputTags output = output_tags("cone", tags);
    plan_output_tags(kOp, output);

    const double bottom = evaluate_scalar(bottom_radius, "bottom_radius");
    const double h = evaluate_scalar(height, "height");
    const double top = evaluate_scalar(top_radius, "top_radius");
    if (bottom <= 0 || h <= 0)
      throw ValueError("The base radius and height must be greater than zero");
    const AxialPose pose = axial_pose(bottom_face_center, axis);
    TrackedResult tracked = tracked_cone(pose.center, pose.axis, bottom, top, h);

    Solid solid(tracked.shape);
    solid.apply_tag("geom.primitive.cone", false);
    solid.add_tag("cone");
    solid.set_metadata("geo", Value(Value::Object{{"type", Value("cone")},
                                                  {"bottom_radius", Value(bottom)},
                                                  {"top_radius", Value(top)},
                                                  {"height", Value(h)},
                                                  {"bottom_face_center", vector_value(pose.center_local)},
                                                  {"axis", vector_value(pose.axis_local)}}));

    FinalizeSpec spec{.record = record_for(kOp,
                                           [&] {
                                             return OpParams(kOp)
                                                 .scalar("bottom_radius", bottom_radius)
                                                 .scalar("top_radius", top_radius)
                                                 .scalar("height", height)
                                                 .point("bottom_face_center", bottom_face_center)
                                                 .point("axis", axis)
                                                 .take();
                                           }),
                      .tags = std::move(output),
                      .roles = feature_roles("cone", top > 0.0)};
    return finalize_tracked_solid(std::move(tracked), std::move(spec));
  });
}

}  // namespace scad

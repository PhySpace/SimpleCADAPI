#include "internal.hpp"
#include "scad/ops/geometry/primitives.hpp"
#include "scad/semantic/tracking.hpp"

namespace scad {

using namespace geometry_detail;

Solid make_box_rsolid(const Scalar& width, const Scalar& height, const Scalar& depth, const Scalar3& bottom_face_center,
                      const BoxTags& tags) {
  static constexpr const char* kOp = "make_box_rsolid";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a box solid.",
      {"Width, height, or depth is not a positive finite scalar.",
       "The bottom face center is not a valid finite 3D point.",
       "The kernel rejected the box dimensions or placement."},
      {"Use width, height, and depth values greater than zero.", "Pass bottom_face_center as a finite 3D tuple.",
       "If dimensions come from expressions, inspect the evaluated numeric values."}};
  return guarded(kSpec, [&] {
    OutputTags output{.tag_prefix = tags.tag_prefix,
                      .result_tag = tags.result_tag,
                      .roles = {{"box.bottom", tags.bottom_face_tag},
                                {"box.top", tags.top_face_tag},
                                {"box.front", tags.front_face_tag},
                                {"box.back", tags.back_face_tag},
                                {"box.left", tags.left_face_tag},
                                {"box.right", tags.right_face_tag}}};
    plan_output_tags(kOp, output);

    const double w = evaluate_scalar(width, "width");
    const double h = evaluate_scalar(height, "height");
    const double d = evaluate_scalar(depth, "depth");
    if (w <= 0 || h <= 0 || d <= 0)
      throw ValueError("width, height, and depth must be greater than zero.");

    const CoordinateSystem& cs = current_cs();
    const Vec3 center = evaluate_point(bottom_face_center, "bottom_face_center");
    const Vec3 corner = cs.transform_point(center) - cs.x_axis() * (w / 2.0) - cs.y_axis() * (h / 2.0);
    TrackedResult tracked = tracked_box(corner, w, h, d, kernel::Axes3{cs.x_axis(), cs.y_axis(), cs.z_axis()});

    Solid solid(tracked.shape);
    solid.auto_tag_faces("box");
    solid.apply_tag("geom.primitive.box", false);
    solid.add_tag("box");
    solid.set_metadata("geo",
                       Value(Value::Object{
                           {"type", Value("box")},
                           {"size", Value(Value::Object{{"x", Value(w)}, {"y", Value(h)}, {"z", Value(d)}})},
                           {"bottom_face_center", Value::tuple({Value(center.x), Value(center.y), Value(center.z)})}}));

    FinalizeSpec spec{.record = record_for(kOp,
                                           [&] {
                                             return OpParams(kOp)
                                                 .scalar("width", width)
                                                 .scalar("height", height)
                                                 .scalar("depth", depth)
                                                 .point("bottom_face_center", bottom_face_center)
                                                 .take();
                                           }),
                      .tags = std::move(output),
                      .roles = {.faces = {{"box.bottom", "bottom"},
                                          {"box.top", "top"},
                                          {"box.front", "front"},
                                          {"box.back", "back"},
                                          {"box.left", "left"},
                                          {"box.right", "right"}}}};
    return finalize_tracked_solid(std::move(tracked), std::move(spec));
  });
}

}  // namespace scad

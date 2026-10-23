// translate_shape, rotate_shape, mirror_shape (operators/transform.py).
#include "scad/ops/features/transforms.hpp"

#include "internal.hpp"
#include "scad/kernel/transforms.hpp"
#include "scad/semantic/tracking.hpp"

namespace scad {

namespace {

constexpr const char* kTranslateOp = "make_translate_rshape";
constexpr const char* kRotateOp = "make_rotate_rshape";
constexpr const char* kMirrorOp = "make_mirror_rshape";

const ErrorSpec& translate_spec() {
  static const ErrorSpec spec{
      "translate_shape",
      "Failed to translate the shape.",
      {"The shape is invalid or has been corrupted by an earlier operation.",
       "The translation vector is not a valid finite 3D vector.", "The kernel rejected the transform."},
      {"Pass a valid SimpleCAD shape object.", "Pass vector as a finite 3-element tuple or expression-backed vector.",
       "Inspect the shape and vector values before retrying."}};
  return spec;
}

// A solid result is finished through the tracking layer (its faces and edges follow `source`);
// any other shape is moved raw, keeping its runtime state, and recorded as it is.
Solid finish_tracked_transform(TrackedResult tracked, const Shape& source, FeatureRecord& rec, std::string_view op) {
  inherit_metadata(tracked.shape, {&source});
  attach_lineage_from_source(source, tracked.shape, LineageDerivation::Continuation, op);
  FinalizeSpec spec;
  spec.record = std::move(rec.input(source, "shape")).take();
  return finalize_tracked_solid(std::move(tracked), std::move(spec));
}

Shape finish_raw_transform(Shape result, const Shape& source, std::string_view op) {
  inherit_metadata(result, {&source});
  copy_runtime_state(source, result);
  attach_lineage_from_source(source, result, LineageDerivation::Continuation, op);
  return result;
}

}  // namespace

Shape translate_shape(const Shape& shape, const Scalar3& vector) {
  return guarded(translate_spec(), [&]() -> Shape {
    FeatureRecord rec(kTranslateOp);
    const Vec3 global_vector = features_detail::place_vector(rec.point("vector", vector));
    if (shape.kind() == Kind::Solid) {
      return finish_tracked_transform(tracked_translate(Solid(shape), global_vector), shape, rec, kTranslateOp);
    }
    Shape moved = finish_raw_transform(Shape::from_occt(kernel::translate_shape(shape.wrapped(), global_vector)), shape, kTranslateOp);
    record_operation(std::move(rec.input(shape, "shape")).take(), {moved});
    return moved;
  });
}

Shape rotate_shape(const Shape& shape, const Scalar& angle, const Scalar3& axis, const Scalar3& origin) {
  static const ErrorSpec spec{
      "rotate_shape",
      "Failed to rotate the shape.",
      {"The shape is invalid.", "The rotation angle is invalid or non-finite.",
       "The axis or origin is not a valid finite 3D vector."},
      {"Pass a valid shape and a finite rotation angle.", "Use a non-zero axis vector and a valid origin point.",
       "Log the evaluated angle, axis, and origin before retrying."}};
  if (evaluate_finite(angle) == 0) return shape;
  return guarded(spec, [&]() -> Shape {
    FeatureRecord rec(kRotateOp);
    const double angle_value = rec.scalar("angle", angle);
    const Vec3 global_axis = features_detail::place_vector(rec.point("axis", axis));
    const Vec3 global_origin = features_detail::place_point(rec.point("origin", origin));
    if (shape.kind() == Kind::Solid) {
      return finish_tracked_transform(tracked_rotate(Solid(shape), angle_value, global_axis, global_origin), shape, rec,
                                      kRotateOp);
    }
    Shape turned = finish_raw_transform(
        Shape::from_occt(kernel::rotate_shape(shape.wrapped(), angle_value, global_axis, global_origin)), shape, kRotateOp);
    record_operation(std::move(rec.input(shape, "shape")).take(), {turned});
    return turned;
  });
}

Shape mirror_shape(const Shape& shape, const Scalar3& plane_origin, const Scalar3& plane_normal) {
  static const ErrorSpec spec{
      "mirror_shape",
      "Failed to mirror the shape across the plane.",
      {"The plane origin or plane normal is invalid.", "The plane normal is zero-length.",
       "The kernel rejected the mirror transform."},
      {"Pass a valid plane origin and a non-zero plane normal.", "Validate the shape before mirroring.",
       "If the plane is computed dynamically, inspect the evaluated values first."}};
  return guarded(spec, [&]() -> Shape {
    FeatureRecord rec(kMirrorOp);
    const Vec3 global_origin = features_detail::place_point(rec.point("plane_origin", plane_origin));
    const Vec3 global_normal = features_detail::place_vector(rec.point("plane_normal", plane_normal));
    if (global_normal.norm() < 1e-10) throw ValueError("The mirror plane normal cannot be a zero vector");

    if (shape.kind() == Kind::Solid) {
      TrackedResult tracked = tracked_mirror(Solid(shape), global_origin, global_normal);
      tracked.shape.apply_tag("solid.transform.mirrored", false);
      return finish_tracked_transform(std::move(tracked), shape, rec, kMirrorOp);
    }
    Shape mirrored = finish_raw_transform(
        Shape::from_occt(kernel::mirror_shape(shape.wrapped(), global_origin, global_normal)), shape, kMirrorOp);
    mirrored.apply_tag("solid.transform.mirrored", false);
    attach_track_summary(mirrored, kMirrorOp);
    record_operation(std::move(rec.input(shape, "shape")).take(), {mirrored});
    return mirrored;
  });
}

}  // namespace scad

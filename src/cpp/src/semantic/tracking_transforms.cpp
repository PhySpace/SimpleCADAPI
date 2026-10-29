// tracked_translate / tracked_rotate / tracked_mirror.
#include <BRepBuilderAPI_Transform.hxx>
#include <TopAbs_ShapeEnum.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/cast.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/kernel/transforms.hpp"
#include "scad/semantic/tracking.hpp"
#include "tracking_detail.hpp"

namespace scad {

namespace {

// Transform a copy of `shape` and ask the transform which face became which.
// A rigid motion maps every face to exactly one face: each is "modified" by
// continuation (the same entity, moved), none generated or deleted.
TrackedResult track_transform(const Solid& shape, const gp_Trsf& trsf, const char* failure) {
  return occt_guard([&] {
    BRepBuilderAPI_Transform xform(shape.wrapped(), trsf, /*Copy=*/true);
    xform.Build();
    if (!xform.IsDone())
      throw ValueError(failure);

    const Solid result(kernel::as_solid(xform.Shape()));
    tracking::DeltaBuilder delta;
    if (tracking::history_wanted()) {
      tracking::BuilderHistory history(xform);
      kernel::SubShapeIndex in_result(xform.Shape());
      tracking::QuerySpec spec;
      spec.origin_role = "body";
      spec.kind = Kind::Face;
      spec.result = &in_result;
      spec.modified_derivation = "continuation";
      tracking::query_sub_shape_history(history, shape.wrapped(), TopAbs_FACE, spec, delta.witnesses);
    }
    return tracking::to_result(result, std::move(delta));
  });
}

}  // namespace

TrackedResult tracked_translate(const Solid& shape, const Vec3& vector) {
  return track_transform(shape, kernel::translation_trsf(vector), "Translate failed: OCC build did not complete");
}

TrackedResult tracked_rotate(const Solid& shape, double angle_degrees, const Vec3& axis, const Vec3& origin) {
  return track_transform(shape, kernel::rotation_trsf(angle_degrees, axis, origin),
                         "Rotate failed: OCC build did not complete");
}

TrackedResult tracked_mirror(const Solid& shape, const Vec3& plane_origin, const Vec3& plane_normal) {
  return track_transform(shape, kernel::mirror_trsf(plane_origin, plane_normal),
                         "Mirror failed: OCC build did not complete");
}

}  // namespace scad

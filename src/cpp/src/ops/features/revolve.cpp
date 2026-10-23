// revolve_rsolid (operators/features.py).
#include "scad/ops/features/revolve.hpp"

#include "internal.hpp"
#include "scad/semantic/tracking.hpp"

namespace scad {

namespace {

constexpr const char* kRevolveOp = "make_revolve_rsolid";

const ErrorSpec& revolve_spec() {
  static const ErrorSpec spec{
      "revolve_rsolid",
      "Failed to revolve the profile into a solid.",
      {"The angle is not a positive finite scalar.", "The axis or origin is invalid.",
       "A wire profile was provided but it is not closed.", "The kernel rejected the revolve definition."},
      {"Use an angle greater than zero.", "Pass a valid non-zero axis vector and a valid origin point.",
       "If you revolve a wire, ensure it is closed or convert it to a face first.",
       "Inspect the evaluated axis, origin, and profile before retrying."}};
  return spec;
}

Face revolution_face(const Shape& profile) {
  switch (profile.kind()) {
    case Kind::Wire: {
      const Wire wire(profile);
      if (!wire.is_closed()) throw ValueError("The wire to revolve must be closed");
      return features_detail::face_of_wire(wire);
    }
    case Kind::Face:
      return Face(profile);
    default:
      throw ValueError("Only a wire or a face can be revolved");
  }
}

}  // namespace

Solid revolve_rsolid(const Shape& profile, const Scalar3& axis, const Scalar& angle, const Scalar3& origin,
                     const SweepTags& tags) {
  return guarded(revolve_spec(), [&]() -> Solid {
    const OutputTags output = features_detail::sweep_output_tags(tags, "revolution.start", "revolution.end", "revolution.side");
    plan_output_tags(kRevolveOp, output);

    FeatureRecord rec(kRevolveOp);
    const double angle_value = rec.scalar("angle", angle);
    if (angle_value <= 0) throw ValueError("The revolve angle must be greater than zero");
    const Vec3 global_axis = features_detail::place_vector(rec.point("axis", axis));
    const Vec3 global_origin = features_detail::place_point(rec.point("origin", origin));

    const Face face = revolution_face(profile);
    TrackedResult tracked = tracked_revolve(face, global_axis, global_origin, angle_value);
    inherit_metadata(tracked.shape, {&profile});

    // A full turn has no cap faces to name.
    const bool capped = angle_value < 360.0;
    FinalizeSpec spec;
    spec.record = std::move(rec.input(profile, "profile")).take();
    spec.tags = output;
    spec.roles.start = capped ? "revolution.start" : "";
    spec.roles.end = capped ? "revolution.end" : "";
    spec.roles.side = "revolution.side";
    return finalize_tracked_solid(std::move(tracked), std::move(spec));
  });
}

}  // namespace scad

// extrude_rsolid (operators/features.py).
#include "scad/ops/features/extrusion.hpp"

#include "internal.hpp"
#include "scad/ops/geometry/diagnostics.hpp"
#include "scad/semantic/tracking.hpp"

namespace scad {

namespace {

constexpr const char* kExtrudeOp = "make_extrude_rsolid";

const ErrorSpec& extrude_spec() {
  static const ErrorSpec spec{"extrude_rsolid",
                              "Failed to extrude the profile into a solid.",
                              {"The distance is not a positive finite scalar.", "The direction vector is invalid.",
                               "A wire profile was provided but it is not closed.",
                               "The kernel rejected the profile or the extrusion direction."},
                              {"Use a distance greater than zero.", "Pass a valid finite direction vector.",
                               "If you extrude a wire, make sure the wire is closed or convert it to a face first.",
                               "Inspect the evaluated profile and direction before retrying."}};
  return spec;
}

Face extrusion_face(const Shape& profile) {
  switch (profile.kind()) {
    case Kind::Wire: {
      const Wire wire(profile);
      if (!wire.is_closed())
        raise_open_wire_failure("extrude_rsolid", wire, "extrude it into a solid");
      return features_detail::face_of_wire(wire);
    }
    case Kind::Face:
      return Face(profile);
    default:
      throw ValueError("Only a wire or a face can be extruded");
  }
}

}  // namespace

Solid extrude_rsolid(const Shape& profile, const Scalar3& direction, const Scalar& distance, const SweepTags& tags) {
  return guarded(extrude_spec(), [&]() -> Solid {
    const OutputTags output =
        features_detail::sweep_output_tags(tags, "extrusion.start", "extrusion.end", "extrusion.side");
    plan_output_tags(kExtrudeOp, output);

    FeatureRecord rec(kExtrudeOp);
    const double distance_value = rec.scalar("distance", distance);
    if (distance_value <= 0)
      throw ValueError("The extrusion distance must be greater than zero");
    const Vec3 global_direction = features_detail::place_vector(rec.point("direction", direction));
    if (global_direction.norm() <= 1e-15)
      throw ValueError("The extrusion direction cannot be a zero vector");

    const Face face = extrusion_face(profile);
    TrackedResult tracked = tracked_extrude(face, global_direction, distance_value);
    tracked.shape.apply_tag("solid.extrusion", false);
    inherit_metadata(tracked.shape, {&profile});

    FinalizeSpec spec;
    spec.record = std::move(rec.input(profile, "profile")).take();
    spec.tags = output;
    spec.roles.start = "extrusion.start";
    spec.roles.end = "extrusion.end";
    spec.roles.side = "extrusion.side";
    return finalize_tracked_solid(std::move(tracked), std::move(spec));
  });
}

}  // namespace scad

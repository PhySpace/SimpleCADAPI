// helical_sweep_rsolid (operators/features.py).
#include "internal.hpp"
#include "scad/ops/features/sweeps.hpp"
#include "scad/ops/geometry/faces.hpp"
#include "scad/ops/geometry/helix.hpp"
#include "scad/ops/geometry/plane.hpp"

namespace scad {

Solid helical_sweep_rsolid(const Wire& profile, const Scalar& pitch, const Scalar& height, const Scalar& radius,
                           const Scalar3& center, const Scalar3& dir, std::string_view handedness) {
  static const ErrorSpec spec{
      "helical_sweep_rsolid",
      "Failed to create the helical sweep solid.",
      {"Pitch, height, or radius is not positive.", "The input profile wire is invalid or cannot form a face.",
       "The center or direction vector is invalid.", "The underlying helix or sweep construction failed."},
      {"Use positive pitch, height, and radius values.", "Pass a valid profile wire that can be turned into a face.",
       "Validate the center and direction inputs before retrying.",
       "If the sweep still fails, try the explicit macro path: helix wire -> face from profile -> sweep."}};
  return guarded(spec, [&]() -> Solid {
    if (recording_session_active()) {
      // Every step is its own recorded node, so the sweep replays from its parts.
      const Wire helix = make_helix_rwire(pitch, height, radius, center, dir, handedness);
      return sweep_rsolid(make_face_from_wire_rface(profile), helix, /*is_frenet=*/true);
    }

    const double pitch_value = evaluate_finite(pitch);
    const double height_value = evaluate_finite(height);
    const double radius_value = evaluate_finite(radius);
    if (pitch_value <= 0)
      throw ValueError("The pitch must be greater than zero");
    if (height_value <= 0)
      throw ValueError("The height must be greater than zero");
    if (radius_value <= 0)
      throw ValueError("The radius must be greater than zero");

    const Vec3 local_dir = evaluate_point(dir, "dir");
    const Vec3 global_center = features_detail::place_point(evaluate_point(center, "center"));
    const Vec3 global_dir = features_detail::place_vector(local_dir);
    const Vec3 global_x = features_detail::place_vector(default_plane_x_direction(local_dir));

    // The kernel call has no handedness; the Python SDK ignores it on this path too.
    Solid result(kernel::make_helical_sweep_solid(TopoDS::Wire(profile.wrapped()), pitch_value, height_value,
                                                  radius_value, global_center, global_dir, global_x));
    inherit_metadata(result, {&profile});
    result.apply_tag("solid.feature.helical_sweep", false);
    return result;
  });
}

}  // namespace scad

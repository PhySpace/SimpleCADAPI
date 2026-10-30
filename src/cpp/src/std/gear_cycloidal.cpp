// Cycloidal reducer discs.
#include <cmath>
#include <vector>

#include "metadata.hpp"
#include "scad/core/error.hpp"
#include "scad/ops/features/features.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/semantic/tracked_result.hpp"
#include "scad/std/gear_profiles.hpp"
#include "scad/std/gears.hpp"
#include "scad/std/validation.hpp"

namespace scad {

using namespace stdlib;

namespace {

// A cylinder along Z through the disc, a little longer than it on both sides.
Solid through_cutter(double radius, double height, double x, double y) {
  return make_cylinder_rsolid(radius, height + 0.4, scalar3(x, y, -0.2), scalar3(0.0, 0.0, 1.0));
}

}  // namespace

Solid make_cycloidal_disc_rsolid(int n_lobes, double ring_pin_pitch_radius, double roller_radius, double eccentricity,
                                 double gear_height, const CycloidalDiscOptions& options) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  if (n_lobes < 2)
    throw ValueError("n_lobes must be at least 2");
  ring_pin_pitch_radius = validate_positive("ring_pin_pitch_radius", ring_pin_pitch_radius);
  roller_radius = validate_positive("roller_radius", roller_radius);
  eccentricity = validate_positive("eccentricity", eccentricity);
  gear_height = validate_positive("gear_height", gear_height);
  const double bore_radius = validate_non_negative("bore_radius", options.bore_radius);
  if (options.output_pin_count < 0)
    throw ValueError("output_pin_count must be non-negative");
  const double pin_pitch_radius = validate_non_negative("output_pin_pitch_radius", options.output_pin_pitch_radius);
  const double pin_clearance_radius =
      validate_non_negative("output_pin_clearance_radius", options.output_pin_clearance_radius);
  if (options.output_pin_count > 0) {
    if (pin_pitch_radius <= 0.0) {
      throw ValueError("output_pin_pitch_radius must be positive when output holes are requested");
    }
    if (pin_clearance_radius <= 0.0) {
      throw ValueError("output_pin_clearance_radius must be positive when output holes are requested");
    }
  }
  if (options.sample_count_per_lobe < 8)
    throw ValueError("sample_count_per_lobe must be at least 8");
  if (options.spline_tolerance <= 0.0)
    throw ValueError("spline_tolerance must be positive");
  if (options.max_control_points < 4)
    throw ValueError("max_control_points must be at least 4");
  if (!std::isfinite(options.output_pin_phase))
    throw ValueError("output_pin_phase must be finite");

  CycloidalProfile profile;
  profile.n_lobes = n_lobes;
  profile.ring_pin_pitch_radius = ring_pin_pitch_radius;
  profile.roller_radius = roller_radius;
  profile.eccentricity = eccentricity;
  profile.sample_count_per_lobe = options.sample_count_per_lobe;
  profile.spline_tolerance = options.spline_tolerance;
  profile.max_control_points = options.max_control_points;
  CycloidalFitData fit;
  const Wire wire = build_cycloidal_disc_profile_wire(profile, &fit);
  Solid disc = extrude_rsolid(wire, scalar3(0.0, 0.0, 1.0), gear_height);

  std::vector<Solid> pieces{disc};
  if (bore_radius > 0.0)
    pieces.push_back(through_cutter(bore_radius, gear_height, 0.0, 0.0));
  for (int index = 0; index < options.output_pin_count; ++index) {
    const double angle = radians(options.output_pin_phase + 360.0 * index / options.output_pin_count);
    pieces.push_back(through_cutter(pin_clearance_radius, gear_height, pin_pitch_radius * std::cos(angle),
                                    pin_pitch_radius * std::sin(angle)));
  }
  if (pieces.size() > 1) {
    CutOptions cut;
    cut.skip_non_intersecting = false;
    disc = cut_rsolid(pieces, cut);
  }

  disc.set_metadata(
      "std.gear.cycloidal_disc",
      Dict("pin_count", n_lobes + 1)("n_lobes", n_lobes)("segment_count", n_lobes)("sample_count_per_lobe",
                                                                                   options.sample_count_per_lobe)(
          "control_point_counts", list_of(fit.control_point_counts))("max_errors", list_of(fit.max_errors))(
          "radius_min", fit.radius_min)("radius_max", fit.radius_max)("ring_pin_pitch_radius", ring_pin_pitch_radius)(
          "roller_radius", roller_radius)("eccentricity", eccentricity)("gear_height", gear_height)(
          "bore_radius", bore_radius)("output_pin_count", options.output_pin_count)(
          "output_pin_pitch_radius", pin_pitch_radius)("output_pin_clearance_radius", pin_clearance_radius)(
          "output_pin_phase", options.output_pin_phase)("spline_tolerance", options.spline_tolerance)(
          "max_control_points", options.max_control_points)
          .take());
  return disc;
}

}  // namespace scad

#include "scad/std/chain.hpp"

#include <cmath>
#include <vector>

#include "metadata.hpp"
#include "scad/core/error.hpp"
#include "scad/ops/features/features.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/semantic/tracked_result.hpp"
#include "scad/std/validation.hpp"

namespace scad {

using namespace stdlib;

Solid make_roller_chain_sprocket_rsolid(int n_teeth, double chain_pitch, double roller_diameter,
                                        double sprocket_thickness, double bore_radius, double roller_clearance) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  if (n_teeth < 6) throw ValueError("n_teeth must be an integer of at least 6");
  const double pitch = positive_finite("chain_pitch", chain_pitch);
  const double roller = positive_finite("roller_diameter", roller_diameter);
  const double thickness = positive_finite("sprocket_thickness", sprocket_thickness);
  if (!std::isfinite(bore_radius) || bore_radius < 0.0) throw ValueError("bore_radius must be non-negative and finite");
  if (!std::isfinite(roller_clearance) || roller_clearance < 0.0) {
    throw ValueError("roller_clearance must be non-negative and finite");
  }
  if (roller >= pitch) throw ValueError("roller_diameter must be smaller than chain_pitch");

  const double half_tooth_angle = kPi / n_teeth;
  const double pitch_radius = pitch / (2.0 * std::sin(half_tooth_angle));
  const double seat_radius = roller / 2.0 + roller_clearance;
  const double root_radius = pitch_radius - seat_radius;
  const double outside_radius = pitch * (0.6 + 1.0 / std::tan(half_tooth_angle)) / 2.0;
  if (root_radius <= 0.0) throw ValueError("chain dimensions produce a non-positive root radius");
  if (!(root_radius < outside_radius && outside_radius < pitch_radius + seat_radius)) {
    throw ValueError("chain dimensions do not produce open roller seats");
  }
  if (bore_radius >= root_radius) throw ValueError("bore_radius must be smaller than the sprocket root radius");

  const Vec3 up{0.0, 0.0, 1.0};
  std::vector<Solid> pieces;
  pieces.reserve(static_cast<std::size_t>(n_teeth) + 2);
  pieces.push_back(make_cylinder_rsolid(outside_radius, thickness, scalar3(0.0, 0.0, 0.0), scalar3(up)));
  for (int index = 0; index < n_teeth; ++index) {
    const double angle = 2.0 * kPi * index / n_teeth;
    pieces.push_back(make_cylinder_rsolid(
        seat_radius, thickness + 0.4,
        scalar3(pitch_radius * std::cos(angle), pitch_radius * std::sin(angle), -0.2), scalar3(up)));
  }
  if (bore_radius > 0.0) {
    pieces.push_back(make_cylinder_rsolid(bore_radius, thickness + 0.4, scalar3(0.0, 0.0, -0.2), scalar3(up)));
  }
  CutOptions cut;
  cut.skip_non_intersecting = false;
  Solid sprocket = cut_rsolid(pieces, cut);
  sprocket.set_metadata("std.chain.roller_sprocket",
                        Dict("n_teeth", n_teeth)("chain_pitch", pitch)("roller_diameter", roller)(
                            "sprocket_thickness", thickness)("bore_radius", bore_radius)(
                            "roller_clearance", roller_clearance)("pitch_radius", pitch_radius)(
                            "root_radius", root_radius)("outside_radius", outside_radius)
                            .take());
  return sprocket;
}

}  // namespace scad

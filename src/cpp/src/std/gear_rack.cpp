// Racks: straight, helical (a lofted twist), herringbone.
#include <algorithm>
#include <cmath>

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

// `_rotate_profile_wire_3d`: `wire` turned about Z, then lifted to height `z`.
Shape rotated_section(const Wire& wire, double angle_degrees, double z) {
  Shape section = rotate_shape(wire, angle_degrees, scalar3(0.0, 0.0, 1.0), scalar3(0.0, 0.0, 0.0));
  if (z != 0.0)
    section = translate_shape(section, scalar3(0.0, 0.0, z));
  return section;
}

}  // namespace

Solid make_spur_rack_rsolid(double module, int n_teeth, double pressure_angle, double rack_height) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  if (module <= 0)
    throw ValueError("module must be positive");
  if (n_teeth < 1)
    throw ValueError("n_teeth must be at least 1");
  if (rack_height <= 0)
    throw ValueError("rack_height must be positive");

  const Face face = build_rack_profile_face(module, n_teeth, radians(pressure_angle));
  return extrude_rsolid(face, scalar3(0.0, 0.0, 1.0), rack_height);
}

Solid make_helical_rack_rsolid(double module, int n_teeth, double pressure_angle, double helix_angle,
                               double rack_height) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  if (helix_angle == 0)
    return make_spur_rack_rsolid(module, n_teeth, pressure_angle, rack_height);

  const double pitch = kPi * module;
  const double twist_total = helix_twist_degrees(rack_height, helix_angle, pitch);
  const int n_sections = std::max(6, static_cast<int>(std::fabs(twist_total) / 5.0) + 2);
  const Wire base_wire = build_rack_profile_face(module, n_teeth, radians(pressure_angle)).outer_wire();

  std::vector<Shape> sections;
  sections.reserve(static_cast<std::size_t>(n_sections) + 1);
  for (int i = 0; i <= n_sections; ++i) {
    const double fraction = static_cast<double>(i) / n_sections;
    sections.push_back(rotated_section(base_wire, twist_total * fraction, rack_height * fraction));
  }
  return loft_rsolid(sections, /*ruled=*/false);
}

Solid make_herringbone_rack_rsolid(double module, int n_teeth, double pressure_angle, double helix_angle,
                                   double rack_height) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  if (helix_angle == 0)
    return make_spur_rack_rsolid(module, n_teeth, pressure_angle, rack_height);

  const double pitch = kPi * module;
  const double half_height = rack_height / 2.0;
  const double half_twist = helix_twist_degrees(half_height, helix_angle, pitch);
  const int n_sections_per_half = std::max(4, static_cast<int>(std::fabs(half_twist) / 5.0) + 2);
  const Wire base_wire = build_rack_profile_face(module, n_teeth, radians(pressure_angle)).outer_wire();

  std::vector<Shape> sections;
  sections.reserve(static_cast<std::size_t>(n_sections_per_half) * 2 + 1);
  for (int i = 0; i <= n_sections_per_half; ++i) {
    const double fraction = static_cast<double>(i) / n_sections_per_half;
    sections.push_back(rotated_section(base_wire, half_twist * fraction, half_height * fraction));
  }
  for (int i = 1; i <= n_sections_per_half; ++i) {
    const double fraction = static_cast<double>(i) / n_sections_per_half;
    sections.push_back(rotated_section(base_wire, half_twist * (1.0 - fraction), half_height + half_height * fraction));
  }
  return loft_rsolid(sections, /*ruled=*/false);
}

}  // namespace scad

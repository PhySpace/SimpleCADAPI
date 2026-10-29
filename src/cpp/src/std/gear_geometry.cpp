#include "scad/std/gear_geometry.hpp"

#include <algorithm>
#include <cmath>

#include "scad/core/error.hpp"
#include "scad/core/vec.hpp"
#include "scad/std/validation.hpp"

namespace scad::stdlib {

double pressure_angle_to_radians(double pressure_angle) {
  if (!std::isfinite(pressure_angle))
    throw ValueError("pressure_angle must be finite");
  if (pressure_angle <= 0.0 || pressure_angle >= 90.0) {
    throw ValueError("pressure_angle must be greater than 0 and less than 90 degrees");
  }
  return radians(pressure_angle);
}

ToothGeometry compute_tooth_geometry(int n_teeth, double module, double pressure_angle, const ToothOptions& options) {
  const ToothTuning& tuning = options.tuning;
  const double addendum = validate_positive("addendum_factor", tuning.addendum_factor) * module;
  const double clearance = validate_non_negative("clearance_factor", tuning.clearance_factor) * module;
  const double backlash = validate_non_negative("backlash", tuning.backlash);

  ToothGeometry g;
  g.pitch_radius = module * n_teeth / 2.0;
  g.base_radius = g.pitch_radius * std::cos(pressure_angle);
  g.tip_radius = options.tip_radius ? *options.tip_radius : g.pitch_radius + addendum;
  g.root_radius =
      options.root_radius ? *options.root_radius : std::max(g.pitch_radius - addendum - clearance, g.base_radius * 0.5);
  if (g.tip_radius <= g.root_radius)
    throw ValueError("tip radius must be greater than root radius");

  g.tooth_angle = 2.0 * kPi / n_teeth;
  const double pitch_tooth_thickness = kPi * module / 2.0 - backlash;
  if (pitch_tooth_thickness <= 0.0)
    throw ValueError("backlash must be smaller than the circular tooth thickness");
  const double pitch_half_angle = pitch_tooth_thickness / (2.0 * g.pitch_radius);
  const double inv_alpha = std::tan(pressure_angle) - pressure_angle;
  const double base_half_angle = pitch_half_angle + inv_alpha;

  g.left_start = -base_half_angle;
  g.right_start = +base_half_angle;
  const double t_tip = involute_t_for_radius(g.base_radius, g.tip_radius);
  const double tip_half_span = t_tip - std::atan(t_tip);
  g.left_tip_angle = g.left_start + tip_half_span;
  g.right_tip_angle = g.right_start - tip_half_span;
  g.prev_right_start = g.right_start - g.tooth_angle;
  g.addendum_factor = tuning.addendum_factor;
  g.clearance_factor = tuning.clearance_factor;
  g.backlash = backlash;
  return g;
}

InternalRingRadii internal_ring_radii(int n_teeth, double module, double rim_thickness, double addendum_factor,
                                      double clearance_factor) {
  const double addendum = validate_positive("addendum_factor", addendum_factor) * module;
  const double clearance = validate_non_negative("clearance_factor", clearance_factor) * module;
  InternalRingRadii r;
  r.pitch = module * n_teeth / 2.0;
  r.tip = r.pitch - addendum;
  r.root = r.pitch + addendum + clearance;
  if (r.tip <= 0.0)
    throw ValueError("internal tooth tip radius must be positive");
  r.outer = r.root + rim_thickness;
  return r;
}

InternalToothGeometry compute_internal_tooth_geometry(int n_teeth, double module, double pressure_angle,
                                                      const ToothTuning& tuning) {
  const double backlash = validate_non_negative("backlash", tuning.backlash);
  const InternalRingRadii radii =
      internal_ring_radii(n_teeth, module, 0.0, tuning.addendum_factor, tuning.clearance_factor);

  InternalToothGeometry g;
  g.pitch_radius = radii.pitch;
  g.tip_radius = radii.tip;
  g.root_radius = radii.root;
  g.base_radius = radii.pitch * std::cos(pressure_angle);
  g.tooth_angle = 2.0 * kPi / n_teeth;
  const double pitch_half_angle = (kPi * module / 2.0) / (2.0 * radii.pitch);
  const double inv_alpha = std::tan(pressure_angle) - pressure_angle;
  g.backlash_half_angle = backlash / (2.0 * radii.pitch);
  const double base_half_angle = pitch_half_angle - inv_alpha - g.backlash_half_angle;

  const auto half_angle_at = [&](double radius) {
    const double t = involute_t_for_radius(g.base_radius, std::max(radius, g.base_radius));
    return base_half_angle + (t - std::atan(t));
  };
  g.flank_tip_radius = std::max(g.base_radius, g.tip_radius);
  g.needs_tip_connectors = g.tip_radius < g.base_radius - 1e-8;
  const double tip_half_angle = half_angle_at(g.flank_tip_radius);
  const double root_half_angle = half_angle_at(g.root_radius);

  g.backlash = backlash;
  g.left_base_angle = -base_half_angle;
  g.right_base_angle = base_half_angle;
  g.left_tip_angle = -tip_half_angle;
  g.right_tip_angle = tip_half_angle;
  g.left_root_angle = -root_half_angle;
  g.right_root_angle = root_half_angle;
  g.addendum_factor = tuning.addendum_factor;
  g.clearance_factor = tuning.clearance_factor;
  return g;
}

std::vector<Point2> rack_profile_points(double module, int n_teeth, double pressure_angle) {
  const double addendum = module;
  const double dedendum = 1.25 * module;
  const double pitch = kPi * module;
  const double half_tooth = pitch / 2.0;
  const double flank_offset = addendum * std::tan(pressure_angle);
  const double root_flank_offset = dedendum * std::tan(pressure_angle);
  const double total_width = n_teeth * pitch;
  const double x_start = -total_width / 2.0;

  std::vector<Point2> points;
  points.reserve(static_cast<std::size_t>(n_teeth) * 4 + 2);
  points.push_back({x_start, -dedendum});
  for (int i = 0; i < n_teeth; ++i) {
    const double x0 = x_start + i * pitch;
    const double x_pitch_left = x0 + half_tooth / 2.0;
    const double x_tip_left = x_pitch_left - flank_offset;
    const double x_tip_right = x_pitch_left + half_tooth + flank_offset;
    const double x_root_right = x0 + pitch;
    points.push_back({x0 + root_flank_offset, -dedendum});
    points.push_back({x_tip_left, addendum});
    points.push_back({x_tip_right, addendum});
    points.push_back({x_root_right - root_flank_offset, -dedendum});
  }
  points.push_back({x_start + total_width, -dedendum});
  return points;
}

Point2 cycloidal_disc_point(double theta, int n_lobes, double ring_pin_pitch_radius, double roller_radius,
                            double eccentricity) {
  const int pin_count = n_lobes + 1;
  const double phi =
      std::atan2(std::sin((1.0 - pin_count) * theta),
                 ring_pin_pitch_radius / (eccentricity * pin_count) - std::cos((1.0 - pin_count) * theta));
  return {ring_pin_pitch_radius * std::cos(theta) - roller_radius * std::cos(theta + phi) -
              eccentricity * std::cos(pin_count * theta),
          -ring_pin_pitch_radius * std::sin(theta) + roller_radius * std::sin(theta + phi) +
              eccentricity * std::sin(pin_count * theta)};
}

double helix_twist_degrees(double height, double helix_angle, double pitch_diameter) {
  return degrees(2.0 * kPi * height * std::tan(radians(helix_angle)) / (kPi * pitch_diameter));
}

}  // namespace scad::stdlib

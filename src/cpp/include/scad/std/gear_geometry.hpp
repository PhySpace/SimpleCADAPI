// The numbers behind the gear profiles: tooth angles and radii of external and internal
// involute gears, rack tooth points, cycloidal disc points.  Pure maths, no shapes.
#pragma once

#include <optional>
#include <tuple>
#include <vector>

#include "scad/std/involute.hpp"

namespace scad::stdlib {

// What a caller may tune of an involute tooth (Python: the keyword-only arguments of every gear).
struct ToothTuning {
  double addendum_factor = 1.0;    // addendum as a multiple of the module
  double clearance_factor = 0.25;  // root clearance below the addendum, as a multiple of the module
  double backlash = 0.0;           // circumferential tooth-thickness reduction at the pitch circle
};

// `_pressure_angle_to_radians`: ValueError unless the angle is finite and in (0, 90) degrees.
double pressure_angle_to_radians(double pressure_angle);

// _compute_tooth_geometry: an external involute tooth-space profile.  Angles are measured
// from the tooth axis; the left flank starts at left_start, the right one at right_start.
struct ToothGeometry {
  double pitch_radius = 0, base_radius = 0, tip_radius = 0, root_radius = 0;
  double tooth_angle = 0;
  double left_start = 0, right_start = 0, left_tip_angle = 0, right_tip_angle = 0, prev_right_start = 0;
  double addendum_factor = 0, clearance_factor = 0, backlash = 0;
};

struct ToothOptions {
  std::optional<double> root_radius;  // default: pitch - addendum - clearance, at least half the base radius
  std::optional<double> tip_radius;   // default: pitch + addendum
  ToothTuning tuning;
};

// ValueError for a tuning outside its range, a tip not above the root, a backlash that eats the tooth.
ToothGeometry compute_tooth_geometry(int n_teeth, double module, double pressure_angle,
                                     const ToothOptions& options = {});

// _internal_ring_radii: (pitch, internal tooth tip, internal root, outer rim).
struct InternalRingRadii {
  double pitch = 0, tip = 0, root = 0, outer = 0;
};
InternalRingRadii internal_ring_radii(int n_teeth, double module, double rim_thickness, double addendum_factor = 1.0,
                                      double clearance_factor = 0.25);

// _compute_internal_tooth_geometry: the inward-facing tooth boundary of an internal gear.
struct InternalToothGeometry {
  double pitch_radius = 0, base_radius = 0, tip_radius = 0, root_radius = 0, flank_tip_radius = 0;
  bool needs_tip_connectors = false;
  double tooth_angle = 0, backlash = 0, backlash_half_angle = 0;
  double left_base_angle = 0, right_base_angle = 0, left_tip_angle = 0, right_tip_angle = 0;
  double left_root_angle = 0, right_root_angle = 0;
  double addendum_factor = 0, clearance_factor = 0;
};
InternalToothGeometry compute_internal_tooth_geometry(int n_teeth, double module, double pressure_angle,
                                                      const ToothTuning& tuning = {});

// _build_rack_profile_points: the closed trapezoidal tooth outline of a straight rack, in x, y.
std::vector<Point2> rack_profile_points(double module, int n_teeth, double pressure_angle);

// _cycloidal_disc_point: one point of a one-tooth-difference cycloidal reducer disc.
Point2 cycloidal_disc_point(double theta, int n_lobes, double ring_pin_pitch_radius, double roller_radius,
                            double eccentricity);

// The twist (degrees) a helix of `helix_angle` makes over `height` on a pitch circle of `pitch_diameter`.
double helix_twist_degrees(double height, double helix_angle, double pitch_diameter);

}  // namespace scad::stdlib

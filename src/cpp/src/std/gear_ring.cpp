// Internal (ring) gears: spur, helical, herringbone.
#include "gear_sweeps.hpp"
#include "scad/core/error.hpp"
#include "scad/semantic/tracked_result.hpp"
#include "scad/std/gear_profiles.hpp"
#include "scad/std/gears.hpp"
#include "scad/std/validation.hpp"

namespace scad {

using namespace stdlib;

Solid make_spur_ring_gear_rsolid(int n_teeth, double module, double pressure_angle, double gear_height,
                                 double rim_thickness, const ToothTuning& tuning) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  if (n_teeth < 3) throw ValueError("n_teeth must be at least 3");
  if (module <= 0) throw ValueError("module must be positive");
  if (gear_height <= 0) throw ValueError("gear_height must be positive");
  if (rim_thickness <= 0) throw ValueError("rim_thickness must be positive");

  const double pa = pressure_angle_to_radians(pressure_angle);
  const Face face = build_ring_gear_face(n_teeth, module, pa, rim_thickness, tuning);
  return extrude_rsolid(face, scalar3(0.0, 0.0, 1.0), gear_height);
}

// Python checks nothing before the helix test here: a zero helix angle hands every check to the
// spur ring gear, and a helical one meets them where the profile maths does.
Solid make_helical_ring_gear_rsolid(int n_teeth, double module, double pressure_angle, double helix_angle,
                                    double gear_height, double rim_thickness, const ToothTuning& tuning) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  if (helix_angle == 0) {
    return make_spur_ring_gear_rsolid(n_teeth, module, pressure_angle, gear_height, rim_thickness, tuning);
  }
  const double pa = pressure_angle_to_radians(pressure_angle);
  const double twist_total = helix_twist_degrees(gear_height, helix_angle, module * n_teeth);
  const Face face = build_ring_gear_face(n_teeth, module, pa, rim_thickness, tuning);
  return twisted_gear_solid(face, gear_height, twist_total);
}

Solid make_herringbone_ring_gear_rsolid(int n_teeth, double module, double pressure_angle, double helix_angle,
                                        double gear_height, double rim_thickness, const ToothTuning& tuning) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  if (helix_angle == 0) {
    return make_spur_ring_gear_rsolid(n_teeth, module, pressure_angle, gear_height, rim_thickness, tuning);
  }
  const double pa = pressure_angle_to_radians(pressure_angle);
  const double half_height = gear_height / 2.0;
  const double half_twist = helix_twist_degrees(half_height, helix_angle, module * n_teeth);
  const Face face = build_ring_gear_face(n_teeth, module, pa, rim_thickness, tuning);
  return herringbone_gear_solid(face, half_height, half_twist);
}

}  // namespace scad

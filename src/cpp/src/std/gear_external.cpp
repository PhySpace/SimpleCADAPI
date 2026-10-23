// Spur, straight bevel, helical and herringbone gears.
#include <cmath>

#include "gear_sweeps.hpp"
#include "metadata.hpp"
#include "scad/core/error.hpp"
#include "scad/semantic/tracked_result.hpp"
#include "scad/sketch/operators.hpp"
#include "scad/std/gear_profiles.hpp"
#include "scad/std/gears.hpp"
#include "scad/std/validation.hpp"

namespace scad {

using namespace stdlib;

namespace {

void require_gear_dimensions(int n_teeth, double module, double gear_height) {
  if (n_teeth < 3) throw ValueError("n_teeth must be at least 3");
  if (module <= 0) throw ValueError("module must be positive");
  if (gear_height <= 0) throw ValueError("gear_height must be positive");
}

ToothOptions tooth_options(const ToothTuning& tuning) {
  ToothOptions options;
  options.tuning = tuning;
  return options;
}

}  // namespace

Solid make_spur_gear_rsolid(int n_teeth, double module, double pressure_angle, double gear_height,
                            const ToothTuning& tuning) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  require_gear_dimensions(n_teeth, module, gear_height);
  const double pa = pressure_angle_to_radians(pressure_angle);
  const Face face = build_gear_profile_face(n_teeth, module, pa, tooth_options(tuning));
  return extrude_rsolid(face, scalar3(0.0, 0.0, 1.0), gear_height);
}

Solid make_straight_bevel_gear_rsolid(int n_teeth, double module, double pitch_angle, double pressure_angle,
                                      double face_width, const ToothTuning& tuning) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  if (n_teeth < 3) throw ValueError("n_teeth must be at least 3");
  const double resolved_module = validate_positive("module", module);
  const double resolved_face_width = validate_positive("face_width", face_width);
  const double resolved_backlash = validate_non_negative("backlash", tuning.backlash);
  const double resolved_addendum = validate_positive("addendum_factor", tuning.addendum_factor);
  const double resolved_clearance = validate_non_negative("clearance_factor", tuning.clearance_factor);
  const double pressure_angle_radians = pressure_angle_to_radians(pressure_angle);
  if (!std::isfinite(pitch_angle)) throw ValueError("pitch_angle must be finite");
  if (pitch_angle <= 0.0 || pitch_angle >= 90.0) {
    throw ValueError("pitch_angle must be greater than 0 and less than 90 degrees");
  }

  const double pitch_angle_radians = radians(pitch_angle);
  const double outer_pitch_radius = resolved_module * n_teeth / 2.0;
  const double outer_cone_distance = outer_pitch_radius / std::sin(pitch_angle_radians);
  if (resolved_face_width >= outer_cone_distance) {
    throw ValueError("face_width must be smaller than the pitch-cone distance");
  }

  const double inner_scale = (outer_cone_distance - resolved_face_width) / outer_cone_distance;
  const double inner_module = resolved_module * inner_scale;
  const double axial_width = resolved_face_width * std::cos(pitch_angle_radians);

  ToothOptions outer_options;
  outer_options.tuning = {resolved_addendum, resolved_clearance, resolved_backlash};
  ToothOptions inner_options = outer_options;
  inner_options.tuning.backlash = resolved_backlash * inner_scale;

  const Wire outer_wire = make_wire_from_sketch_rwire(
      build_gear_profile_sketch(n_teeth, resolved_module, pressure_angle_radians, outer_options));
  Shape inner_wire = make_wire_from_sketch_rwire(
      build_gear_profile_sketch(n_teeth, inner_module, pressure_angle_radians, inner_options));
  inner_wire = translate_shape(inner_wire, scalar3(0.0, 0.0, axial_width));

  Solid gear = loft_rsolid({outer_wire, inner_wire}, /*ruled=*/true);
  gear.set_metadata("std.gear.straight_bevel",
                    Dict("n_teeth", n_teeth)("module", resolved_module)("pitch_angle", pitch_angle)(
                        "pressure_angle", pressure_angle)("face_width", resolved_face_width)(
                        "axial_width", axial_width)("outer_pitch_radius", outer_pitch_radius)(
                        "outer_cone_distance", outer_cone_distance)("inner_scale", inner_scale)(
                        "addendum_factor", resolved_addendum)("clearance_factor", resolved_clearance)(
                        "backlash", resolved_backlash)
                        .take());
  return gear;
}

Solid make_helical_gear_rsolid(int n_teeth, double module, double pressure_angle, double helix_angle,
                               double gear_height, const ToothTuning& tuning) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  require_gear_dimensions(n_teeth, module, gear_height);
  if (helix_angle == 0) return make_spur_gear_rsolid(n_teeth, module, pressure_angle, gear_height, tuning);

  const double pa = pressure_angle_to_radians(pressure_angle);
  const double twist_total = helix_twist_degrees(gear_height, helix_angle, module * n_teeth);
  const Face face = build_gear_profile_face(n_teeth, module, pa, tooth_options(tuning));
  return twisted_gear_solid(face, gear_height, twist_total);
}

Solid make_herringbone_gear_rsolid(int n_teeth, double module, double pressure_angle, double helix_angle,
                                   double gear_height, const ToothTuning& tuning) {
  const TrackingPolicyScope graph(TrackingPolicy::Graph);
  require_gear_dimensions(n_teeth, module, gear_height);
  if (helix_angle == 0) return make_spur_gear_rsolid(n_teeth, module, pressure_angle, gear_height, tuning);

  const double pa = pressure_angle_to_radians(pressure_angle);
  const double half_height = gear_height / 2.0;
  const double half_twist = helix_twist_degrees(half_height, helix_angle, module * n_teeth);
  const Face face = build_gear_profile_face(n_teeth, module, pa, tooth_options(tuning));
  return herringbone_gear_solid(face, half_height, half_twist);
}

}  // namespace scad

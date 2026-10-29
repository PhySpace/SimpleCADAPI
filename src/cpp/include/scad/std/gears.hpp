// Involute gears, ring gears, racks and cycloidal discs: the factories of std/gear.py.
//
// Every factory runs under the graph tracking policy, so the intermediate solids it builds are
// recorded without topology deltas.  Argument problems are plain ValueErrors, as in Python;
// anything the operators underneath reject surfaces as their own scad::Error.
#pragma once

#include "scad/std/gear_geometry.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

using stdlib::ToothTuning;

// An involute spur gear along +Z from the origin.  `pressure_angle` in degrees; tuning: addendum
// and clearance as multiples of the module, backlash as a tooth-thickness reduction in mm.
// ValueError: n_teeth < 3, module or gear_height not positive, a pressure angle outside (0, 90),
// a tuning outside its range.
Solid make_spur_gear_rsolid(int n_teeth, double module, double pressure_angle = 20.0, double gear_height = 6.0,
                            const ToothTuning& tuning = {});

// A straight bevel gear: the large-end involute section and a similar small-end section on the
// pitch cone, joined by a ruled loft.  `face_width` runs along the pitch-cone generator.
// Metadata "std.gear.straight_bevel".
Solid make_straight_bevel_gear_rsolid(int n_teeth, double module, double pitch_angle = 45.0,
                                      double pressure_angle = 20.0, double face_width = 8.0,
                                      const ToothTuning& tuning = {});

// One continuous twisted sweep of the spur profile; a zero helix angle gives the spur gear.
Solid make_helical_gear_rsolid(int n_teeth, double module, double pressure_angle = 20.0, double helix_angle = 30.0,
                               double gear_height = 8.0, const ToothTuning& tuning = {});

// Two opposite twisted halves sharing the rotated centre section, fused.
Solid make_herringbone_gear_rsolid(int n_teeth, double module, double pressure_angle = 20.0, double helix_angle = 32.0,
                                   double gear_height = 10.0, const ToothTuning& tuning = {});

// Internal gears: the rim and the inward tooth profile are one multi-loop face.  `tuning.backlash`
// widens the tooth space.
Solid make_spur_ring_gear_rsolid(int n_teeth, double module, double pressure_angle = 20.0, double gear_height = 6.0,
                                 double rim_thickness = 3.0, const ToothTuning& tuning = {});
Solid make_helical_ring_gear_rsolid(int n_teeth, double module, double pressure_angle = 20.0, double helix_angle = 25.0,
                                    double gear_height = 8.0, double rim_thickness = 3.0,
                                    const ToothTuning& tuning = {});
Solid make_herringbone_ring_gear_rsolid(int n_teeth, double module, double pressure_angle = 20.0,
                                        double helix_angle = 30.0, double gear_height = 10.0,
                                        double rim_thickness = 3.0, const ToothTuning& tuning = {});

struct CycloidalDiscOptions {
  double bore_radius = 0.0;
  int output_pin_count = 0;
  double output_pin_pitch_radius = 0.0;
  double output_pin_clearance_radius = 0.0;
  double output_pin_phase = 0.0;  // degrees, in the unrotated disc's frame
  int sample_count_per_lobe = 33;
  double spline_tolerance = 0.005;
  int max_control_points = 20;
};

// A one-tooth-difference cycloidal reducer disc: one fitted B-spline per lobe, an optional bore
// and output-pin clearance holes.  Metadata "std.gear.cycloidal_disc".
Solid make_cycloidal_disc_rsolid(int n_lobes, double ring_pin_pitch_radius, double roller_radius, double eccentricity,
                                 double gear_height = 6.0, const CycloidalDiscOptions& options = {});

// Racks with trapezoidal teeth, along X, centred on the origin.
Solid make_spur_rack_rsolid(double module, int n_teeth = 10, double pressure_angle = 20.0, double rack_height = 6.0);
Solid make_helical_rack_rsolid(double module, int n_teeth = 10, double pressure_angle = 20.0, double helix_angle = 25.0,
                               double rack_height = 8.0);
Solid make_herringbone_rack_rsolid(double module, int n_teeth = 10, double pressure_angle = 20.0,
                                   double helix_angle = 30.0, double rack_height = 10.0);

}  // namespace scad

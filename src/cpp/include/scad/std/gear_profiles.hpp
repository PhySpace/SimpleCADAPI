// The planar profiles of the gear factories: constraint sketches of involute teeth, ring-gear
// faces, rack outlines and fitted cycloidal lobes.
#pragma once

#include <vector>

#include "scad/sketch/sketch.hpp"
#include "scad/std/gear_geometry.hpp"
#include "scad/topo/shape.hpp"

namespace scad::stdlib {

// _build_gear_profile_face (build_face=False): the sketch of one external gear -- construction
// circles for root, pitch and tip, a fixed centre, and per tooth a root arc, two B-spline flanks
// with optional tangent root transitions, and a tip arc.  The flank is fitted once and rotated.
Sketch build_gear_profile_sketch(int n_teeth, double module, double pressure_angle, const ToothOptions& options = {});
Face build_gear_profile_face(int n_teeth, double module, double pressure_angle, const ToothOptions& options = {});

// _build_internal_gear_profile_wire: the inward-facing boundary of an internal gear.
Sketch build_internal_gear_profile_sketch(int n_teeth, double module, double pressure_angle,
                                          const ToothTuning& tuning = {});
Wire build_internal_gear_profile_wire(int n_teeth, double module, double pressure_angle,
                                      const ToothTuning& tuning = {});

// _build_ring_gear_face: an outer rim circle and the internal tooth boundary as one multi-loop face.
Face build_ring_gear_face(int n_teeth, double module, double pressure_angle, double rim_thickness,
                          const ToothTuning& tuning = {});

// _build_rack_profile_face: the rack outline as a sketch line loop promoted to a face.
Face build_rack_profile_face(double module, int n_teeth, double pressure_angle);

// _build_cycloidal_disc_profile_wire: one fitted cubic B-spline per lobe.
struct CycloidalProfile {
  int n_lobes = 0;
  double ring_pin_pitch_radius = 0, roller_radius = 0, eccentricity = 0;
  int sample_count_per_lobe = 33;
  double spline_tolerance = 0.005;
  int max_control_points = 20;
};
struct CycloidalFitData {
  std::vector<int> control_point_counts;
  std::vector<double> max_errors;
  double radius_min = 0, radius_max = 0;
};
Wire build_cycloidal_disc_profile_wire(const CycloidalProfile& profile, CycloidalFitData* fit_data = nullptr);

}  // namespace scad::stdlib

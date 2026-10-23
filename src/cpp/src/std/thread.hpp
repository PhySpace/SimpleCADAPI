// Thread and prism builders shared by the bolt and nut factories.
#pragma once

#include <string_view>
#include <vector>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad::stdlib {

// `sides` points of a regular polygon of `circumradius` at height `z`, the first at angle `phase`.
std::vector<Scalar3> regular_polygon_points(int sides, double circumradius, double z, double phase);

// The closed polygon through `points` (in a horizontal plane) extruded up by `height`.
Solid make_prism(const std::vector<Scalar3>& points, double height);

// A regular prism of `sides` flats `width` apart, from height `z` up by `height`.
Solid make_across_flats_prism(int sides, double width, double z, double height);

// One helical ridge: a V (truncated 60 degrees) or trapezoidal profile swept along a helix that
// starts one pitch below `start_z` and is clipped to [start_z, start_z + length].
struct ThreadCutterSpec {
  double inner_radius = 0.0;
  double outer_radius = 0.0;
  double pitch = 0.0;
  double start_z = 0.0;
  double length = 0.0;
  std::string_view thread_form = "v";
};
// ValueError when the profile's depth leaves no root flat; the operators' own errors otherwise.
Solid make_thread_cutter(const ThreadCutterSpec& spec);

// The cutter turned about Z by `angle_degrees` (the cutter itself for 0, which records nothing).
Solid rotate_thread_cutter(const Solid& cutter, double angle_degrees);

// The first candidate phase for which cutting `cutter` from `shank` removes something, but not
// everything: the helical sweep is unstable at some phases.  The trials are not recorded.
// ValueError("modeled external thread is unstable ...") when none works.
double select_external_thread_phase(const Solid& shank, const Solid& cutter, double minimum_volume);

// The same for fusing `ridge` into an opened nut.
double select_internal_thread_phase(const Solid& opened_nut, const Solid& body, const Solid& ridge);

}  // namespace scad::stdlib

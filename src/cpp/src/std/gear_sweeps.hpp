// The sweeps shared by the external and the ring gears: one continuous twist, or two opposite
// halves fused at the rotated centre section.
#pragma once

#include "scad/ops/features/features.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/topo/shape.hpp"

namespace scad::stdlib {

inline Solid twisted_gear_solid(const Face& profile, double height, double twist_degrees) {
  return twisted_sweep_rsolid(profile, height, twist_degrees);
}

inline Solid herringbone_gear_solid(const Face& profile, double half_height, double half_twist_degrees) {
  const Solid lower = twisted_sweep_rsolid(profile, half_height, half_twist_degrees);
  Shape upper_profile = rotate_shape(profile, half_twist_degrees, scalar3(0.0, 0.0, 1.0), scalar3(0.0, 0.0, 0.0));
  upper_profile = translate_shape(upper_profile, scalar3(0.0, 0.0, half_height));
  const Solid upper = twisted_sweep_rsolid(upper_profile, half_height, -half_twist_degrees, scalar3(0.0, 0.0, 1.0),
                                           scalar3(0.0, 0.0, half_height));
  UnionOptions options;
  options.tracking_policy = "graph";
  return union_rsolid({lower, upper}, options);
}

}  // namespace scad::stdlib

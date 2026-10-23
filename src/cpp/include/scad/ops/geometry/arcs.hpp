// Circular arcs.
#pragma once

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// The arc through three points of the current coordinate system, from `start` to `end`.
// Error "make_three_point_arc_redge": collinear points.
Edge make_three_point_arc_redge(const Scalar3& start, const Scalar3& middle, const Scalar3& end);
Wire make_three_point_arc_rwire(const Scalar3& start, const Scalar3& middle, const Scalar3& end);

// The arc of the circle (center, radius, normal) from `start_angle` to `end_angle`, in
// radians, counter-clockwise about `normal`.
// Error "make_angle_arc_redge": radius not positive, equal angles.
Edge make_angle_arc_redge(const Scalar3& center, const Scalar& radius, const Scalar& start_angle,
                          const Scalar& end_angle, const Scalar3& normal = scalar3(0, 0, 1));
Wire make_angle_arc_rwire(const Scalar3& center, const Scalar& radius, const Scalar& start_angle,
                          const Scalar& end_angle, const Scalar3& normal = scalar3(0, 0, 1));

}  // namespace scad

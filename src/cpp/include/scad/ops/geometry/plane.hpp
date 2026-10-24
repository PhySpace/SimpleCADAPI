// Plane frames, as operators/_support.py and operators/geometry.py compute them.
#pragma once

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"

namespace scad {

// `_orthonormal_plane_axes`: a right-handed frame whose z axis is `normal`.  x is the global
// X (or Z, when the normal is nearly along Z) projected onto the plane, so a +Z normal gives
// exactly the global (x, y, z): the width of a profile lies along X, like make_box_rsolid's.
struct PlaneAxes {
  Vec3 z_axis;
  Vec3 x_axis;
  Vec3 y_axis;
};
// ValueError for a zero normal.
PlaneAxes orthonormal_plane_axes(const Vec3& normal);

// `_default_plane_x_direction`: the in-plane X axis OpenCASCADE picks for `normal` (gp_Ax2).
// Circles, arcs and helices start where this direction points.
Vec3 default_plane_x_direction(const Vec3& normal);

// `_sketch_plane_in_current_coordinates`: a sketch plane, read in the current coordinate
// system, as a world-space frame.
struct PlaneFrame {
  Vec3 origin;
  Vec3 x_axis;
  Vec3 y_axis;
};
// `plane` is "XY" | "XZ" | "YZ" (any case) or an object with optional "origin", "x_axis",
// "y_axis" 3-vectors.  ValueError for anything else.
PlaneFrame sketch_plane_in_current_coordinates(const Value& plane);

}  // namespace scad

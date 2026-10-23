// Revolutions.
#pragma once

#include "scad/ops/features/tags.hpp"
#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// `profile` (a closed Wire or a Face) revolved `angle` degrees about the line through `origin`
// along `axis`.  Roles: revolution.start / .end (only below 360 degrees), revolution.side.
// Error "revolve_rsolid".
Solid revolve_rsolid(const Shape& profile, const Scalar3& axis = scalar3(0, 0, 1), const Scalar& angle = Scalar(360.0),
                     const Scalar3& origin = scalar3(0, 0, 0), const SweepTags& tags = {});

}  // namespace scad

// Helices.
#pragma once

#include <string>
#include <string_view>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// A helix of `pitch` rising to `height` on a cylinder of `radius` around the axis
// (`center`, `dir`).  "Right" winds counter-clockwise as it climbs, "Left" clockwise.
// Error "make_helix_redge": non-positive pitch / height / radius, another handedness.
Edge make_helix_redge(const Scalar& pitch, const Scalar& height, const Scalar& radius,
                      const Scalar3& center = scalar3(0, 0, 0), const Scalar3& dir = scalar3(0, 0, 1),
                      std::string_view handedness = "Right");

// The same helix as a wire.  (The Python SDK drops `handedness` here when it is not
// recording and builds a right-handed helix; this honours it on both paths.)
Wire make_helix_rwire(const Scalar& pitch, const Scalar& height, const Scalar& radius,
                      const Scalar3& center = scalar3(0, 0, 0), const Scalar3& dir = scalar3(0, 0, 1),
                      std::string_view handedness = "Right");

}  // namespace scad

// Rectangles, as wires and faces.
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

struct RectangleTags {
  OptionalString tag_prefix;                          // "<prefix>.wire" / "<prefix>.face"
  std::optional<std::vector<std::string>> edge_tags;  // one local name per edge; default line1..line4
};

// A width x height rectangle centered on `center`, in the plane through it with `normal`.
// The width runs along the plane's x axis (global X for a +Z normal), like make_box_rsolid's.
// Error "make_rectangle_rwire": a size that is not positive, a zero normal.
Wire make_rectangle_rwire(const Scalar& width, const Scalar& height, const Scalar3& center = scalar3(0, 0, 0),
                          const Scalar3& normal = scalar3(0, 0, 1), const RectangleTags& tags = {});
Face make_rectangle_rface(const Scalar& width, const Scalar& height, const Scalar3& center = scalar3(0, 0, 0),
                          const Scalar3& normal = scalar3(0, 0, 1), const RectangleTags& tags = {});

}  // namespace scad

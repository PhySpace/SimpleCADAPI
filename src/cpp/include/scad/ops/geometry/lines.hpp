// Points, straight edges, segments and polylines.
#pragma once

#include <vector>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// A vertex at (x, y, z) of the current coordinate system.
Vertex make_point_rvertex(const Scalar& x, const Scalar& y, const Scalar& z);

// A straight edge between two points of the current coordinate system.
Edge make_line_redge(const Scalar3& start, const Scalar3& end, const OptionalString& tag_prefix = std::nullopt);

// Alias of make_line_redge.
Edge make_segment_redge(const Scalar3& start, const Scalar3& end);
// A wire holding one straight segment.
Wire make_segment_rwire(const Scalar3& start, const Scalar3& end);

// Segments through `points`; `closed` joins the last point to the first (more than two points).
// Error "make_polyline_rwire": fewer than two points.
Wire make_polyline_rwire(const std::vector<Scalar3>& points, bool closed = false);

}  // namespace scad

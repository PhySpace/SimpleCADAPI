// B-spline edges and wires: exact (poles + knots) and interpolating.
#pragma once

#include <optional>
#include <vector>

#include "scad/core/tolerance.hpp"
#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// An exact B-spline.  `control_points` are poles, not points on the curve (see
// SplineInterpolation for that).  Defaults: a clamped cubic with uniform knots.
struct SplineSpec {
  std::vector<ScalarPoint> control_points;  // 2D or 3D, in the current coordinate system
  double degree = 3;                        // an integer from 1 to 25 (a double so that 3.5 is rejected as Python does)
  std::optional<ScalarList> knots;          // distinct knots, or a full non-decreasing vector
  std::optional<std::vector<int>> multiplicities;  // requires `knots` to be the distinct ones
  std::optional<ScalarList> weights;               // one positive weight per pole (rational spline)
  bool periodic = false;
};

// Error "make_spline_redge" / "make_spline_rwire": an inconsistent definition.
Edge make_spline_redge(const SplineSpec& spec);
Wire make_spline_rwire(const SplineSpec& spec);

// A B-spline through `points`.
struct SplineInterpolation {
  std::vector<ScalarPoint> points;
  bool periodic = false;  // closed: the first point need not be repeated at the end
  Scalar tolerance = Scalar(tol::kSplineInterpolation);
};

// Error "make_interpolated_spline_redge" / "_rwire": too few or coincident points.
Edge make_interpolated_spline_redge(const SplineInterpolation& spec);
Wire make_interpolated_spline_rwire(const SplineInterpolation& spec);
// make_interpolated_spline_rwire with periodic = true.
Wire make_periodic_spline_rwire(const std::vector<ScalarPoint>& points,
                                const Scalar& tolerance = Scalar(tol::kSplineInterpolation));

}  // namespace scad

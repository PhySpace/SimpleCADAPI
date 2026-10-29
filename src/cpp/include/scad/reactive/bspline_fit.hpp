// Fitting a minimal cubic B-spline to sampled curve points: port of
// simplecadapi/math.py (fit_cubic_bspline_control_points, BSplineFitResult).
//
// Parked in the reactive area because no other area owns `math.py`; it has no
// dependency on the rest of the library and can move without a change.
#pragma once

#include <optional>
#include <vector>

#include "scad/core/value.hpp"

namespace scad::reactive {

struct BSplineFitOptions {
  double tolerance = 1e-3;                // maximum Euclidean error at the samples
  std::optional<int> max_control_points;  // default: the cleaned sample count (at least 4)
  double fairing = 1e-6;                  // second-difference regularization weight
  double duplicate_tolerance = 1e-12;     // consecutive samples closer than this are merged
  double knot_tolerance = 1e-9;           // spacing threshold for interior knots
  bool raise_on_failure = true;
};

// A complete clamped cubic B-spline definition with how well it fits.
struct BSplineFit {
  int degree = 3;
  std::vector<std::vector<double>> control_points;
  std::vector<double> knots;  // full clamped knot vector
  std::vector<double> sample_parameters;
  double max_error = 0.0;
  double rms_error = 0.0;
  double tolerance = 0.0;
  double fairing = 0.0;
  int iterations = 0;
  bool converged = false;

  std::size_t control_count() const noexcept { return control_points.size(); }
  std::size_t dimension() const noexcept { return control_points.empty() ? 0 : control_points.front().size(); }
  std::vector<double> unique_knots() const;  // repeated entries collapsed
  std::vector<int> multiplicities() const;   // aligned with unique_knots()
  // The curve point at a normalized parameter in [0, 1].
  std::vector<double> evaluate(double parameter) const;
  Value to_value() const;
};

// ValueError for invalid inputs, and (raise_on_failure) when the tolerance
// cannot be met within the control-point budget.
BSplineFit fit_cubic_bspline_control_points(const std::vector<std::vector<double>>& sample_points,
                                            const BSplineFitOptions& options = {});

}  // namespace scad::reactive

// The argument normalisation of the B-spline makers (operators/geometry.py:
// _normalize_bspline_control_points / _knots / _weights, _normalize_interpolation_points).
//
// Each function evaluates its symbolic input and throws ValueError with the Python
// message when the definition is inconsistent; the operators wrap those into their error.
#pragma once

#include <optional>
#include <vector>

#include "scad/core/vec.hpp"
#include "scad/ops/geometry/types.hpp"

namespace scad::bspline {

// Distinct knots and how often each repeats.
struct Knots {
  std::vector<double> unique;
  std::vector<int> multiplicities;
};

// Poles of 2 or 3 coordinates (a missing z is 0); at least one.
std::vector<Vec3> control_points(const std::vector<ScalarPoint>& points);

// A full knot vector (non-decreasing) collapsed into distinct knots and multiplicities.
Knots collapse_knot_vector(const ScalarList& knots);
// Uniform knots; clamped (degree + 1 at the ends) unless periodic.
Knots default_knots(int control_count, int degree, bool periodic);
// `knots` absent: the defaults.  `knots` alone: a full vector, collapsed.  Both: distinct
// knots with explicit multiplicities.  The multiplicities must sum to the count the
// degree and periodicity demand.
Knots normalize_knots(int control_count, int degree, bool periodic, const std::optional<ScalarList>& knots,
                      const std::optional<std::vector<int>>& multiplicities);

// One finite positive weight per pole, or nullopt.
std::optional<std::vector<double>> normalize_weights(const std::optional<ScalarList>& weights, int control_count);

// Interpolation points: a periodic list may repeat its first point at the end (dropped);
// consecutive points must be farther apart than `tolerance`.
std::vector<Vec3> interpolation_points(const std::vector<ScalarPoint>& points, bool periodic, double tolerance);

}  // namespace scad::bspline

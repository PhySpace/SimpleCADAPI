// Knot / weight normalisation for B-spline entities: the helpers
// operators/geometry.py shares between make_spline_redge and sketch B-splines.
#pragma once

#include <optional>
#include <utility>
#include <vector>

namespace scad {

struct BSplineKnots {
  std::vector<double> knots;  // unique, strictly increasing
  std::vector<int> multiplicities;
};

// ValueError with the Python messages when the definition is inconsistent.
// `knots` empty + `multiplicities` empty: uniform defaults; `knots` alone: a
// full knot vector collapsed into unique knots and multiplicities.
BSplineKnots normalize_bspline_knots(int control_count, int degree, bool periodic,
                                     const std::optional<std::vector<double>>& knots,
                                     const std::optional<std::vector<int>>& multiplicities);

std::optional<std::vector<double>> normalize_bspline_weights(const std::optional<std::vector<double>>& weights,
                                                             int control_count);

}  // namespace scad

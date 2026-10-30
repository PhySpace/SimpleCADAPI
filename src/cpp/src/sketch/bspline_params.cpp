#include "scad/core/tolerance.hpp"
#include "scad/sketch/bspline_params.hpp"

#include <cmath>
#include <string>

#include "scad/core/error.hpp"

namespace scad {

namespace {

BSplineKnots collapse_knot_vector(const std::vector<double>& values) {
  if (values.empty())
    throw ValueError("knots must not be empty");
  for (const double value : values) {
    if (!std::isfinite(value))
      throw ValueError("knots must contain only finite values");
  }
  for (std::size_t i = 1; i < values.size(); ++i) {
    if (values[i] < values[i - 1]) {
      throw ValueError("knots must be non-decreasing when passed as a full knot vector");
    }
  }
  BSplineKnots out;
  for (const double value : values) {
    if (!out.knots.empty() && std::abs(value - out.knots.back()) <= tol::kDuplicateParameter) {
      ++out.multiplicities.back();
    } else {
      out.knots.push_back(value);
      out.multiplicities.push_back(1);
    }
  }
  return out;
}

BSplineKnots default_knots(int control_count, int degree, bool periodic) {
  BSplineKnots out;
  if (periodic) {
    const int knot_count = control_count + 1;
    for (int i = 0; i < knot_count; ++i) {
      out.knots.push_back(static_cast<double>(i) / static_cast<double>(knot_count - 1));
      out.multiplicities.push_back(1);
    }
    return out;
  }
  const int knot_count = control_count - degree + 1;
  if (knot_count < 2)
    throw ValueError("control point count must be at least degree + 1");
  for (int i = 0; i < knot_count; ++i) {
    out.knots.push_back(static_cast<double>(i) / static_cast<double>(knot_count - 1));
  }
  out.multiplicities.push_back(degree + 1);
  for (int i = 0; i < knot_count - 2; ++i)
    out.multiplicities.push_back(1);
  out.multiplicities.push_back(degree + 1);
  return out;
}

}  // namespace

BSplineKnots normalize_bspline_knots(int control_count, int degree, bool periodic,
                                     const std::optional<std::vector<double>>& knots,
                                     const std::optional<std::vector<int>>& multiplicities) {
  BSplineKnots out;
  if (!knots) {
    if (multiplicities)
      throw ValueError("multiplicities require explicit knots");
    out = default_knots(control_count, degree, periodic);
  } else if (!multiplicities) {
    out = collapse_knot_vector(*knots);
  } else {
    out.knots = *knots;
    out.multiplicities = *multiplicities;
  }

  if (out.knots.size() != out.multiplicities.size()) {
    throw ValueError("knots and multiplicities must have the same length");
  }
  if (out.knots.size() < 2)
    throw ValueError("at least two unique knots are required");
  for (const double knot : out.knots) {
    if (!std::isfinite(knot))
      throw ValueError("knots must contain only finite values");
  }
  for (std::size_t i = 1; i < out.knots.size(); ++i) {
    if (out.knots[i] <= out.knots[i - 1])
      throw ValueError("unique knots must be strictly increasing");
  }
  int total = 0;
  for (const int multiplicity : out.multiplicities) {
    if (multiplicity <= 0)
      throw ValueError("multiplicities must be positive integers");
    if (multiplicity > degree + 1)
      throw ValueError("multiplicities must not exceed degree + 1");
    total += multiplicity;
  }
  const int expected = control_count + (periodic ? 1 : degree + 1);
  if (total != expected) {
    throw ValueError("sum(multiplicities) must equal " + std::to_string(expected) + " for this " +
                     (periodic ? "periodic" : "non-periodic") + " B-spline");
  }
  return out;
}

std::optional<std::vector<double>> normalize_bspline_weights(const std::optional<std::vector<double>>& weights,
                                                             int control_count) {
  if (!weights)
    return std::nullopt;
  if (static_cast<int>(weights->size()) != control_count) {
    throw ValueError("weights must contain exactly one value per control point");
  }
  for (const double weight : *weights) {
    if (!std::isfinite(weight) || weight <= 0.0)
      throw ValueError("weights must be finite positive values");
  }
  return weights;
}

}  // namespace scad

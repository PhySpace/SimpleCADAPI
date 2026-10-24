#include "scad/ops/geometry/bspline_args.hpp"

#include <cmath>
#include <numeric>
#include <string>

#include "scad/core/error.hpp"

namespace scad::bspline {

std::vector<Vec3> control_points(const std::vector<ScalarPoint>& points) {
  if (points.empty()) throw ValueError("control_points must contain at least one point");
  std::vector<Vec3> normalized;
  normalized.reserve(points.size());
  for (std::size_t index = 0; index < points.size(); ++index) {
    const ScalarPoint& point = points[index];
    if (point.size() != 2 && point.size() != 3) throw ValueError("control point " + std::to_string(index) + " must be 2D or 3D");
    const std::string label = "control_points[" + std::to_string(index) + "]";
    const Vec3 coordinates{evaluate_scalar(point[0], label + "[0]"), evaluate_scalar(point[1], label + "[1]"),
                           point.size() == 3 ? evaluate_scalar(point[2], label + "[2]") : 0.0};
    if (!coordinates.is_finite()) throw ValueError("control point " + std::to_string(index) + " contains a non-finite coordinate");
    normalized.push_back(coordinates);
  }
  return normalized;
}

Knots collapse_knot_vector(const ScalarList& knots) {
  std::vector<double> values;
  values.reserve(knots.size());
  for (const Scalar& knot : knots) values.push_back(evaluate_scalar(knot, "knots"));
  if (values.empty()) throw ValueError("knots must not be empty");
  for (std::size_t i = 1; i < values.size(); ++i) {
    if (values[i] < values[i - 1]) throw ValueError("knots must be non-decreasing when passed as a full knot vector");
  }
  Knots out;
  for (const double value : values) {
    if (!out.unique.empty() && std::abs(value - out.unique.back()) <= 1e-12) {
      ++out.multiplicities.back();
    } else {
      out.unique.push_back(value);
      out.multiplicities.push_back(1);
    }
  }
  return out;
}

Knots default_knots(int control_count, int degree, bool periodic) {
  const auto uniform = [](int count) {
    std::vector<double> knots;
    knots.reserve(static_cast<std::size_t>(count));
    for (int i = 0; i < count; ++i) knots.push_back(static_cast<double>(i) / static_cast<double>(count - 1));
    return knots;
  };
  if (periodic) {
    const int count = control_count + 1;
    return {uniform(count), std::vector<int>(static_cast<std::size_t>(count), 1)};
  }
  const int count = control_count - degree + 1;
  if (count < 2) throw ValueError("control point count must be at least degree + 1");
  std::vector<int> multiplicities(static_cast<std::size_t>(count), 1);
  multiplicities.front() = multiplicities.back() = degree + 1;
  return {uniform(count), std::move(multiplicities)};
}

Knots normalize_knots(int control_count, int degree, bool periodic, const std::optional<ScalarList>& knots,
                      const std::optional<std::vector<int>>& multiplicities) {
  Knots resolved;
  if (!knots) {
    if (multiplicities) throw ValueError("multiplicities require explicit knots");
    resolved = default_knots(control_count, degree, periodic);
  } else if (!multiplicities) {
    resolved = collapse_knot_vector(*knots);
  } else {
    for (const Scalar& knot : *knots) resolved.unique.push_back(evaluate_scalar(knot, "knots"));
    resolved.multiplicities = *multiplicities;
  }

  if (resolved.unique.size() != resolved.multiplicities.size()) {
    throw ValueError("knots and multiplicities must have the same length");
  }
  if (resolved.unique.size() < 2) throw ValueError("at least two unique knots are required");
  for (const double knot : resolved.unique) {
    if (!std::isfinite(knot)) throw ValueError("knots must contain only finite values");
  }
  for (std::size_t i = 1; i < resolved.unique.size(); ++i) {
    if (resolved.unique[i] <= resolved.unique[i - 1]) throw ValueError("unique knots must be strictly increasing");
  }
  for (const int multiplicity : resolved.multiplicities) {
    if (multiplicity <= 0) throw ValueError("multiplicities must be positive integers");
  }
  for (const int multiplicity : resolved.multiplicities) {
    if (multiplicity > degree + 1) throw ValueError("multiplicities must not exceed degree + 1");
  }

  const int expected = control_count + (periodic ? 1 : degree + 1);
  const int actual = std::accumulate(resolved.multiplicities.begin(), resolved.multiplicities.end(), 0);
  if (actual != expected) {
    throw ValueError("sum(multiplicities) must equal " + std::to_string(expected) + " for this " +
                     (periodic ? "periodic" : "non-periodic") + " B-spline");
  }
  return resolved;
}

std::optional<std::vector<double>> normalize_weights(const std::optional<ScalarList>& weights, int control_count) {
  if (!weights) return std::nullopt;
  std::vector<double> values;
  values.reserve(weights->size());
  for (const Scalar& weight : *weights) values.push_back(evaluate_scalar(weight, "weights"));
  if (values.size() != static_cast<std::size_t>(control_count)) {
    throw ValueError("weights must contain exactly one value per control point");
  }
  for (const double value : values) {
    if (!std::isfinite(value) || value <= 0.0) throw ValueError("weights must be finite positive values");
  }
  return values;
}

std::vector<Vec3> interpolation_points(const std::vector<ScalarPoint>& points, bool periodic, double tolerance) {
  std::vector<Vec3> normalized = control_points(points);
  if (periodic && normalized.size() >= 2 && (normalized.front() - normalized.back()).norm() <= tolerance) {
    normalized.pop_back();
  }
  const std::size_t minimum = periodic ? 3 : 2;
  if (normalized.size() < minimum) {
    throw ValueError("interpolation requires at least " + std::to_string(minimum) + (periodic ? " distinct" : "") + " points");
  }
  const std::size_t pairs = periodic ? normalized.size() : normalized.size() - 1;
  for (std::size_t index = 0; index < pairs; ++index) {
    const std::size_t next = (index + 1) % normalized.size();
    if ((normalized[index] - normalized[next]).norm() <= tolerance) {
      throw ValueError("interpolation points " + std::to_string(index) + " and " + std::to_string(next) +
                       " are within the interpolation tolerance");
    }
  }
  return normalized;
}

}  // namespace scad::bspline
